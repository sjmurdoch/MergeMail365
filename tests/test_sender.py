import responses

from mail_merge.sender import GRAPH_SEND_URL, SendResult, send_all, send_one


class TestSendOne:
    @responses.activate
    def test_success(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert result.success
        assert result.status_code == 202

    @responses.activate
    def test_client_error_no_retry(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=400, body="Bad Request")
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert not result.success
        assert result.status_code == 400
        assert len(responses.calls) == 1  # no retry

    @responses.activate
    def test_server_error_retries(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=500, body="Server Error")
        responses.add(responses.POST, GRAPH_SEND_URL, status=500, body="Server Error")
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body", max_retries=3)
        assert result.success
        assert len(responses.calls) == 3

    @responses.activate
    def test_server_error_exhausts_retries(self):
        for _ in range(4):
            responses.add(responses.POST, GRAPH_SEND_URL, status=500, body="Server Error")
        result = send_one("fake-token", "test@example.com", "Subject", "Body", max_retries=3)
        assert not result.success
        assert result.status_code == 500

    @responses.activate
    def test_rate_limit_retries(self):
        responses.add(
            responses.POST, GRAPH_SEND_URL, status=429,
            headers={"Retry-After": "0"},
        )
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert result.success
        assert len(responses.calls) == 2


class TestSendAll:
    def test_dry_run(self):
        recipients = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        results = send_all(
            token=None,
            recipients=recipients,
            email_column="email",
            subject_template="Hi {{name}}",
            body_template="Hello {{name}}",
            dry_run=True,
        )
        assert len(results) == 2
        assert all(r.success for r in results)
        assert all(r.status_code is None for r in results)

    @responses.activate
    def test_send_all_with_failures(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=400, body="Bad")

        recipients = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        results = send_all(
            token="fake",
            recipients=recipients,
            email_column="email",
            subject_template="Hi {{name}}",
            body_template="Hello {{name}}",
        )
        assert results[0].success
        assert not results[1].success
