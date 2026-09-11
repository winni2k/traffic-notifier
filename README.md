# traffic-notifier

Checks whether SL's Pendeltåg line 43 (the Mälarbanan trunk) is delayed or
disrupted between Sundbyberg and T-Centralen, and reports the result.

## How it works

`traffic_notifier/sl_client.py` is a small stdlib-only client for two public,
key-free Trafiklab APIs:

- [SL Transport API](https://www.trafiklab.se/api/our-apis/sl/transport/) —
  live departure boards (`/sites/{id}/departures`).
- [SL Deviations API](https://www.trafiklab.se/api/our-apis/sl/deviations/) —
  network-wide disruption messages (`/v1/messages`).

`traffic_notifier/check.py` fetches the departure boards for Sundbyberg
(site `9325`) and T-Centralen (site `9001`), both filtered to line `43`
(the only pendeltåg line serving both stations), and flags:

- any departure running `DELAY_THRESHOLD_MINUTES` (default 3) or more behind
  schedule,
- any cancelled departure,
- any non-informational deviation message attached to a departure,
- any network-wide deviation scoped to either station with
  `importance_level >= NOTABLE_IMPORTANCE_THRESHOLD` (default 4).

## Usage

```bash
python3 -m traffic_notifier.cli
```

Prints a human-readable report and exits `1` if the segment is affected,
`0` if it's clean.

## Tests

```bash
pip install -e '.[dev]'
python3 -m pytest
```

Tests use inline fixtures matching the real API response shapes (captured
against the live API on 2026-09-11) rather than live network calls.

## Daily schedule

This check runs automatically on weekdays at 15:00 Europe/Stockholm time via
a Claude Code Routine (scheduled trigger) that:

1. Pulls this repo.
2. Runs `python3 -m traffic_notifier.cli`.
3. Reports the result as an email notification.

The cron expression is stored in UTC and does **not** auto-adjust for
daylight saving — it needs to be nudged by an hour at the spring/autumn
DST transitions. See the Routine's `cron_expression` (currently
`0 13 * * 1-5`, correct for CEST/UTC+2; becomes `0 14 * * 1-5` once Sweden
switches to CET/UTC+1 in late October).
