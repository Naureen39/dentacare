"""iCalendar (.ics) files for appointments."""

from datetime import UTC, datetime, timedelta

from icalendar import Alarm, Calendar, Event, vText

from app.core.config import Settings

PRODID = "-//Meridian Dental Care//Appointments//EN"


def build_ics(
    *,
    appointment_id: object,
    start: datetime,
    end: datetime,
    service_name: str,
    dentist_name: str,
    settings: Settings,
    now: datetime | None = None,
) -> bytes:
    """A single event calendar for the appointment. Times are UTC so every client agrees."""
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")

    event = Event()
    event.add("uid", f"{appointment_id}@meridian.test")
    event.add("dtstamp", (now or datetime.now(UTC)).astimezone(UTC))
    event.add("dtstart", start.astimezone(UTC))
    event.add("dtend", end.astimezone(UTC))
    event.add("summary", f"{service_name} at {settings.clinic_name}")
    event.add(
        "description",
        f"{service_name} with {dentist_name}. To change or cancel, call {settings.clinic_phone}.",
    )
    event["location"] = vText(f"{settings.clinic_name}, {settings.clinic_address}")
    event.add("status", "CONFIRMED")

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Appointment at {settings.clinic_name}")
    alarm.add("trigger", timedelta(hours=-2))
    event.add_component(alarm)

    calendar.add_component(event)
    return bytes(calendar.to_ical())
