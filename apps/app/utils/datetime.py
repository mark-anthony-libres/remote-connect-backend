from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, available_timezones

if TYPE_CHECKING:
    from apps.app.modules.user.entities.user_entity import User

_NON_STANDARD_TIMEZONE_NAMES = {"localtime", "posixrules", "Factory"}

AVAILABLE_TIMEZONES = sorted(
    tz for tz in available_timezones() if tz not in _NON_STANDARD_TIMEZONE_NAMES
)

class DateTime:

    def __init__(self, user: "User" = None):
        effective_timezone = (user.timezone or user.okta_timezone) if user else None
        self.timezone = ZoneInfo(effective_timezone) if effective_timezone else None

    @property
    def name(self):
        return str(self.timezone) if self.timezone else None

    def now(self):
        return datetime.now(self.timezone)

    def from_utc(self, dt: datetime):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(self.timezone)

    def to_utc(self, dt: datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.timezone)
        return dt.astimezone(ZoneInfo("UTC"))

    def date_range(self, days: int):
        to_dt = self.now().date()
        from_dt = to_dt - timedelta(days=days)
        return from_dt, to_dt

    def day_window(self, days: int):
        tz = self.timezone or timezone.utc
        today = datetime.now(tz).date()
        start_date = today - timedelta(days=days - 1)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        return start_date, start, end

    @staticmethod
    def _convert_iso_string_to_utc(iso_string):
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).astimezone(timezone.utc)
