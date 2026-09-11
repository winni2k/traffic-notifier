from unittest.mock import patch

from traffic_notifier.check import (
    DELAY_THRESHOLD_MINUTES,
    STOCKHOLM,
    Report,
    analyze_departures,
    analyze_network_deviations,
    build_report,
    format_report,
)


def _departure(
    scheduled="2026-09-11T17:26:00",
    expected="2026-09-11T17:26:00",
    state="EXPECTED",
    destination="Bålsta",
    deviations=None,
):
    return {
        "destination": destination,
        "state": state,
        "scheduled": scheduled,
        "expected": expected,
        "deviations": deviations or [],
    }


def test_on_time_departure_is_not_a_delay():
    delays, cancellations, deviations = analyze_departures([_departure()], "Sundbyberg")
    assert delays == []
    assert cancellations == []
    assert deviations == []


def test_departure_below_threshold_is_not_a_delay():
    departure = _departure(scheduled="2026-09-11T17:26:00", expected="2026-09-11T17:28:00")
    delays, _, _ = analyze_departures([departure], "Sundbyberg")
    assert delays == []


def test_departure_at_or_above_threshold_is_a_delay():
    minutes_late = DELAY_THRESHOLD_MINUTES
    departure = _departure(scheduled="2026-09-11T17:26:00", expected=f"2026-09-11T17:{26 + minutes_late:02d}:00")
    delays, _, _ = analyze_departures([departure], "Sundbyberg")
    assert len(delays) == 1
    assert delays[0].delay_minutes == minutes_late
    assert delays[0].station == "Sundbyberg"


def test_cancelled_departure_is_reported_and_not_double_counted_as_delay():
    departure = _departure(state="CANCELLED")
    delays, cancellations, _ = analyze_departures([departure], "T-Centralen")
    assert delays == []
    assert len(cancellations) == 1
    assert cancellations[0].station == "T-Centralen"


def test_informational_per_departure_deviation_is_ignored():
    departure = _departure(
        deviations=[{"importance_level": 2, "consequence": "INFORMATION", "message": "Elevator note"}]
    )
    _, _, deviations = analyze_departures([departure], "Sundbyberg")
    assert deviations == []


def test_non_informational_per_departure_deviation_is_notable():
    departure = _departure(
        deviations=[{"importance_level": 5, "consequence": "SEVERE", "message": "Signal fault near Sundbyberg"}]
    )
    _, _, deviations = analyze_departures([departure], "Sundbyberg")
    assert len(deviations) == 1
    assert "Signal fault" in deviations[0].header
    assert deviations[0].source == "departure@Sundbyberg"


def test_low_importance_network_deviation_is_ignored():
    raw = [{"priority": {"importance_level": 2}, "message_variants": [{"header": "Minor note", "language": "sv"}]}]
    assert analyze_network_deviations(raw) == []


def test_high_importance_network_deviation_is_notable():
    raw = [
        {
            "priority": {"importance_level": 7},
            "message_variants": [{"header": "Buss ersätter pendeltåg", "language": "sv"}],
        }
    ]
    notable = analyze_network_deviations(raw)
    assert len(notable) == 1
    assert notable[0].header == "Buss ersätter pendeltåg"
    assert notable[0].source == "network"


def test_report_is_timestamped_in_stockholm_not_host_time():
    """SL returns naive Stockholm timestamps and the job runs on a UTC host, so
    a host-local header time would contradict the departure times below it."""
    with patch("traffic_notifier.check.sl_client.get_departures", return_value={"departures": []}):
        with patch("traffic_notifier.check.sl_client.get_deviations", return_value=[]):
            report = build_report()
    assert report.checked_at.tzinfo is STOCKHOLM


def test_format_report_when_clean():
    report = Report(checked_at=__import__("datetime").datetime(2026, 9, 11, 15, 0), departures_checked=12)
    text = format_report(report)
    assert "✅" in text
    assert "No delays" in text


def test_format_report_when_affected_lists_each_item():
    from datetime import datetime

    from traffic_notifier.check import CancelledDeparture, DelayedDeparture, NotableDeviation

    report = Report(
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
        cancellations=[
            CancelledDeparture(station="T-Centralen", destination="Nynäshamn", scheduled=datetime(2026, 9, 11, 15, 10))
        ],
        deviations=[NotableDeviation(header="Buss ersätter pendeltåg", importance_level=7, source="network")],
    )
    text = format_report(report)
    assert "⚠️" in text
    assert "Bålsta" in text
    assert "CANCELLED" in text
    assert "Buss ersätter pendeltåg" in text
