"""Post a report to Slack via an incoming webhook.

The webhook URL is a secret and is read from the SLACK_WEBHOOK_URL
environment variable by the CLI — never hardcode it here. The target channel
is fixed at webhook-creation time in Slack, not chosen by this code.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 10
USER_AGENT = "traffic-notifier/1.0 (+https://github.com/winni2k/traffic-notifier)"


class SlackDeliveryError(RuntimeError):
    pass


def post(webhook_url: str, text: str) -> None:
    """Post `text` to Slack. Raises SlackDeliveryError if delivery fails."""
    payload = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8").strip()
    except urllib.error.URLError as exc:
        raise SlackDeliveryError(f"could not reach Slack: {exc}") from exc

    # A Slack incoming webhook answers with a literal "ok" on success.
    if body != "ok":
        raise SlackDeliveryError(f"Slack rejected the message: {body!r}")
