"""Delay/disruption detection for Pendeltåg line 43 between Sundbyberg and
T-Centralen.

Line 43 is the Mälarbanan pendeltåg trunk (Bålsta/Kallhäll <-> Västerhaninge/
Nynäshamn), which is the only pendeltåg line serving both Sundbyberg and
T-Centralen. Site and line IDs below were looked up against the live SL
Transport API on 2026-09-11 and are stable identifiers (not schedule data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from traffic_notifier import sl_client

SITE_SUNDBYBERG = 9325
SITE_T_CENTRALEN = 9001
LINE_PENDELTAG = 43

STATIONS = {
    SITE_SUNDBYBERG: "Sundbyberg",
    SITE_T_CENTRALEN: "T-Centralen",
}

# A departure running this many minutes or more behind schedule counts as a delay.
DELAY_THRESHOLD_MINUTES = 3

# Per-departure deviations (bundled in the /departures response) carry a
# "consequence" field; this value is purely informational (e.g. "an elevator
# that was reported broken actually works") and is never surfaced.
IGNORED_CONSEQUENCES = {"INFORMATION"}

# The network-wide /deviations endpoint has no "consequence" field, only a
# priority.importance_level (roughly 1-7). Below this, treat as noise.
NOTABLE_IMPORTANCE_THRESHOLD = 4


@dataclass
class DelayedDeparture:
    station: str
    destination: str
    scheduled: datetime
    expected: datetime
    delay_minutes: float

    def describe(self) -> str:
        return (
            f"{self.station} -> {self.destination}: "
            f"{self.delay_minutes:.0f} min late "
            f"(scheduled {self.scheduled:%H:%M}, expected {self.expected:%H:%M})"
        )


@dataclass
class CancelledDeparture:
    station: str
    destination: str
    scheduled: datetime

    def describe(self) -> str:
        return f"{self.station} -> {self.destination}: CANCELLED (was {self.scheduled:%H:%M})"


@dataclass
class NotableDeviation:
    header: str
    importance_level: int
    source: str  # "departure" (per-departure, e.g. at Sundbyberg) or "network"

    def describe(self) -> str:
        return f"{self.header} (importance {self.importance_level}, source: {self.source})"


@dataclass
class Report:
    checked_at: datetime
    departures_checked: int
    delays: list[DelayedDeparture] = field(default_factory=list)
    cancellations: list[CancelledDeparture] = field(default_factory=list)
    deviations: list[NotableDeviation] = field(default_factory=list)

    @property
    def is_affected(self) -> bool:
        return bool(self.delays or self.cancellations or self.deviations)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def analyze_departures(
    departures: list[dict], station: str
) -> tuple[list[DelayedDeparture], list[CancelledDeparture], list[NotableDeviation]]:
    """Analyze one station's departure board: delays, cancellations, and any
    deviation messages bundled directly onto a departure."""
    delays: list[DelayedDeparture] = []
    cancellations: list[CancelledDeparture] = []
    deviations: list[NotableDeviation] = []

    for departure in departures:
        scheduled = _parse_time(departure["scheduled"])
        destination = departure.get("destination", "?")

        if departure.get("state") == "CANCELLED":
            cancellations.append(CancelledDeparture(station=station, destination=destination, scheduled=scheduled))
        else:
            expected = _parse_time(departure["expected"])
            delay_minutes = (expected - scheduled).total_seconds() / 60
            if delay_minutes >= DELAY_THRESHOLD_MINUTES:
                delays.append(
                    DelayedDeparture(
                        station=station,
                        destination=destination,
                        scheduled=scheduled,
                        expected=expected,
                        delay_minutes=delay_minutes,
                    )
                )

        for deviation in departure.get("deviations") or []:
            if deviation.get("consequence") in IGNORED_CONSEQUENCES:
                continue
            deviations.append(
                NotableDeviation(
                    header=deviation.get("message", "(no message)"),
                    importance_level=deviation.get("importance_level", 0),
                    source=f"departure@{station}",
                )
            )

    return delays, cancellations, deviations


def analyze_network_deviations(deviations: list[dict]) -> list[NotableDeviation]:
    """Analyze results from the network-wide /deviations endpoint, scoped to
    our two stations. This schema has no "consequence" field, only a
    priority.importance_level."""
    notable: list[NotableDeviation] = []
    for deviation in deviations:
        importance_level = deviation.get("priority", {}).get("importance_level", 0)
        if importance_level < NOTABLE_IMPORTANCE_THRESHOLD:
            continue
        variants = deviation.get("message_variants") or [{}]
        variant = next((v for v in variants if v.get("language") == "sv"), variants[0])
        header = variant.get("header", "(no header)")
        notable.append(NotableDeviation(header=header, importance_level=importance_level, source="network"))
    return notable


def build_report() -> Report:
    """Fetch live data from SL and build a report for the Sundbyberg <-> T-Centralen segment."""
    now = datetime.now()

    sundbyberg = sl_client.get_departures(SITE_SUNDBYBERG, line=LINE_PENDELTAG)
    t_centralen = sl_client.get_departures(SITE_T_CENTRALEN, line=LINE_PENDELTAG)

    sundbyberg_departures = sundbyberg.get("departures", [])
    t_centralen_departures = t_centralen.get("departures", [])

    delays: list[DelayedDeparture] = []
    cancellations: list[CancelledDeparture] = []
    deviations: list[NotableDeviation] = []
    for departures, station in (
        (sundbyberg_departures, STATIONS[SITE_SUNDBYBERG]),
        (t_centralen_departures, STATIONS[SITE_T_CENTRALEN]),
    ):
        d, c, dev = analyze_departures(departures, station)
        delays.extend(d)
        cancellations.extend(c)
        deviations.extend(dev)

    network_deviations = sl_client.get_deviations(
        sites=[SITE_SUNDBYBERG, SITE_T_CENTRALEN],
        transport_mode="TRAIN",
        future=True,
    )
    deviations.extend(analyze_network_deviations(network_deviations))

    return Report(
        checked_at=now,
        departures_checked=len(sundbyberg_departures) + len(t_centralen_departures),
        delays=delays,
        cancellations=cancellations,
        deviations=deviations,
    )


def format_report(report: Report) -> str:
    lines = [f"SL Pendeltåg (line 43) Sundbyberg <-> T-Centralen — {report.checked_at:%Y-%m-%d %H:%M}"]

    if not report.is_affected:
        lines.append(f"✅ No delays or disruptions found ({report.departures_checked} departures checked).")
        return "\n".join(lines)

    lines.append("⚠️ Affected:")
    for delay in report.delays:
        lines.append(f"  - {delay.describe()}")
    for cancellation in report.cancellations:
        lines.append(f"  - {cancellation.describe()}")
    for deviation in report.deviations:
        lines.append(f"  - {deviation.describe()}")

    return "\n".join(lines)
