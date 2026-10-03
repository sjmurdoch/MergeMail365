"""Shared by the conformance tests (tests/test_conformance.py,
tests/test_conformance_e2e.py): ITF trace loading and a send_merge()
stand-in whose jobs are driven one model action at a time."""

import json
import queue
from pathlib import Path
from typing import Any

TOTAL = 3  # spec/wizard.qnt TOTAL: emails in a send


def decode(v: Any) -> Any:
    """ITF JSON to plain Python values (as in tests/js/conformance.test.js)."""
    if isinstance(v, list):
        return [decode(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "#bigint" in v:
        return int(v["#bigint"])
    for key in ("#set", "#tup", "#map"):
        if key in v:
            return [decode(x) for x in v[key]]
    if set(v) == {"tag", "value"}:
        value = decode(v["value"])
        return v["tag"] if value == [] else {"tag": v["tag"], "value": value}
    return {k: decode(x) for k, x in v.items()}


def load_trace(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    s_var = next(v for v in raw["vars"] if v.endswith("::s"))
    states = []
    for st in raw["states"]:
        picks = decode(st["mbt::nondetPicks"])
        states.append({
            "s": decode(st[s_var]),
            "action": st["mbt::actionTaken"],
            # decode() turns None (a variant without payload) into "None".
            "picks": {k: p["value"] for k, p in picks.items() if isinstance(p, dict) and p["tag"] == "Some"},
        })
    return states


class Handle:
    """One job's fake send_merge() call, driven one command at a time."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.commands: queue.Queue[str] = queue.Queue()
        self.acks: queue.Queue[None] = queue.Queue()


class FakeSendMerge:
    """send_merge() for the server tier. Test emails and dry runs wait for
    "ok" or "fail"; a send waits for "next" before each step of its loop, in
    which the real should_stop, token provider and on_result decide what
    happens, or "fail" (the Graph API failing the send)."""

    def __init__(self) -> None:
        self.started: queue.Queue[Handle] = queue.Queue()

    def __call__(self, **kw: Any) -> list[Any]:
        from mail_merge.sender import SendAborted, SendResult

        mode = "test_email" if kw.get("test_email") else "send" if kw.get("send") else "dry_run"
        h = Handle(mode)
        self.started.put(h)
        if mode != "send":
            if h.commands.get(timeout=60) != "ok":
                raise RuntimeError("job failed")
            if mode == "test_email":
                kw["token_provider"]()
            return []
        results: list[Any] = []
        while True:
            if h.commands.get(timeout=60) != "next":
                raise SendAborted("send failed", results)
            # As in sender.send_all: Stop is checked before each email, so
            # once the last has gone the loop ends without asking.
            if len(results) == TOTAL or kw["should_stop"]():
                return results
            try:
                kw["token_provider"]()
            except Exception as exc:
                raise SendAborted(str(exc), results) from exc
            results.append(SendResult(email=f"r{len(results)}@example.com", success=True, status_code=202))
            kw["on_result"](results[-1])
            h.acks.put(None)


