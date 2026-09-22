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

The production Actions worker refreshes and commits sources every 300 seconds
for five hours, then dispatches a successor. Scheduled runs at :02, :07, ... :57
UTC are a recovery trigger. Production workers cannot overlap; PR checks use a
separate concurrency group. To stop the automation, disable the workflow and
cancel its running/pending runs in Actions.

The hosted dashboard checks the public GitHub raw data every 60 seconds and
when a hidden tab becomes visible. It does not wait for a Pages build for each
data commit. Pages still publishes changes to the dashboard code. Local copies
read their local data files.

The header shows the actual completed source-check time and warns after ten
minutes without a refresh. Every tab displays quote timestamps and stale status;
individual indicative/stale fields remain labelled. Source delays, market closures,
GitHub runner handoffs and outages can still delay quotes; five minutes is a
refresh target, not a real-time market-data guarantee. The worker uses standard
GitHub-hosted runners in this public repository. Review Actions billing before
making the repository private.

Checks: `python -m unittest discover -s tests -v` and `node tests/frontend.cjs`.

Free-source additions: Shenzhen Component (399001.SZ) uses Eastmoney when its
identity/scale-validated quote is newer and under 30 minutes old. It is labelled
indicative. TSM remains the US-listed ADR: its Yahoo market cap is corroborated
against Nasdaq with matching regular-session date/price and 0.01% cap tolerance.
Nasdaq supplies no separate cap timestamp. Failures preserve existing fallbacks;
per-run artifacts record free-source errors. Public endpoint availability is not
a guarantee of real-time data. Market-cap cells retain their numeric formatting.
