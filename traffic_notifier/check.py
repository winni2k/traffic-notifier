"""Delay/disruption detection for Pendeltåg line 43 on the segments between
Sundbyberg and the city.

Line 43 is the Mälarbanan pendeltåg trunk (Bålsta/Kallhäll <-> Västerhaninge/
Nynäshamn). It is the only pendeltåg line calling at Sundbyberg, and it runs
via Stockholm Odenplan and Stockholm City (T-Centralen) on Citybanan. Site and
line IDs below were looked up against the live SL Transport API and are stable
identifiers (not schedule data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from traffic_notifier import sl_client

# SL returns naive local timestamps, and this runs on a UTC host, so the
# report's own clock has to be pinned to Stockholm or the header time
# contradicts the departure times printed beneath it.
STOCKHOLM = ZoneInfo("Europe/Stockholm")

SITE_SUNDBYBERG = 9325
SITE_T_CENTRALEN = 9001
# "Stockholm Odenplan" is the commuter-rail station on Citybanan. Site 9117
# ("Odenplan") is the metro station and carries no pendeltåg departures.
SITE_ODENPLAN = 1079
LINE_PENDELTAG = 43

# direction_code as SL reports it on line 43. Inbound trains are the ones that
# carry you Sundbyberg -> Odenplan -> Stockholm City.
INBOUND = 1  # toward Nynäshamn/Västerhaninge, i.e. through the city
OUTBOUND = 2  # toward Bålsta/Kallhäll


@dataclass(frozen=True)
class Board:
    """One departure board to inspect, optionally limited to one direction."""

    site_id: int
    station: str
    direction_code: int | None = None  # None means both directions


@dataclass(frozen=True)
class Segment:
    label: str
    line: int
    boards: tuple[Board, ...]
    # Stations whose network-wide deviation messages are relevant to this segment.
    deviation_sites: tuple[int, ...]


SEGMENTS = {
    # Both directions matter for the afternoon check: you might be heading
    # either way.
    "tcentralen": Segment(
        label="Sundbyberg <-> T-Centralen",
        line=LINE_PENDELTAG,
        boards=(Board(SITE_SUNDBYBERG, "Sundbyberg"), Board(SITE_T_CENTRALEN, "T-Centralen")),
        deviation_sites=(SITE_SUNDBYBERG, SITE_T_CENTRALEN),
    ),
    # The morning commute is one-way, so outbound delays at Sundbyberg are
    # noise here and would bury the departures that actually matter.
    "odenplan": Segment(
        label="Sundbyberg -> Odenplan",
        line=LINE_PENDELTAG,
        boards=(Board(SITE_SUNDBYBERG, "Sundbyberg", direction_code=INBOUND),),
        deviation_sites=(SITE_SUNDBYBERG, SITE_ODENPLAN),
    ),
}

DEFAULT_SEGMENT = "tcentralen"

# A departure running this many minutes or more behind schedule counts as a delay.
DELAY_THRESHOLD_MINUTES = 3

# Per-departure deviations (bundled in the /departures response) carry a
# "consequence" field; this value is purely informational (e.g. "an elevator
# that was reported broken actually works") and is never surfaced.
IGNORED_CONSEQUENCES = {"INFORMATION"}

CANCELLED = "CANCELLED"

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
    segment_label: str
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


def is_cancelled(departure: dict) -> bool:
    """SL signals cancellation inconsistently: `state` is often still EXPECTED
    on a cancelled departure, while journey.state and a deviation with
    consequence CANCELLED carry the truth. Checking only `state` misses it and
    leaves the departure looking punctual."""
    if departure.get("state") == CANCELLED:
        return True
    if (departure.get("journey") or {}).get("state") == CANCELLED:
        return True
    return any((d.get("consequence") == CANCELLED) for d in departure.get("deviations") or [])


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
        cancelled = is_cancelled(departure)

        if cancelled:
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
            consequence = deviation.get("consequence")
            if consequence in IGNORED_CONSEQUENCES:
                continue
            # The cancellation entry already names the train and its time; the
            # deviation that announced it says only "Inställd".
            if cancelled and consequence == CANCELLED:
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


def in_direction(departures: list[dict], direction_code: int | None) -> list[dict]:
    if direction_code is None:
        return departures
    return [d for d in departures if d.get("direction_code") == direction_code]


def build_report(segment: Segment) -> Report:
    """Fetch live data from SL and build a report for one segment."""
    now = datetime.now(STOCKHOLM)

    delays: list[DelayedDeparture] = []
    cancellations: list[CancelledDeparture] = []
    deviations: list[NotableDeviation] = []
    departures_checked = 0

    for board in segment.boards:
        response = sl_client.get_departures(board.site_id, line=segment.line)
        departures = in_direction(response.get("departures", []), board.direction_code)
        departures_checked += len(departures)

        d, c, dev = analyze_departures(departures, board.station)
        delays.extend(d)
        cancellations.extend(c)
        deviations.extend(dev)

    network_deviations = sl_client.get_deviations(
        sites=list(segment.deviation_sites),
        transport_mode="TRAIN",
        future=True,
    )
    deviations.extend(analyze_network_deviations(network_deviations))

    return Report(
        segment_label=segment.label,
        checked_at=now,
        departures_checked=departures_checked,
        delays=delays,
        cancellations=cancellations,
        deviations=deviations,
    )


def format_report(report: Report) -> str:
    lines = [f"SL Pendeltåg (line 43) {report.segment_label} — {report.checked_at:%Y-%m-%d %H:%M}"]

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
