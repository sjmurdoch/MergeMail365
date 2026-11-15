import logging

from mail_merge.report import print_summary, read_csv, summarize, write_csv
from mail_merge.sender import SendResult


class TestPrintSummary:
    def test_all_success_no_warnings(self, caplog):
        results = [
            SendResult(email="a@x.com", success=True, status_code=202),
            SendResult(email="b@x.com", success=True, status_code=202),
        ]
        with caplog.at_level(logging.INFO, logger="mail_merge.report"):
            print_summary(results)
        assert "Total: 2, Sent: 2, Failed: 0" in caplog.text
        assert "Failed:" not in caplog.text.replace("Failed: 0", "")

    def test_dry_run_says_nothing_was_sent(self, caplog):
        """A dry run's emails were only composed (phase H, macOS)."""
        results = [SendResult(email="a@x.com", success=True), SendResult(email="b@x.com", success=True)]
        with caplog.at_level(logging.INFO, logger="mail_merge.report"):
            print_summary(results, dry_run=True)
        assert caplog.messages == ["Dry run summary (nothing sent): Total: 2, Would send: 2, Failed: 0"]

    def test_with_failures_logs_each_failed_recipient(self, caplog):
        results = [
            SendResult(email="a@x.com", success=True, status_code=202),
            SendResult(email="b@x.com", success=False, status_code=403, error="Forbidden"),
        ]
        with caplog.at_level(logging.INFO, logger="mail_merge.report"):
            print_summary(results)
        assert "Total: 2, Sent: 1, Failed: 1" in caplog.text
        assert "b@x.com" in caplog.text
        assert "403" in caplog.text
        assert "Forbidden" in caplog.text


class TestCsvSanitization:
    def test_formula_in_email_is_prefixed(self, tmp_path):
        """Email starting with '=' is prefixed to prevent spreadsheet formula injection."""
        results = [SendResult(email="=EVIL()", success=True, status_code=202, error="")]
        path = tmp_path / "report.csv"
        write_csv(results, path)
        raw = path.read_text(encoding="utf-8")
        data_row = raw.splitlines()[1]
        # The field must start with the tab prefix, not bare '='
        assert data_row.startswith("\t=EVIL()")
        assert "\t=EVIL()" in raw

    def test_formula_in_error_is_prefixed(self, tmp_path):
        """Error message starting with '+' is prefixed to prevent formula injection."""
        results = [SendResult(email="a@x.com", success=False, status_code=400, error="+CMD")]
        path = tmp_path / "report.csv"
        write_csv(results, path)
        raw = path.read_text(encoding="utf-8")
        assert "\t+CMD" in raw

    def test_normal_values_are_unchanged(self, tmp_path):
        """Non-formula values pass through without modification."""
        results = [SendResult(email="a@x.com", success=True, status_code=202, error="OK")]
        path = tmp_path / "report.csv"
        write_csv(results, path)
        loaded = read_csv(path)
        assert loaded[0].email == "a@x.com"
        assert loaded[0].error == "OK"


class TestReadCsvRoundTrip:
    def test_round_trip(self, tmp_path):
        results = [
            SendResult(email="a@x.com", success=True, status_code=202, error=""),
            SendResult(email="b@x.com", success=False, status_code=403, error="Forbidden"),
        ]
        path = tmp_path / "report.csv"
        write_csv(results, path)

        loaded = read_csv(path)
        assert len(loaded) == 2
        assert loaded[0].email == "a@x.com"
        assert loaded[0].success is True
        assert loaded[0].status_code == 202
        assert loaded[0].error == ""
        assert loaded[1].email == "b@x.com"
        assert loaded[1].success is False
        assert loaded[1].status_code == 403
        assert loaded[1].error == "Forbidden"

    def test_round_trip_of_guarded_values(self, tmp_path):
        """The tab written before a value that a spreadsheet would treat as
        a formula is taken off again, so resume matches +tag@ addresses."""
        results = [
            SendResult(email=f"{c}tag@example.com", success=False, status_code=400, error=f"{c}err")
            for c in ("=", "+", "-", "@", "\t", "\r")
        ] + [SendResult(email="\tx@example.com", success=True, status_code=202, error="\tplain")]
        path = tmp_path / "report.csv"
        write_csv(results, path)
        assert read_csv(path) == results

    def test_round_trip_of_unknown_outcome(self, tmp_path):
        results = [
            SendResult(email="a@x.com", success=False, error="no answer", unknown=True),
            SendResult(email="b@x.com", success=False, status_code=400, error="bad"),
        ]
        path = tmp_path / "report.csv"
        write_csv(results, path)
        assert read_csv(path) == results

    def test_reads_a_report_written_before_the_unknown_column(self, tmp_path):
        path = tmp_path / "report.csv"
        path.write_text("email,success,status_code,error\na@x.com,False,500,x\n", encoding="utf-8")
        assert read_csv(path) == [SendResult(email="a@x.com", success=False, status_code=500, error="x")]

    def test_none_status_code(self, tmp_path):
        results = [
            SendResult(email="c@x.com", success=True, status_code=None, error=""),
        ]
        path = tmp_path / "report.csv"
        write_csv(results, path)

        loaded = read_csv(path)
        assert loaded[0].status_code is None
        assert loaded[0].success is True


class TestUnknownOutcome:
    RESULTS = [
        SendResult(email="a@x.com", success=True, status_code=202),
        SendResult(email="b@x.com", success=False, status_code=400, error="bad"),
        SendResult(email="c@x.com", success=False, error="no answer", unknown=True),
    ]

    def test_summary_counts_unknown_separately(self):
        summary = summarize(self.RESULTS)
        assert (summary["total"], summary["sent"], summary["failed"], summary["unknown"]) == (3, 1, 1, 1)
        assert [d["email"] for d in summary["failed_details"]] == ["b@x.com"]
        assert [d["email"] for d in summary["unknown_details"]] == ["c@x.com"]

    def test_print_summary_says_it_may_have_been_delivered(self, caplog):
        with caplog.at_level(logging.INFO):
            print_summary(self.RESULTS)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Unknown: 1" in m for m in messages)
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("c@x.com" in m and "may have been delivered" in m for m in warnings)
        assert not any("c@x.com" in m and m.startswith("Failed") for m in warnings)
