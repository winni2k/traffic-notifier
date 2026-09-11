"""Entry point: `python3 -m traffic_notifier.cli`.

Checks the Sundbyberg <-> T-Centralen pendeltåg segment, prints the report,
and posts it to Slack via the webhook in SLACK_WEBHOOK_URL.

Exit codes:
    0  segment is clean
    1  segment is affected (delays, cancellations, or a notable deviation)
    2  the check itself, or Slack delivery, failed
"""

from __future__ import annotations

import argparse
import os
import sys

from traffic_notifier import slack
from traffic_notifier.check import build_report, format_report

EXIT_CLEAN = 0
EXIT_AFFECTED = 1
EXIT_ERROR = 2

WEBHOOK_ENV_VAR = "SLACK_WEBHOOK_URL"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="print the report only, don't post it to Slack (for local runs)",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report()
    except Exception as exc:  # noqa: BLE001 - the daily job needs the reason, whatever it is
        print(f"SL check failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    text = format_report(report)
    print(text)

    if not args.no_slack:
        webhook_url = os.environ.get(WEBHOOK_ENV_VAR)
        if not webhook_url:
            print(f"{WEBHOOK_ENV_VAR} is not set, so the report was not posted to Slack.", file=sys.stderr)
            return EXIT_ERROR
        try:
            slack.post(webhook_url, text)
        except slack.SlackDeliveryError as exc:
            print(f"Slack delivery failed: {exc}", file=sys.stderr)
            return EXIT_ERROR

    return EXIT_AFFECTED if report.is_affected else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
