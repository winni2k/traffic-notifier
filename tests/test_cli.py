from datetime import datetime
from unittest.mock import patch

from traffic_notifier import cli
from traffic_notifier.check import DelayedDeparture, Report

CLEAN_REPORT = Report(checked_at=datetime(2026, 9, 11, 15, 0), departures_checked=12)

AFFECTED_REPORT = Report(
    checked_at=datetime(2026, 9, 11, 15, 0),
    departures_checked=12,
    delays=[
        DelayedDeparture(
            station="Sundbyberg",
            destination="Bålsta",
            scheduled=datetime(2026, 9, 11, 15, 0),
            expected=datetime(2026, 9, 11, 15, 6),
            delay_minutes=6,
        )
    ],
)


def test_clean_segment_exits_zero_and_posts_to_slack(monkeypatch):
    monkeypatch.setenv(cli.WEBHOOK_ENV_VAR, "https://hooks.slack.com/services/x")
    with patch.object(cli, "build_report", return_value=CLEAN_REPORT):
        with patch.object(cli.slack, "post") as post:
            assert cli.main([]) == cli.EXIT_CLEAN
    post.assert_called_once()


def test_affected_segment_exits_one_and_posts_to_slack(monkeypatch):
    monkeypatch.setenv(cli.WEBHOOK_ENV_VAR, "https://hooks.slack.com/services/x")
    with patch.object(cli, "build_report", return_value=AFFECTED_REPORT):
        with patch.object(cli.slack, "post") as post:
            assert cli.main([]) == cli.EXIT_AFFECTED
    posted_text = post.call_args[0][1]
    assert "Bålsta" in posted_text


def test_missing_webhook_is_an_error_not_a_silent_success(monkeypatch):
    monkeypatch.delenv(cli.WEBHOOK_ENV_VAR, raising=False)
    with patch.object(cli, "build_report", return_value=CLEAN_REPORT):
        assert cli.main([]) == cli.EXIT_ERROR


def test_no_slack_flag_skips_delivery_and_keeps_status_exit_code(monkeypatch):
    monkeypatch.delenv(cli.WEBHOOK_ENV_VAR, raising=False)
    with patch.object(cli, "build_report", return_value=AFFECTED_REPORT):
        with patch.object(cli.slack, "post") as post:
            assert cli.main(["--no-slack"]) == cli.EXIT_AFFECTED
    post.assert_not_called()


def test_slack_failure_is_reported_as_an_error(monkeypatch):
    monkeypatch.setenv(cli.WEBHOOK_ENV_VAR, "https://hooks.slack.com/services/x")
    with patch.object(cli, "build_report", return_value=CLEAN_REPORT):
        with patch.object(cli.slack, "post", side_effect=cli.slack.SlackDeliveryError("boom")):
            assert cli.main([]) == cli.EXIT_ERROR


def test_sl_api_failure_is_reported_as_an_error(monkeypatch):
    monkeypatch.setenv(cli.WEBHOOK_ENV_VAR, "https://hooks.slack.com/services/x")
    with patch.object(cli, "build_report", side_effect=OSError("SL API down")):
        assert cli.main([]) == cli.EXIT_ERROR
