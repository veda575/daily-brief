# Daily Brief market times

Stock analysis uses these regional display zones:

| Tab | IANA zone | Display |
| --- | --- | --- |
| India | Asia/Kolkata | IST (UTC+05:30) |
| United States | America/New_York | EDT or EST, automatically for the quote date |
| Asia / Global Chips | Asia/Singapore | GMT+8 (UTC+08:00) |

The backend adds `display_timezone` and an offset-aware `source_timestamp_local`
to each regional stock. Original UTC source timestamps and exchange time zones
remain unchanged for validation and trading-session calculations. GMT+8 is a
common display zone for the Asia tab: Samsung trades in Korea (UTC+9), while
the BABA and TSM symbols are US-listed ADRs; their sessions retain their actual
exchange zones. Failed fetches retain their original quote time and stale status.

The existing GitHub Actions workflow fetches data every five minutes at
:02, :07, ..., :57 UTC, around the clock, so no DST-dependent cron conversion
is needed. The browser fetches the published snapshot every 300 seconds.
GitHub scheduled runs and Pages publication can be delayed; this is not a
guaranteed real-time feed. For a strict five-minute deadline, use an external
scheduler and a continuously available backend instead of Actions/Pages.

Checks: `python -m unittest discover -s tests -v` and `node tests/frontend.cjs`.
