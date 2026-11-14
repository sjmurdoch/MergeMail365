"""The app only touches files it owns, and its private files are private
from the moment they exist (docs/review-fixes-plan.md, F3, G3).

The footprint test gives the app a fake home directory, runs a sign-in, a
CLI send and a web send in it, and then looks at everything that changed:
the home directory's own mode must be as it was (saving the token cache
used to chmod it to 0700), every new file must be one the app is expected
to write, and everything holding tokens, addresses or logs must be for the
user only.
"""

import logging
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import openpyxl
import pytest
import responses

import mail_merge.auth as auth_module
from mail_merge import _paths
from mail_merge._paths import open_private_append, private_dir, write_private
from mail_merge.cli import main
from mail_merge.sender import GRAPH_SEND_URL
from tests.test_msal_contract import (  # noqa: F401  (entra is a fixture)
    CLIENT_ID,
    REDIRECT_URI,
    TENANT_ID,
    TOKEN_ENDPOINT,
    _token_response,
    entra,
)

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A home directory other users may enter (0755), holding a file of the
    user's own, and a working directory outside it."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "Documents").mkdir()
    (home / "Documents" / "thesis.txt").write_text("mine", encoding="utf-8")
    home.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert Path.home() == home
    # Paths the modules worked out when they were imported.
    monkeypatch.setattr(auth_module, "CACHE_PATH", home / ".mergemail365-token-cache.json")
    monkeypatch.setattr("mail_merge.config.DEFAULT_PATH", home / ".mergemail365.toml")
    monkeypatch.setattr("mail_merge.sender.time.sleep", lambda _s: None)

    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    try:
        yield home
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level)


def tree(top: Path) -> set[Path]:
    return {p for p in top.rglob("*")}


@unix_only
def test_footprint_of_sign_in_cli_send_and_web_send(
    home: Path, tmp_path: Path, entra: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    pytest.importorskip("flask")
    from mail_merge.diagnostics import start_diagnostics
    from mail_merge.web.app import _job_store, create_app
    from mail_merge.web.sendlog import SendLog

    # The entra fixture points the cache at a scratch file; put it back
    # where the app keeps it, so that saving it is part of the footprint.
    monkeypatch.setattr(auth_module, "CACHE_PATH", home / ".mergemail365-token-cache.json")
    before = tree(home)
    work = tmp_path / "work"
    work.mkdir()
    xlsx = work / "people.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "email"])
    ws.append(["Alice", "alice@example.com"])
    wb.save(xlsx)
    (work / "body.txt").write_text("Hello {{name}}", encoding="utf-8")
    entra.add(responses.POST, GRAPH_SEND_URL, status=202)

    # 1. Sign in with real msal: writes the token cache.
    flow = auth_module.initiate_auth_code_flow(CLIENT_ID, TENANT_ID, REDIRECT_URI)
    nonce = parse_qs(urlparse(flow["auth_uri"]).query)["nonce"][0]
    entra.post(TOKEN_ENDPOINT, json=_token_response(nonce=nonce))
    auth_module.acquire_token_by_auth_code(CLIENT_ID, TENANT_ID, flow, {"code": "c", "state": flow["state"]})

    # 2. A CLI send with a report and file logging, using the cached token.
    assert main([
        "--spreadsheet", str(xlsx), "--body", str(work / "body.txt"), "--subject", "Hi",
        "--email-column", "email", "--client-id", CLIENT_ID, "--tenant-id", TENANT_ID,
        "--device-code", "--send", "--yes", "--delay", "0", "--log-file", "--output", str(work / "out.csv"),
    ]) == 0

    # 3. The web app as mergemail365-web starts it: diagnostics and a send log.
    watchdog = start_diagnostics(_paths.log_dir())
    send_log_dir = _paths.state_dir() / "sends"  # as web/__init__.py main() passes it
    try:
        app = create_app(startup_token="t", client_id=CLIENT_ID, tenant_id=TENANT_ID, send_log_dir=send_log_dir)
        client = app.test_client()
        client.get("/?token=t")
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        with xlsx.open("rb") as f:
            client.post("/api/upload-spreadsheet", data={"spreadsheet": (f, "people.xlsx")}, headers=headers)
        job_id = client.post("/api/start-job", data={
            "mode": "send", "email_column": "email", "subject": "Hi", "body": "Hello",
        }, headers=headers).get_json()["job_id"]
        client.get(f"/api/job/{job_id}/events").get_data()
        assert client.get(f"/api/job/{job_id}/status").get_json()["ok"]
        # A send the process never finished leaves its log behind.
        interrupted = SendLog(send_log_dir)
        interrupted.start("interrupted")
    finally:
        watchdog.stop()
        if watchdog.dump_file is not None:
            watchdog.dump_file.close()
        _job_store.send_log = None
        _job_store.interrupted = []

    # --- What changed under the home directory? ---
    assert mode(home) == 0o755, "the home directory's permissions were changed"
    assert (home / "Documents" / "thesis.txt").read_text(encoding="utf-8") == "mine"

    log_dir, state_dir = _paths.log_dir(), _paths.state_dir()
    private_files = {
        auth_module.CACHE_PATH,
        log_dir / "mergemail365.log",
        log_dir / "mergemail365-stalls.log",
        send_log_dir / "send-interrupted.jsonl",
    }
    # state_dir itself only holds the (private) sends directory.
    private_dirs = {log_dir, send_log_dir}
    expected = private_files | private_dirs | {state_dir}
    # Directories on the way to the app's own (~/Library, ~/.local/state, ...).
    on_the_way = {parent for p in expected for parent in p.parents if home in parent.parents}

    created = tree(home) - before
    assert private_files <= created, f"expected files were not written: {sorted(private_files - created)}"
    unexpected = created - expected - on_the_way
    assert not unexpected, f"the app wrote files it is not expected to: {sorted(unexpected)}"
    for path in private_files:
        assert mode(path) == 0o600, f"{path} is {oct(mode(path))}, not 0600"
    for path in private_dirs:
        assert mode(path) == 0o700, f"{path} is {oct(mode(path))}, not 0700"

    # Nothing the user owns outside the app's directories lost access either.
    assert mode(home / "Documents") & 0o055 == 0o055


class TestPrivateDir:
    def test_refuses_the_home_directory_and_its_ancestors(self, home: Path) -> None:
        for path in (home, home.parent, Path(home.anchor)):
            with pytest.raises(ValueError, match="not a directory of the app's own"):
                private_dir(path)
        assert mode(home) == 0o755 or sys.platform == "win32"

    @unix_only
    def test_creates_and_restricts_a_directory_of_the_apps_own(self, home: Path) -> None:
        target = home / "Library" / "Logs" / "mergemail365"
        target.mkdir(parents=True)
        target.chmod(0o755)  # as an earlier version left it
        assert private_dir(target) == target
        assert mode(target) == 0o700
        assert mode(home) == 0o755

    @unix_only
    def test_an_unwritable_log_directory_disables_file_logging(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from mail_merge.console import setup_file_logging

        monkeypatch.setattr(_paths, "log_dir", lambda: home)  # would mean chmod of the home directory
        assert setup_file_logging() is None
        assert mode(home) == 0o755


class TestWritePrivate:
    @unix_only
    def test_file_is_private_and_directory_untouched(self, tmp_path: Path) -> None:
        tmp_path.chmod(0o755)
        target = tmp_path / "cache.json"
        write_private(target, "{}")
        assert target.read_text(encoding="utf-8") == "{}"
        assert mode(target) == 0o600
        assert mode(tmp_path) == 0o755

    @unix_only
    def test_replacing_a_world_readable_file_makes_it_private(self, tmp_path: Path) -> None:
        target = tmp_path / "cache.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        write_private(target, "new")
        assert mode(target) == 0o600

    @pytest.mark.parametrize("failing", ["write", "replace"])
    def test_a_failed_write_keeps_the_previous_contents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str,
    ) -> None:
        target = tmp_path / "cache.json"
        write_private(target, '{"token": "good"}')

        def boom(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "fsync" if failing == "write" else "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            write_private(target, "half-writ")
        monkeypatch.undo()

        assert target.read_text(encoding="utf-8") == '{"token": "good"}'
        assert [p.name for p in tmp_path.iterdir()] == ["cache.json"], "a temporary file was left behind"

    def test_never_exposes_a_partial_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A reader (another mergemail365 process) sees the old contents or
        the new, never a truncated file."""
        target = tmp_path / "cache.json"
        write_private(target, "old")
        seen = []
        real_replace = os.replace

        def watching_replace(src: str, dst: object) -> None:
            seen.append(target.read_text(encoding="utf-8"))
            real_replace(src, dst)  # type: ignore[arg-type]

        monkeypatch.setattr(os, "replace", watching_replace)
        write_private(target, "new contents")
        assert seen == ["old"]
        assert target.read_text(encoding="utf-8") == "new contents"


class TestOpenPrivateAppend:
    @unix_only
    def test_new_and_existing_files_are_private(self, tmp_path: Path) -> None:
        new = tmp_path / "new.log"
        with open_private_append(new) as f:
            f.write("a\n")
            assert f.name == str(new)
        assert mode(new) == 0o600

        old = tmp_path / "old.log"
        old.write_text("x\n", encoding="utf-8")
        old.chmod(0o644)
        with open_private_append(old) as f:
            f.write("y\n")
        assert mode(old) == 0o600
        assert old.read_text(encoding="utf-8") == "x\ny\n"


class TestCorruptTokenCache:
    def test_a_corrupt_cache_is_ignored_with_a_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text('{"AccessToken": {"trunc', encoding="utf-8")
        monkeypatch.setattr(auth_module, "CACHE_PATH", cache_path)
        with caplog.at_level(logging.WARNING):
            cache = auth_module._load_cache()
        assert cache.serialize() in ("{}", ""), "an unreadable cache should load as empty"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1 and str(cache_path) in warnings[0].getMessage()

    def test_signing_in_again_replaces_a_corrupt_cache(
        self, tmp_path: Path, entra: responses.RequestsMock,  # noqa: F811
    ) -> None:
        auth_module.CACHE_PATH.write_text("not json", encoding="utf-8")
        with pytest.raises(auth_module.NotSignedInError):
            auth_module.acquire_token_silent(CLIENT_ID, TENANT_ID)
        flow = auth_module.initiate_auth_code_flow(CLIENT_ID, TENANT_ID, REDIRECT_URI)
        nonce = parse_qs(urlparse(flow["auth_uri"]).query)["nonce"][0]
        entra.post(TOKEN_ENDPOINT, json=_token_response(nonce=nonce))
        token = auth_module.acquire_token_by_auth_code(CLIENT_ID, TENANT_ID, flow, {"code": "c", "state": flow["state"]})
        assert auth_module.acquire_token_silent(CLIENT_ID, TENANT_ID) == token
