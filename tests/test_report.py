from mail_merge.report import read_csv, write_csv
from mail_merge.sender import SendResult


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

    def test_none_status_code(self, tmp_path):
        results = [
            SendResult(email="c@x.com", success=True, status_code=None, error=""),
        ]
        path = tmp_path / "report.csv"
        write_csv(results, path)

        loaded = read_csv(path)
        assert loaded[0].status_code is None
        assert loaded[0].success is True
