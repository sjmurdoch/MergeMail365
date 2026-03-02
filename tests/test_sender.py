from unittest.mock import patch

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

    @responses.activate
    def test_throttled_false_on_clean_send(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert result.success
        assert result.throttled is False

    @responses.activate
    def test_throttled_true_after_429(self):
        responses.add(
            responses.POST, GRAPH_SEND_URL, status=429,
            headers={"Retry-After": "0"},
        )
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert result.success
        assert result.throttled is True


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

    @responses.activate
    def test_adaptive_delay_increases_on_throttle(self):
        # First send: 429 then 202 (throttled), second send: clean 202
        responses.add(
            responses.POST, GRAPH_SEND_URL, status=429,
            headers={"Retry-After": "0"},
        )
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)

        recipients = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        sleep_values = []
        original_sleep = __import__("time").sleep

        def mock_sleep(secs):
            sleep_values.append(secs)

        with patch("mail_merge.sender.time.sleep", side_effect=mock_sleep):
            results = send_all(
                token="fake",
                recipients=recipients,
                email_column="email",
                subject_template="Hi {{name}}",
                body_template="Hello {{name}}",
                delay=1.0,
            )

        assert results[0].success
        assert results[0].throttled is True
        assert results[1].success
        # After throttled send, delay should have doubled to 2.0
        assert sleep_values[-1] == 2.0
