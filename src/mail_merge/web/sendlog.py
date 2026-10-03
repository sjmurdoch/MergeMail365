"""A send's results on disk while it runs, so a send the process didn't
finish (the app quit or crashed) can still be reported (spec/requirements.md,
R15; spec/wizard.qnt `sendLog`).

Each running send has a JSON-lines file: a header, then one line per email
as the send loop records it. A send that ends in this process deletes its
file, since its results are then in memory and on the page; a file left over
from an earlier process is an interrupted send. The files hold recipient
addresses, so they are readable by the user only and deleted as soon as the
user dismisses the report.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)


class SendLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, job_id: str) -> Path:
        return self.directory / f"send-{job_id}.jsonl"

    def _append(self, job_id: str, entry: dict[str, Any]) -> None:
        path = self._path(job_id)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def start(self, job_id: str) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._append(job_id, {"started": time.strftime("%Y-%m-%d %H:%M:%S")})
        except OSError:
            logger.warning("Could not write the send log in %s", self.directory, exc_info=True)

    def record(self, job_id: str, result: SendResult) -> None:
        try:
            self._append(job_id, {
                "email": result.email, "success": result.success,
                "status_code": result.status_code, "error": result.error,
            })
        except OSError:
            logger.warning("Could not write the send log in %s", self.directory, exc_info=True)

    def finish(self, job_id: str) -> None:
        self._path(job_id).unlink(missing_ok=True)

    def interrupted(self) -> list[dict[str, Any]]:
        """The sends earlier processes left unfinished, oldest first:
        {"file", "started", "results"}. A line cut short by a crash is
        skipped."""
        sends = []
        for path in sorted(self.directory.glob("send-*.jsonl"), key=lambda p: p.stat().st_mtime):
            started = None
            results = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "started" in entry:
                    started = entry["started"]
                elif "email" in entry:
                    results.append(entry)
            sends.append({"file": path.name, "started": started, "results": results})
        return sends

    def dismiss(self, files: list[str]) -> None:
        for name in files:
            (self.directory / name).unlink(missing_ok=True)
