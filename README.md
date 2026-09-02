# Menu Sync for Google Calendar

A Python application that syncs school menu data from Nutrislice to Google Calendar. Fetches breakfast and lunch menu items and creates/updates calendar events with menu descriptions.

## Setup

### Prerequisites
- Python 3.7+
- Google Cloud OAuth credentials (`credentials.json`)
- A Google Calendar where you want to sync menu data

### Installation

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate  # Windows
   # or
   source .venv/bin/activate  # macOS/Linux
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `credentials.json` file with your Google Cloud OAuth credentials.

4. Generate a token:
   ```bash
   python generate_token.py
   ```
   This will open a browser window to authenticate with your Google account.

### Configuration

All configuration can be set via environment variables. See `.env.example` for all available options.

Key settings:
- `MENU_SCHOOL_SLUG`: School identifier in the Nutrislice API (default: `wilder`)
- `MENU_CALENDAR_ID`: Google Calendar ID to sync to
- `MENU_MAX_WEEKS`: Number of weeks to fetch (default: `52`)
- `MENU_MIN_COMMAS`: Minimum commas in menu description to import (default: `2`)
- `MENU_TYPES`: Meal types to sync, comma-separated (default: `breakfast,lunch`)

Example:
```bash
set MENU_SCHOOL_SLUG=myschool
set MENU_MAX_WEEKS=104
python getmenu.py
```

## Usage

### Sync menus
```bash
python getmenu.py
```

This will:
- Fetch available weekday menu data from Nutrislice
- Delete stale events that don't meet quality standards
- Update existing events if menu descriptions change
- Create new calendar events for new menu data

### Regenerate token
```bash
python generate_token.py
```

Use this if your OAuth token expires or needs to be refreshed.

## How it works

1. **Fetch**: Retrieves menu data from the Nutrislice API for each configured meal type.
2. **Filter**: Only imports weekday entries (Mon-Fri).
3. **Validate**: Skips entries with no menu items or insufficient content (fewer than 2 commas by default).
4. **Cleanup**: Deletes existing calendar events that are stale or don't meet quality thresholds.
5. **Sync**: Updates changed events and creates new ones.

### Event format

- **Title**: Meal type (e.g., "Breakfast", "Lunch")
- **Description**: Comma-separated list of menu items
- **Date**: Full-day event on the menu date

### No-menu handling

Events are skipped or deleted if they contain phrases like:
- "No menu data"
- "Professional Development"
- "Teacher Workday"
- "Spring Recess"

Customize via the `MENU_NO_DATA_PHRASES` environment variable.

## Logging

Output uses Python logging with INFO level by default. Messages include:
- Menu sync status
- Event creation, updates, and deletions
- Skipped entries with reasons

## Extensibility

To sync additional meal types (e.g., "snack", "dinner"):
1. Update `MENU_TYPES` environment variable
2. Add display title via `MENU_TITLE_<TYPE>` (e.g., `MENU_TITLE_SNACK=Snack`)

Example:
```bash
set MENU_TYPES=breakfast,lunch,snack
set MENU_TITLE_SNACK=Snack
python getmenu.py
```

## Files

- `getmenu.py`: Main sync application
- `generate_token.py`: OAuth token generator
- `credentials.json`: Google Cloud OAuth config (do not share)
- `token.json`: OAuth access token (do not share, auto-generated)
- `.env.example`: Configuration template
- `requirements.txt`: Python dependencies
