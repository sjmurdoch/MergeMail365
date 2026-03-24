import csv
import logging
from pathlib import Path

from rich.text import Text

from mail_merge.console import console
from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)

# Characters that trigger formula execution in spreadsheet applications
_CSV_FORMULA_PREFIXES = ("=", "+", "@", "-", "\t", "\r")


def _sanitize_csv(value: str) -> str:
    """Prefix values that would be interpreted as spreadsheet formulas with a tab."""
    if value.startswith(_CSV_FORMULA_PREFIXES):
        return "\t" + value
    return value


def summarize(results: list[SendResult]) -> dict[str, object]:
    """Return structured summary: total, sent, failed counts + failed details."""
    total = len(results)
    sent = sum(1 for r in results if r.success)
    failed = total - sent
    failed_details = [
        {"email": r.email, "status_code": r.status_code, "error": r.error}
        for r in results
        if not r.success
    ]
    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "failed_details": failed_details,
    }


def print_summary(results: list[SendResult]) -> None:
    summary = summarize(results)
    total = summary["total"]
    sent = summary["sent"]
    failed = summary["failed"]

    logger.info("Summary: Total: %d, Sent: %d, Failed: %d", total, sent, failed)

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
                logger.warning("Failed: %s [%s] %s", r.email, r.status_code, r.error)
                console.print(f"  [red]{r.email}[/red]: [{r.status_code}] {r.error}")


def write_csv(results: list[SendResult], path: str | Path) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "success", "status_code", "error"])
        for r in results:
            writer.writerow([_sanitize_csv(r.email), r.success, r.status_code or "", _sanitize_csv(r.error)])
    logger.info("Report written to %s", path)


def read_csv(path: str | Path) -> list[SendResult]:
    """Read back a CSV report written by :func:`write_csv`.

    Returns a list of :class:`SendResult` with ``throttled`` defaulting to
    ``False`` (not persisted in the CSV).
    """
    path = Path(path)
    results: list[SendResult] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status_raw = row.get("status_code", "")
            results.append(SendResult(
                email=row["email"],
                success=row["success"] == "True",
                status_code=int(status_raw) if status_raw else None,
                error=row.get("error", ""),
            ))
    return results
