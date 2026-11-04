from unittest.mock import patch

from traffic_notifier.check import (
    DELAY_THRESHOLD_MINUTES,
    INBOUND,
    OUTBOUND,
    SEGMENTS,
    SITE_SUNDBYBERG,
    STOCKHOLM,
    Report,
    analyze_departures,
    analyze_network_deviations,
    build_report,
    format_report,
    in_direction,
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


def test_cancellation_signalled_only_by_journey_state_is_caught():
    """Observed live: SL leaves `state` as EXPECTED and marks the cancellation
    on journey.state, so a departure would otherwise look punctual."""
    departure = _departure(state="EXPECTED") | {"journey": {"state": "CANCELLED"}}
    _, cancellations, _ = analyze_departures([departure], "Sundbyberg")
    assert len(cancellations) == 1


def test_cancellation_signalled_only_by_deviation_consequence_is_caught():
    departure = _departure(state="EXPECTED", deviations=[{"consequence": "CANCELLED", "message": "Inställd"}])
    _, cancellations, _ = analyze_departures([departure], "Sundbyberg")
    assert len(cancellations) == 1


def test_cancellation_is_reported_once_not_also_as_a_bare_deviation():
    """The "Inställd" deviation carries no time or destination; the cancellation
    entry does, so repeating it would only add a context-free line."""
    departure = _departure(
        state="EXPECTED",
        destination="Kallhäll",
        deviations=[{"importance_level": 7, "consequence": "CANCELLED", "message": "Inställd"}],
    ) | {"journey": {"state": "CANCELLED"}}
    _, cancellations, deviations = analyze_departures([departure], "Sundbyberg")
    assert len(cancellations) == 1
    assert "Kallhäll" in cancellations[0].describe()
    assert deviations == []


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
            report = build_report(SEGMENTS["tcentralen"])
    assert report.checked_at.tzinfo is STOCKHOLM


def test_in_direction_keeps_everything_when_unfiltered():
    departures = [{"direction_code": INBOUND}, {"direction_code": OUTBOUND}]
    assert in_direction(departures, None) == departures


def test_in_direction_keeps_only_the_requested_direction():
    inbound = {"direction_code": INBOUND}
    outbound = {"direction_code": OUTBOUND}
    assert in_direction([inbound, outbound], INBOUND) == [inbound]


def test_odenplan_segment_checks_only_sundbyberg_inbound():
    """The morning commute is one-way: outbound departures at Sundbyberg would
    be noise, and the other end of the segment has no board of its own."""
    segment = SEGMENTS["odenplan"]
    assert [board.site_id for board in segment.boards] == [SITE_SUNDBYBERG]
    assert segment.boards[0].direction_code == INBOUND


def test_odenplan_segment_ignores_outbound_delays():
    board = {
        "departures": [
            _departure(
                scheduled="2026-11-04T07:50:00",
                expected="2026-11-04T08:05:00",
                destination="Kallhäll",
            )
            | {"direction_code": OUTBOUND},
        ]
    }
    with patch("traffic_notifier.check.sl_client.get_departures", return_value=board):
        with patch("traffic_notifier.check.sl_client.get_deviations", return_value=[]):
            report = build_report(SEGMENTS["odenplan"])
    assert report.departures_checked == 0
    assert not report.is_affected


def test_odenplan_segment_reports_inbound_delays():
    board = {
        "departures": [
            _departure(
                scheduled="2026-11-04T07:50:00",
                expected="2026-11-04T08:05:00",
                destination="Västerhaninge",
            )
            | {"direction_code": INBOUND},
        ]
    }
    with patch("traffic_notifier.check.sl_client.get_departures", return_value=board):
        with patch("traffic_notifier.check.sl_client.get_deviations", return_value=[]):
            report = build_report(SEGMENTS["odenplan"])
    assert report.departures_checked == 1
    assert [d.delay_minutes for d in report.delays] == [15]


def test_format_report_names_the_segment():
    from datetime import datetime

    report = Report(
        segment_label="Sundbyberg -> Odenplan",
        checked_at=datetime(2026, 11, 4, 7, 50),
        departures_checked=3,
    )
    assert "Sundbyberg -> Odenplan" in format_report(report)


def test_format_report_when_clean():
    report = Report(
        segment_label="Sundbyberg <-> T-Centralen",
        checked_at=__import__("datetime").datetime(2026, 9, 11, 15, 0),
        departures_checked=12,
    )
    text = format_report(report)
    assert "✅" in text
    assert "No delays" in text


def test_format_report_when_affected_lists_each_item():
    from datetime import datetime

    from traffic_notifier.check import CancelledDeparture, DelayedDeparture, NotableDeviation

    report = Report(
        segment_label="Sundbyberg <-> T-Centralen",
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
