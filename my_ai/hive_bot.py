"""Read-only client for the authenticated Hive bot status bridge."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


MAX_STATUS_BYTES = 64 * 1024
ALLOWED_TOP_LEVEL = {
    "schema_version", "generated_at", "age_seconds", "dry_run",
    "base_symbol", "last_cycle", "pairs",
}


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirect target.
        return None


def fetch_hive_bot_status() -> dict:
    """Fetch one fresh read-only status snapshot; never follow redirects."""
    url = os.getenv("HIVE_BOT_STATUS_URL", "").strip()
    token = os.getenv("HIVE_BOT_STATUS_TOKEN", "")
    if not url or not token:
        raise RuntimeError(
            "Set HIVE_BOT_STATUS_URL and HIVE_BOT_STATUS_TOKEN to connect the Hive bot."
        )

    parsed = urllib.parse.urlsplit(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost", "127.0.0.1", "::1",
    }
    if (
        (parsed.scheme != "https" and not local_http)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/ai/v1/status"
    ):
        raise RuntimeError("HIVE_BOT_STATUS_URL must be an HTTPS /ai/v1/status URL.")

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": "PocketAI-HiveStatus/1",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_RejectRedirects())
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(MAX_STATUS_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("The Hive status token was rejected.") from None
        if exc.code == 503:
            raise RuntimeError("The Hive bot has no fresh status snapshot yet.") from None
        raise RuntimeError("The Hive status service returned HTTP %d." % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("The Hive status service could not be reached.") from None

    if len(body) > MAX_STATUS_BYTES:
        raise RuntimeError("The Hive status response was too large.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError("The Hive status service returned invalid JSON.") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("The Hive status response used an unsupported schema.")

    # Keep the client-side contract narrow even if the server adds new fields.
    result = {key: payload[key] for key in ALLOWED_TOP_LEVEL if key in payload}
    if not isinstance(result.get("pairs"), list):
        raise RuntimeError("The Hive status response is incomplete.")
    return result
