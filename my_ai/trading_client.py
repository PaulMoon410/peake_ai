"""Client for talking to Harold's trading bridge from a locally running bot.

The trading bot runs on the operator's machine; Harold runs on Render. This
module is the thin HTTP client the bot uses to ask Harold for guidance and to
report outcomes back, so the bot can be wired up with three calls.

    from my_ai.trading_client import TradingClient

    harold = TradingClient("https://your-app.onrender.com", api_key="...")
    advice = harold.advise({"market": "BTC/USDT", "timeframe": "1h"}, "RSI at 27, hold or exit?")
    harold.report_outcome("btc-rsi-bounce", "target hit", pnl=2.4, market="BTC/USDT", timeframe="1h")
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib import error as urlerror
from urllib import request as urlrequest


class TradingBridgeError(RuntimeError):
    """Raised when the remote Harold service refuses or fails a request."""


class TradingClient:
    """HTTP client for Harold's trading bridge endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"X-Trading-Key": self.api_key, "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urlrequest.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise TradingBridgeError(f"Harold returned HTTP {exc.code}: {detail}") from exc
        except urlerror.URLError as exc:
            raise TradingBridgeError(f"Could not reach Harold: {exc.reason}") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TradingBridgeError(f"Harold returned invalid JSON: {body[:200]}") from exc
        if not isinstance(parsed, dict):
            raise TradingBridgeError("Harold returned an unexpected payload.")
        if parsed.get("error"):
            raise TradingBridgeError(str(parsed["error"]))
        return parsed

    def advise(self, context: Optional[dict[str, Any]] = None, question: str = "") -> dict[str, Any]:
        """Ask Harold what the bot should do in the given market context."""
        return self._request("/api/trading/advise", {"context": context or {}, "question": question})

    def report_outcome(
        self,
        key: str,
        outcome: str,
        pnl: float = 0.0,
        market: str = "",
        timeframe: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Report a trade or strategy result so Harold can learn from it."""
        return self._request("/api/trading/feedback", {
            "key": key,
            "outcome": outcome,
            "pnl": pnl,
            "market": market,
            "timeframe": timeframe,
            "notes": notes,
        })

    def report_lesson(
        self,
        key: str,
        lesson: str,
        market: str = "",
        timeframe: str = "",
    ) -> dict[str, Any]:
        """Report a distilled lesson about a mechanism."""
        return self._request("/api/trading/feedback", {
            "key": key,
            "lesson": lesson,
            "market": market,
            "timeframe": timeframe,
        })

    def teach_mechanism(
        self,
        key: str,
        description: str,
        market: str = "",
        timeframe: str = "",
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Teach Harold a trading mechanism it does not know yet."""
        return self._request("/api/trading/mechanism", {
            "key": key,
            "description": description,
            "market": market,
            "timeframe": timeframe,
            "tags": list(tags or []),
        })

    def summary(self) -> dict[str, Any]:
        """Fetch what Harold has learned about trading so far."""
        return self._request("/api/trading/summary")
