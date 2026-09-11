"""Thin client for Trafiklab's SL Transport and SL Deviations APIs.

Both APIs are public and require no API key:
  https://www.trafiklab.se/api/our-apis/sl/transport/
  https://www.trafiklab.se/api/our-apis/sl/deviations/

Uses stdlib urllib only, so no dependency install is needed to run this
as a daily scheduled job.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

TRANSPORT_BASE = "https://transport.integration.sl.se/v1"
DEVIATIONS_BASE = "https://deviations.integration.sl.se/v1/messages"

USER_AGENT = "traffic-notifier/1.0 (+https://github.com/winni2k/traffic-notifier)"
TIMEOUT_SECONDS = 10


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def get_departures(site_id: int, *, line: int | None = None, transport: str = "TRAIN") -> dict:
    """Fetch upcoming departures for a site, optionally filtered to one line."""
    params = {"transport": transport}
    if line is not None:
        params["line"] = line
    url = f"{TRANSPORT_BASE}/sites/{site_id}/departures?{urllib.parse.urlencode(params)}"
    return _get_json(url)


def get_deviations(
    *,
    sites: list[int] | None = None,
    lines: list[int] | None = None,
    transport_mode: str | None = None,
    future: bool = False,
) -> list[dict]:
    """Fetch current (or current+future) deviation messages, optionally filtered."""
    params: list[tuple[str, str]] = []
    for site in sites or []:
        params.append(("site", str(site)))
    for line in lines or []:
        params.append(("line", str(line)))
    if transport_mode is not None:
        params.append(("transport_mode", transport_mode))
    if future:
        params.append(("future", "true"))
    url = f"{DEVIATIONS_BASE}?{urllib.parse.urlencode(params)}"
    return _get_json(url)
