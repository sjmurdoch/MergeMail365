"""The real mergemail365-web process and its port (docs/phase-h-guards-plan.md,
class C).

Phase H found that a second copy of the app shared the first one's port on
Windows, and that reopening the app just after quitting moved it to the
next port on macOS (another origin, so the page's saved fields were gone).
Both depend on what the operating system does with the server's own
socket, which differs between platforms, so these tests start the entry
point as a separate process, as a user does, on whichever platform runs
them. Only the opening of a browser is replaced.
"""

import http.cookiejar
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("flask")

# main() as the console script runs it, without opening the user's browser.
LAUNCH = (
    "import sys, webbrowser\n"
    "webbrowser.open = lambda *args, **kwargs: True\n"
    "from mail_merge.web import main\n"
    "main(sys.argv[1:])\n"
)
# The console wraps long lines, so the log is searched with its white space
# removed; the token is secrets.token_urlsafe(32), 43 characters.
ACCESS_URL = re.compile(r"AccessURL:http://localhost:(\d+)/\?token=([\w-]{43})")
# Inside the range the app searches (5050-5099), away from 5050 itself in
# case the developer has the app open.
FIRST_PORT = 5070


class Copy:
    """One running copy of the app."""

    def __init__(self, home: Path, port: int) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("MERGEMAIL365_")}
        env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / "AppData"),
                   NO_COLOR="1", TERM="dumb", PYTHONUNBUFFERED="1")
        env.pop("XDG_STATE_HOME", None)
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", LAUNCH, "--port", str(port), "--client-id", "process-test"],
            env=env, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        )
        self.output: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        self.port, self.token = 0, ""

    def wait_until_started(self) -> None:
        self.port, self.token = self._wait_for_url()

    def _read(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.output.append(line)

    def _wait_for_url(self) -> tuple[int, str]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            found = ACCESS_URL.search(re.sub(r"\s+", "", "".join(self.output)))
            if found:
                return int(found.group(1)), found.group(2)
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        raise AssertionError("the app did not start:\n" + "".join(self.output))

    def get(self, token: str | None = None) -> int:
        """The status of the wizard page for someone holding `token`."""
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        url = f"http://127.0.0.1:{self.port}/?token={token or self.token}"
        for _ in range(100):  # the URL is logged just before the server listens
            try:
                with opener.open(url, timeout=5) as resp:
                    return int(resp.status)
            except urllib.error.HTTPError as exc:
                return exc.code
            except OSError:
                time.sleep(0.05)
        raise AssertionError(f"nothing answers on port {self.port}:\n" + "".join(self.output))

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(10)


@pytest.fixture
def start(tmp_path: Path) -> Iterator[type[Copy]]:
    copies: list[Copy] = []

    def start_copy(port: int = FIRST_PORT) -> Copy:
        copy = Copy(tmp_path, port)
        copies.append(copy)  # before waiting, so a copy that fails to start is still stopped
        copy.wait_until_started()
        return copy

    yield start_copy  # type: ignore[misc]
    for copy in copies:
        if copy.proc.poll() is None:
            copy.kill()


def test_a_second_copy_gets_its_own_port(start):
    """Phase H, Windows rc2: both copies listened on 5050 and the second
    window talked to the first copy's server."""
    first = start()
    second = start(first.port)
    assert second.port != first.port
    assert first.get() == 200
    assert second.get() == 200
    # Each port is served by its own copy: the other's token is refused.
    assert first.get(second.token) == 403
    assert second.get(first.token) == 403


def test_reopening_after_a_kill_keeps_the_port(start):
    """Phase H, macOS rc3: the app was quit during a send, with the page's
    connections open; started again at once, it found its port "in use"
    (connections still closing) and moved to the next, where the page's
    saved subject, body and columns are not."""
    first = start()
    assert first.get() == 200
    # A connection the server has not finished with when the app dies, as
    # the page's event stream is during a send. (One whose request has been
    # answered doesn't keep the port busy; this one does, for 30 seconds on
    # macOS, unless the probe allows for it.)
    with socket.create_connection(("127.0.0.1", first.port), timeout=5):
        first.kill()
    again = start(first.port)
    assert again.port == first.port
    assert again.get() == 200
