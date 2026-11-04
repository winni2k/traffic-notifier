# traffic-notifier

Checks whether SL's Pendeltåg line 43 (the Mälarbanan trunk) is delayed or
disrupted on the commute between Sundbyberg and the city, and posts the result
to Slack.

Two segments are defined:

| Segment | Route | Boards checked |
| --- | --- | --- |
| `tcentralen` (default) | Sundbyberg ↔ T-Centralen | Both stations, both directions |
| `odenplan` | Sundbyberg → Odenplan | Sundbyberg, inbound only |

`odenplan` is one-way on purpose: it backs the morning check, where a delay on
an outbound train to Bålsta is noise that would bury the departures that
matter. Note that Odenplan's commuter-rail station is site `1079`
("Stockholm Odenplan"); site `9117` ("Odenplan") is the metro station and
carries no pendeltåg departures.

## How it works

`traffic_notifier/sl_client.py` is a small stdlib-only client for two public,
key-free Trafiklab APIs:

- [SL Transport API](https://www.trafiklab.se/api/our-apis/sl/transport/) —
  live departure boards (`/sites/{id}/departures`).
- [SL Deviations API](https://www.trafiklab.se/api/our-apis/sl/deviations/) —
  network-wide disruption messages (`/v1/messages`).

`traffic_notifier/check.py` fetches the departure boards named by the chosen
segment, filtered to line `43`, and flags:

- any departure running `DELAY_THRESHOLD_MINUTES` (default 3) or more behind
  schedule,
- any cancelled departure,
- any non-informational deviation message attached to a departure,
- any network-wide deviation scoped to either of the segment's stations with
  `importance_level >= NOTABLE_IMPORTANCE_THRESHOLD` (default 4).

### Detecting cancellations

SL signals a cancellation inconsistently, so `is_cancelled()` checks three
places. Observed live on 2026-11-04: a cancelled departure had
`state: "EXPECTED"` with the cancellation recorded only on `journey.state` and
on a deviation with `consequence: "CANCELLED"` whose message was the bare word
`Inställd`. Testing `state` alone both missed the cancellation and left the
departure looking punctual, so the only hint was a context-free deviation line.
A departure counts as cancelled if any of `state`, `journey.state`, or a
deviation's `consequence` says `CANCELLED`; the cancellation entry then
replaces that bare deviation line, since it carries the time and destination.

## Usage

```bash
python3 -m traffic_notifier.cli                       # tcentralen, post to Slack
python3 -m traffic_notifier.cli --segment odenplan    # morning segment
python3 -m traffic_notifier.cli --no-slack            # check and print only
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Segment is clean |
| `1` | Segment is affected (delays, cancellations, or a notable deviation) |
| `2` | The check itself, or Slack delivery, failed, or the segment could not be verified |

### An empty board is never "clean"

If SL returns no departures at all, the report says the segment could **not**
be checked and exits `2`. SL has been seen answering `HTTP 200` with an empty
`departures` array instead of a `429` under rate limiting, and at the times
these checks run line 43 always has departures. A false all-clear is the worst
failure mode here — you read "no delays" and walk to a station with no trains
— so an unverifiable segment takes the same path as any other failure.

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
against the live API on 2026-09-11 and 2026-11-04) rather than live network
calls.

In the cloud environment, `pip` and `python3` can point at different
interpreters (`pip` → 3.13, `python3` → 3.11). If `python3 -m pytest` reports
no module named pytest, run `python3.13 -m pytest`. Only the dev tooling is
affected — the package itself is stdlib-only and runs on either.

## Daily schedule

Two Claude Code Routines (scheduled triggers) run on weekdays. Each checks out
`main`, runs the CLI, and the script posts to Slack itself.

| Stockholm | Command | Cron (UTC, winter) |
| --- | --- | --- |
| 07:50 | `python3 -m traffic_notifier.cli --segment odenplan` | `50 6 * * 1-5` |
| 15:00 | `python3 -m traffic_notifier.cli` | `0 14 * * 1-5` |

Delivery deliberately lives in the script rather than in the agent: Routines
created via the Claude Code MCP tooling can't be granted connector access in
this org, so a fired session has no Slack tools. Posting from the script also
makes the message deterministic and testable.

### Daylight saving

Cron expressions are stored in **UTC** and do **not** auto-adjust, so both
need nudging by an hour at each DST transition. The table above holds for
CET/UTC+1 (winter). Under CEST/UTC+2 (summer) they become `50 5 * * 1-5` and
`0 13 * * 1-5`.

### Rate limits

The Trafiklab APIs ask for roughly one request a minute. Each run makes three
calls, so two runs a day is far inside that — but running the CLI repeatedly
in a tight loop will earn an `HTTP 429`, which surfaces as exit `2`. There is
no built-in backoff; the Routine prompt handles a transient failure by
retrying once.
