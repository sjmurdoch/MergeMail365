import json
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


class TestSendOneNewFeatures:
    @responses.activate
    def test_html_sets_content_type(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "<b>Body</b>", html=True)
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["body"]["contentType"] == "HTML"

    @responses.activate
    def test_plain_text_default(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        send_one("fake-token", "test@example.com", "Subject", "Body")
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["body"]["contentType"] == "Text"

    @responses.activate
    def test_save_to_sent_items_false(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body", save_to_sent_items=False)
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        assert payload["saveToSentItems"] is False

    @responses.activate
    def test_save_to_sent_items_true_omitted(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        send_one("fake-token", "test@example.com", "Subject", "Body", save_to_sent_items=True)
        payload = json.loads(responses.calls[0].request.body)
        assert "saveToSentItems" not in payload

    @responses.activate
    def test_attachments_in_payload(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        attachments = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "test.txt",
            "contentType": "text/plain",
            "contentBytes": "SGVsbG8=",
        }]
        result = send_one("fake-token", "test@example.com", "Subject", "Body", attachments=attachments)
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["attachments"] == attachments

    @responses.activate
    def test_reply_to_in_payload(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body", reply_to=["reply@example.com"])
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        reply_addrs = [r["emailAddress"]["address"] for r in payload["message"]["replyTo"]]
        assert reply_addrs == ["reply@example.com"]


class TestSendOneOptionalFields:
    @responses.activate
    def test_importance_included_in_payload(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body", importance="high")
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        assert payload["message"]["importance"] == "high"

    @responses.activate
    def test_cc_and_bcc_included_in_payload(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one(
            "fake-token", "test@example.com", "Subject", "Body",
            cc=["a@x.com", "b@x.com"], bcc=["c@x.com"],
        )
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        cc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["ccRecipients"]]
        assert cc_addrs == ["a@x.com", "b@x.com"]
        bcc_addrs = [r["emailAddress"]["address"] for r in payload["message"]["bccRecipients"]]
        assert bcc_addrs == ["c@x.com"]

    @responses.activate
    def test_optional_fields_absent_by_default(self):
        responses.add(responses.POST, GRAPH_SEND_URL, status=202)
        result = send_one("fake-token", "test@example.com", "Subject", "Body")
        assert result.success
        payload = json.loads(responses.calls[0].request.body)
        assert "importance" not in payload["message"]
        assert "ccRecipients" not in payload["message"]
        assert "bccRecipients" not in payload["message"]


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
