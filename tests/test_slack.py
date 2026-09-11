import json
import urllib.error
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from traffic_notifier import slack

WEBHOOK = "https://hooks.slack.com/services/T000/B000/xxx"


@contextmanager
def _fake_response(body: str):
    class _Response:
        def read(self):
            return body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    yield _Response()


def test_post_sends_json_payload_to_webhook():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["content_type"] = request.get_header("Content-type")
        return _fake_response("ok").__enter__()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        slack.post(WEBHOOK, "No delays")

    assert captured["url"] == WEBHOOK
    assert captured["body"] == {"text": "No delays"}
    assert captured["content_type"] == "application/json"


def test_post_raises_when_slack_rejects_the_message():
    def fake_urlopen(request, timeout=None):
        return _fake_response("invalid_payload").__enter__()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(slack.SlackDeliveryError, match="invalid_payload"):
            slack.post(WEBHOOK, "No delays")


def test_post_raises_when_slack_is_unreachable():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(slack.SlackDeliveryError, match="could not reach Slack"):
            slack.post(WEBHOOK, "No delays")
