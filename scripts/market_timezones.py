"""Regional display zones; exchange zones still determine trading sessions."""
from datetime import datetime
from zoneinfo import ZoneInfo

REGION_TIMEZONES = {
    'india': 'Asia/Kolkata',
    'us': 'America/New_York',
    'asia': 'Asia/Singapore',
}


def apply_region_timezones(payload):
    """Annotate snapshots without changing source timestamps or freshness."""
    payload['region_timezones'] = dict(REGION_TIMEZONES)
    payload['refresh_interval_seconds'] = 300
    for region, rows in payload['regions'].items():
        if region not in REGION_TIMEZONES:
            continue
        zone = REGION_TIMEZONES[region]
        for row in rows:
            row['display_timezone'] = zone
            row['source_timestamp_local'] = None
            value = row.get('source_timestamp')
            if value:
                try:
                    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if instant.tzinfo is not None:
                        row['source_timestamp_local'] = instant.astimezone(ZoneInfo(zone)).isoformat()
                except (ValueError, TypeError):
                    pass
    return payload
