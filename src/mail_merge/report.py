import csv
import logging
import sys
from pathlib import Path

from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)


def print_summary(results: list[SendResult], file=sys.stderr) -> None:
    total = len(results)
    sent = sum(1 for r in results if r.success)
    failed = total - sent

    print(f"\n{'='*40}", file=file)
    print(f"Total:  {total}", file=file)
    print(f"Sent:   {sent}", file=file)
    print(f"Failed: {failed}", file=file)
    print(f"{'='*40}", file=file)

    if failed:
        print("\nFailed recipients:", file=file)
        for r in results:
            if not r.success:
                print(f"  {r.email}: [{r.status_code}] {r.error}", file=file)


def write_csv(results: list[SendResult], path: str | Path) -> None:
    path = Path(path)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "success", "status_code", "error"])
        for r in results:
            writer.writerow([r.email, r.success, r.status_code or "", r.error])
    logger.info("Report written to %s", path)
