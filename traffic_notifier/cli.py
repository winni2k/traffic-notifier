"""Entry point: `python -m traffic_notifier.cli`.

Prints a human-readable report to stdout and exits 1 if the Sundbyberg <->
T-Centralen pendeltåg segment is affected by delays, cancellations, or a
notable deviation, so this can also be used as a plain shell check.
"""

from __future__ import annotations

import sys

from traffic_notifier.check import build_report, format_report


def main() -> int:
    report = build_report()
    print(format_report(report))
    return 1 if report.is_affected else 0


if __name__ == "__main__":
    sys.exit(main())
