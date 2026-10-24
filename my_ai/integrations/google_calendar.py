
import os
import json
from typing import Dict, List, Optional, Any
import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

class GoogleCalendarIntegration:
    """Google Calendar API integration for calendar operations"""

    SCOPES = ['https://www.googleapis.com/auth/calendar']

    def __init__(self):
        self.credentials = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Handle Google OAuth authentication"""
        creds_file = "credentials.json"
        token_file = "token.json"

        if os.path.exists(token_file):
            self.credentials = Credentials.from_authorized_user_file(token_file, self.SCOPES)

        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                self.credentials.refresh(requests.Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_file, self.SCOPES)
                self.credentials = flow.run_local_server(port=0)

            with open(token_file, 'w') as token:
                token.write(self.credentials.to_json())

        self.service = build('calendar', 'v3', credentials=self.credentials)

    def get_events(self, calendar_id: str = 'primary', 
                  time_min: Optional[datetime] = None,
                  time_max: Optional[datetime] = None,
                  max_results: int = 10) -> List[Dict]:
        """Get events from calendar"""
        if not time_min:
            time_min = datetime.utcnow()
        if not time_max:
            time_max = time_min + timedelta(days=7)

        events_result = self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + 'Z',
            timeMax=time_max.isoformat() + 'Z',
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        return events_result.get('items', [])

    def create_event(self, summary: str, start_time: datetime, end_time: datetime,
                    description: str = "", location: str = "",
                    attendees: Optional[List[str]] = None,
                    calendar_id: str = 'primary') -> Dict:
        """Create a new calendar event"""
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': [{'email': email} for email in (attendees or [])],
        }

        created_event = self.service.events().insert(
            calendar=calendar_id, body=event).execute()
        return created_event

    def update_event(self, event_id: str, summary: str = None,
                    start_time: datetime = None, end_time: datetime = None,
                    description: str = None, calendar_id: str = 'primary') -> Dict:
        """Update an existing calendar event"""
        # First get the current event
        current_event = self.service.events().get(
            calendarId=calendar_id, eventId=event_id).execute()

        # Update fields if provided
        if summary is not None:
            current_event['summary'] = summary
        if start_time is not None:
            current_event['start']['dateTime'] = start_time.isoformat()
        if end_time is not None:
            current_event['end']['dateTime'] = end_time.isoformat()
        if description is not None:
            current_event['description'] = description

        updated_event = self.service.events().update(
            calendarId=calendar_id, eventId=event_id, body=current_event).execute()
        return updated_event

    def delete_event(self, event_id: str, calendar_id: str = 'primary') -> bool:
        """Delete a calendar event"""
        try:
            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id).execute()
            return True
        except HttpError:
            return False

    def find_free_time(self, calendar_id: str = 'primary', 
                      duration_hours: float = 1.0,
                      search_start: Optional[datetime] = None,
                      search_end: Optional[datetime] = None) -> Optional[datetime]:
        """Find available time slots in calendar"""
        if not search_start:
            search_start = datetime.utcnow()
        if not search_end:
            search_end = search_start + timedelta(days=7)

        # Get existing events
        events = self.get_events(
            calendar_id=calendar_id,
            time_min=search_start,
            time_max=search_end,
            max_results=100
        )

        # Create busy intervals
        busy_intervals = []
        for event in events:
            start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
            busy_intervals.append((start, end))

        # Sort busy intervals by start time
        busy_intervals.sort(key=lambda x: x[0])

        # Find gaps between busy intervals
        current_time = search_start
        for start, end in busy_intervals:
            if current_time + timedelta(hours=duration_hours) <= start:
                return current_time
            current_time = max(current_time, end)

        # Check after last event
        if current_time + timedelta(hours=duration_hours) <= search_end:
            return current_time

        return None
