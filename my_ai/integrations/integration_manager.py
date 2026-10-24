
import os
from typing import Dict, Any, Optional
from .quickbooks import QuickBooksIntegration
from .google_calendar import GoogleCalendarIntegration

class IntegrationManager:
    """Central manager for all external integrations"""

    def __init__(self):
        self.quickbooks = None
        self.google_calendar = None
        self._initialize_integrations()

    def _initialize_integrations(self):
        """Initialize integrations if credentials are available"""
        # Initialize QuickBooks if credentials are available
        if all([
            os.getenv("QUICKBOOKS_ACCESS_TOKEN"),
            os.getenv("QUICKBOOKS_REALM_ID"),
            os.getenv("QUICKBOOKS_API_KEY"),
            os.getenv("QUICKBOOKS_API_SECRET")
        ]):
            self.quickbooks = QuickBooksIntegration()

        # Initialize Google Calendar if credentials are available
        if os.path.exists("credentials.json"):
            try:
                self.google_calendar = GoogleCalendarIntegration()
            except Exception as e:
                print(f"Failed to initialize Google Calendar: {e}")

    def get_financial_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get a financial summary from QuickBooks"""
        if not self.quickbooks:
            return {"error": "QuickBooks integration not configured"}

        try:
            transactions = self.quickbooks.get_recent_transactions(days)
            customers = self.quickbooks.get_customer_list()

            # Calculate basic metrics
            total_income = sum(
                float(txn.get("TotalAmount", 0)) 
                for txn in transactions 
                if txn.get("TxnType") == "Invoice"
            )

            return {
                "status": "success",
                "period_days": days,
                "total_transactions": len(transactions),
                "total_income": total_income,
                "customer_count": len(customers),
                "recent_transactions": transactions[:5]  # Return first 5 transactions
            }
        except Exception as e:
            return {"error": str(e)}

    def schedule_business_meeting(self, summary: str, start_time: str, 
                               duration_hours: float = 1.0,
                               attendees: Optional[list] = None) -> Dict[str, Any]:
        """Schedule a business meeting using Google Calendar"""
        if not self.google_calendar:
            return {"error": "Google Calendar integration not configured"}

        try:
            # Parse start time
            start_dt = datetime.fromisoformat(start_time)
            end_dt = start_dt + timedelta(hours=duration_hours)

            # Create the event
            event = self.google_calendar.create_event(
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                attendees=attendees or []
            )

            return {
                "status": "success",
                "event_id": event["id"],
                "html_link": event.get("htmlLink"),
                "summary": event["summary"],
                "start": event["start"]["dateTime"],
                "end": event["end"]["dateTime"]
            }
        except Exception as e:
            return {"error": str(e)}

    def find_meeting_time(self, duration_hours: float = 1.0,
                         search_days: int = 7) -> Dict[str, Any]:
        """Find available time for meetings"""
        if not self.google_calendar:
            return {"error": "Google Calendar integration not configured"}

        try:
            # Find free time
            available_time = self.google_calendar.find_free_time(
                duration_hours=duration_hours,
                search_end=datetime.now() + timedelta(days=search_days)
            )

            if available_time:
                return {
                    "status": "success",
                    "available_time": available_time.isoformat(),
                    "suggested_time_str": available_time.strftime("%Y-%m-%d %H:%M")
                }
            else:
                return {
                    "status": "no_slots_found",
                    "message": f"No available slots found for {duration_hours} hour meeting in next {search_days} days"
                }
        except Exception as e:
            return {"error": str(e)}

    def get_integration_status(self) -> Dict[str, Any]:
        """Get status of all integrations"""
        return {
            "quickbooks": {
                "enabled": self.quickbooks is not None,
                "configured": all([
                    os.getenv("QUICKBOOKS_ACCESS_TOKEN"),
                    os.getenv("QUICKBOOKS_REALM_ID"),
                    os.getenv("QUICKBOOKS_API_KEY"),
                    os.getenv("QUICKBOOKS_API_SECRET")
                ])
            },
            "google_calendar": {
                "enabled": self.google_calendar is not None,
                "configured": os.path.exists("credentials.json")
            }
        }
