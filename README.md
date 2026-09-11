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
python3 -m traffic_notifier.cli              # check and post to Slack
python3 -m traffic_notifier.cli --no-slack   # check and print only
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Segment is clean |
| `1` | Segment is affected (delays, cancellations, or a notable deviation) |
| `2` | The check itself, or Slack delivery, failed |

## Slack delivery

The report is posted to `#sl-pendeltag` via a Slack **incoming webhook**. The
webhook URL is read from the `SLACK_WEBHOOK_URL` environment variable and is
never stored in this repo.

To set it up:

1. Create a Slack app at <https://api.slack.com/apps> (*From scratch*, pick
   your workspace).
2. Under **Incoming Webhooks**, toggle them on and *Add New Webhook to
   Workspace*, selecting `#sl-pendeltag` as the target channel.
3. Copy the generated `https://hooks.slack.com/services/...` URL.
4. Add it as an environment variable named `SLACK_WEBHOOK_URL` on the Claude
   Code environment that runs the daily Routine (Settings → Environments →
   environment variables), so every fired session inherits it.

A missing `SLACK_WEBHOOK_URL` is treated as an error (exit `2`) rather than a
silent no-op, so a misconfiguration can't masquerade as a clean day.

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
2. Runs `python3 -m traffic_notifier.cli`, which posts the report to Slack
   itself.

Delivery deliberately lives in the script rather than in the agent: Routines
created via the Claude Code MCP tooling can't be granted connector access in
this org, so a fired session has no Slack tools. Posting from the script also
makes the message deterministic and testable.

The cron expression is stored in UTC and does **not** auto-adjust for
daylight saving — it needs to be nudged by an hour at the spring/autumn
DST transitions. See the Routine's `cron_expression` (currently
`0 13 * * 1-5`, correct for CEST/UTC+2; becomes `0 14 * * 1-5` once Sweden
switches to CET/UTC+1 in late October).
