import csv
import logging
from pathlib import Path

from rich.text import Text

from mail_merge.console import console
from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)


def print_summary(results: list[SendResult]) -> None:
    total = len(results)
    sent = sum(1 for r in results if r.success)
    failed = total - sent

    console.rule("Summary")
    console.print(f"  Total:  {total}")
    sent_text = Text(f"  Sent:   {sent}")
    if sent:
        sent_text.stylize("green")
    console.print(sent_text)
    failed_text = Text(f"  Failed: {failed}")
    if failed:
        failed_text.stylize("bold red")
    console.print(failed_text)
    console.rule()

    if failed:
        console.print("\n[bold red]Failed recipients:[/bold red]")
        for r in results:
            if not r.success:
                console.print(f"  [red]{r.email}[/red]: [{r.status_code}] {r.error}")


def write_csv(results: list[SendResult], path: str | Path) -> None:
    path = Path(path)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "success", "status_code", "error"])
        for r in results:
            writer.writerow([r.email, r.success, r.status_code or "", r.error])
    logger.info("Report written to %s", path)
