import logging
import os
import re
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

# Load .env file if it exists (environment variables take precedence)
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Configuration: values must be provided via environment variables
CONFIG = {
    "SCHOOL_SLUG": os.getenv("MENU_SCHOOL_SLUG"),
    "CALENDAR_ID": os.getenv("MENU_CALENDAR_ID"),
    "MAX_WEEKS": int(os.getenv("MENU_MAX_WEEKS", 52)),
    "MIN_COMMA_THRESHOLD": int(os.getenv("MENU_MIN_COMMAS", 2)),
    "NO_MENU_DESCRIPTIONS": set(
        phrase.strip()
        for phrase in os.getenv("MENU_NO_DATA_PHRASES", "").split(",")
        if phrase.strip()
    ),
    "MENU_TYPES": [
        t.strip()
        for t in os.getenv("MENU_TYPES", "").split(",")
        if t.strip()
    ],
    "MENU_TITLES": {},
}

# Build dynamic menu titles from environment
for menu_type in CONFIG["MENU_TYPES"]:
    title_key = f"MENU_TITLE_{menu_type.upper()}"
    CONFIG["MENU_TITLES"][menu_type] = os.getenv(title_key) or menu_type.capitalize()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def normalize_description(value):
    normalized = (value or "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def fetch_available_weekday_days(start_date, menu_type, config):
    """Fetch available weekday menu days from the Nutrislice API."""
    collected_days = []
    seen_dates = set()

    for week_offset in range(config["MAX_WEEKS"]):
        week_start = start_date + timedelta(weeks=week_offset)
        menu_url = (
            f"https://gbaps.api.nutrislice.com/menu/api/weeks/school/{config['SCHOOL_SLUG']}/"
            f"menu-type/{menu_type}/{week_start.year}/{week_start.month:02d}/{week_start.day:02d}/?format=json"
        )

        response = requests.get(menu_url)
        if response.status_code == 404:
            break
        response.raise_for_status()

        data = response.json()
        days = data.get("days", [])
        if not days:
            break

        for day in days:
            day_date = day.get("date")
            if not day_date or day_date in seen_dates:
                continue
            try:
                if datetime.strptime(day_date, "%Y-%m-%d").weekday() < 5:
                    seen_dates.add(day_date)
                    collected_days.append(day)
            except ValueError:
                continue

    return sorted(collected_days, key=lambda day: day.get("date", ""))


def fetch_calendar_events(service, calendar_id, start_date, end_date):
    """Fetch all events in a date range."""
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=f"{start_date}T00:00:00Z",
            timeMax=f"{end_date}T23:59:59Z",
            singleEvents=True,
        )
        .execute()
    )
    return events_result.get("items", [])


def sync_menu_events(menu_type, title, config):
    """Sync a menu type to the calendar."""
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    weekday_days = fetch_available_weekday_days(today, menu_type, config)
    if not weekday_days:
        logger.info(f"No weekday {menu_type} menu days found for {today_str}")
        return

    logger.info(f"Today's date: {today_str}")
    logger.info(
        f"Found {len(weekday_days)} weekday {menu_type} days across available weeks"
    )

    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    service = build("calendar", "v3", credentials=creds)

    calendar_id = config["CALENDAR_ID"]
    start_date = weekday_days[0].get("date")
    end_date = weekday_days[-1].get("date")

    # Fetch and clean up stale events
    existing_events = fetch_calendar_events(service, calendar_id, start_date, end_date)
    for event in existing_events:
        if event.get("summary") != title:
            continue
        event_description = normalize_description(event.get("description"))
        event_id = event.get("id")
        if not event_id:
            continue

        # Delete if it's a no-menu event
        if event_description in config["NO_MENU_DESCRIPTIONS"]:
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info(
                f"Deleted empty {menu_type} event for {event.get('start', {}).get('date')}"
            )
            continue

        # Delete if it doesn't meet the minimum quality threshold
        if event_description.count(",") < config["MIN_COMMA_THRESHOLD"]:
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info(
                f"Deleted weak {menu_type} event for {event.get('start', {}).get('date')}"
            )

    # Re-fetch events after cleanup
    existing_events = fetch_calendar_events(service, calendar_id, start_date, end_date)
    existing_by_date = {}
    for event in existing_events:
        if event.get("summary") != title:
            continue
        event_description = normalize_description(event.get("description"))
        if event_description in config["NO_MENU_DESCRIPTIONS"]:
            continue
        event_date = event.get("start", {}).get("date")
        if event_date:
            existing_by_date[event_date] = event

    # Process new days
    for day in weekday_days:
        day_date = day.get("date")
        if not day_date:
            continue

        menu_items = day.get("menu_items", [])
        food_names = []
        for item in menu_items:
            if item.get("is_section_title"):
                continue
            food = item.get("food") or {}
            name = food.get("name") or item.get("text")
            if name and name not in food_names:
                food_names.append(name)

        if not food_names:
            logger.debug(f"Skipping calendar entry for {day_date}: no menu data")
            continue

        new_description = ", ".join(food_names)
        if new_description.count(",") < config["MIN_COMMA_THRESHOLD"]:
            logger.debug(
                f"Skipping calendar entry for {day_date}: too few menu items ({new_description!r})"
            )
            continue

        existing_event = existing_by_date.get(day_date)

        if existing_event:
            current_description = existing_event.get("description") or ""
            if current_description != new_description:
                existing_event["description"] = new_description
                service.events().update(
                    calendarId=calendar_id,
                    eventId=existing_event["id"],
                    body=existing_event,
                ).execute()
                logger.info(f"Updated {menu_type} event description for {day_date}")
            else:
                logger.debug(f"{title} event already exists for {day_date}")
            continue

        event_body = {
            "summary": title,
            "description": new_description,
            "start": {"date": day_date},
            "end": {"date": day_date},
        }
        service.events().insert(calendarId=calendar_id, body=event_body).execute()
        logger.info(f"Created {menu_type} event for {day_date}")


def sync_all_menus(config):
    """Sync all configured menu types to the calendar."""
    # Validate required configuration
    if not config.get("SCHOOL_SLUG"):
        raise ValueError("MENU_SCHOOL_SLUG environment variable is required")
    if not config.get("CALENDAR_ID"):
        raise ValueError("MENU_CALENDAR_ID environment variable is required")
    if not config.get("MENU_TYPES"):
        raise ValueError("MENU_TYPES environment variable is required (comma-separated)")
    if not config.get("NO_MENU_DESCRIPTIONS"):
        raise ValueError("MENU_NO_DATA_PHRASES environment variable is required (comma-separated)")

    for menu_type in config["MENU_TYPES"]:
        title = config["MENU_TITLES"].get(menu_type, menu_type.capitalize())
        logger.info(f"Syncing {menu_type}...")
        sync_menu_events(menu_type, title, config)


if __name__ == "__main__":
    sync_all_menus(CONFIG)