
import os
import json
from typing import Dict, List, Optional, Any
import requests
from datetime import datetime, timedelta

class QuickBooksIntegration:
    """QuickBooks API integration for financial data and operations"""

    def __init__(self):
        self.base_url = "https://quickbooks.api.intuit.com/v3"
        self.access_token = os.getenv("QUICKBOOKS_ACCESS_TOKEN")
        self.realm_id = os.getenv("QUICKBOOKS_REALM_ID")
        self.api_key = os.getenv("QUICKBOOKS_API_KEY")
        self.api_secret = os.getenv("QUICKBOOKS_API_SECRET")

    def _make_request(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Dict:
        """Make authenticated request to QuickBooks API"""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        url = f"{self.base_url}/{endpoint}"

        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()

    def get_recent_transactions(self, days: int = 30) -> List[Dict]:
        """Get recent transactions from QuickBooks"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        query = f"""
            SELECT * FROM Transaction
            WHERE TxnDate >= '{start_date.strftime("%Y-%m-%d")}'
            AND TxnDate <= '{end_date.strftime("%Y-%m-%d")}'
            MAXRESULTS 1000
        """

        endpoint = f"/company/{self.realm_id}/query"
        data = {"query": query}

        result = self._make_request(endpoint, method="POST", data=data)
        return result.get("QueryResponse", {}).get("Transaction", [])

    def get_customer_list(self) -> List[Dict]:
        """Get list of all customers"""
        endpoint = f"/company/{self.realm_id}/customer"
        return self._make_request(endpoint).get("Customer", [])

    def get_account_balance(self, account_id: str) -> float:
        """Get balance for a specific account"""
        endpoint = f"/company/{self.realm_id}/account/{account_id}"
        result = self._make_request(endpoint)
        return float(result.get("Account", {}).get("CurrentBalance", 0))

    def create_invoice(self, customer_id: str, line_items: List[Dict], 
                      invoice_date: Optional[str] = None) -> Dict:
        """Create a new invoice"""
        if not invoice_date:
            invoice_date = datetime.now().strftime("%Y-%m-%d")

        invoice_data = {
            "TxnDate": invoice_date,
            "CustomerRef": {"value": customer_id},
            "Line": line_items
        }

        endpoint = f"/company/{self.realm_id}/invoice"
        return self._make_request(endpoint, method="POST", data=invoice_data)

    def get_financial_report(self, report_type: str = "ProfitAndLoss", 
                            start_date: str = None, end_date: str = None) -> Dict:
        """Generate financial reports"""
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        report_data = {
            "ReportType": report_type,
            "StartPeriod": start_date,
            "EndPeriod": end_date,
            "SummarizeColumnsBy": "Month",
            "CollapseColumns": false,
            "Filters": {
                "DateMacro": "ThisMonth"
            }
        }

        endpoint = f"/company/{self.realm_id}/reports/{report_type}"
        return self._make_request(endpoint, method="POST", data=report_data)
