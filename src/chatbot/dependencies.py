import os
import hmac
import base64
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import Header, HTTPException, status, Request, WebSocket
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_ALLOWLIST_PATHS = {
    "/",  # optional
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/login",
    "/api/v1/auth/me",
}


def get_api_keys():
    keys = os.getenv("API_KEYS", "")
    return [k.strip() for k in keys.split(",") if k.strip()]


def _get_admin_secret() -> str:
    secret = (os.getenv("ADMIN_AUTH_SECRET") or "").strip()
    if secret:
        return secret
    api_keys = get_api_keys()
    if api_keys:
        return api_keys[0]
    return "dev-admin-auth-secret"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _token_ttl_minutes() -> int:
    raw = (os.getenv("ADMIN_AUTH_TOKEN_TTL_MINUTES") or "").strip()
    try:
        ttl = int(raw)
        return ttl if ttl > 0 else 480
    except (TypeError, ValueError):
        return 480


def _session_secret() -> str:
    return (os.getenv("SESSION_AUTH_SECRET") or _get_admin_secret()).strip()


def create_session_capability(session_id: str, user_id: str, ttl_seconds: int = 2592000) -> str:
    payload = {"sid": str(session_id), "uid": str(user_id), "exp": int(time.time()) + ttl_seconds}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_session_secret().encode(), raw, hashlib.sha256).digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(sig)}"


def verify_session_capability(token: str, session_id: str, user_id: str | None = None) -> bool:
    try:
        parts = (token or "").split(".", 1)
        if len(parts) != 2:
            return False
        raw = _b64url_decode(parts[0])
        sig = _b64url_decode(parts[1])
        expected = hmac.new(_session_secret().encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(raw.decode())
        return int(payload.get("exp", 0)) > int(time.time()) and payload.get("sid") == str(session_id) and (user_id is None or payload.get("uid") == str(user_id))
    except Exception:
        return False


def require_session_owner(request: Request, session_id: str, session: dict | None = None) -> dict:
    session = session or {}
    token = request.cookies.get("om_chat_session") or request.headers.get("X-SESSION-TOKEN")
    if not verify_session_capability(token or "", session_id, session.get("user_id")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session access denied")
    return session


def session_user_id_from_request(request: Request) -> str:
    token = request.cookies.get("om_chat_session") or request.headers.get("X-SESSION-TOKEN")
    try:
        raw, sig = (token or "").split(".", 1)
        payload_bytes = _b64url_decode(raw)
        expected = hmac.new(_session_secret().encode(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            raise ValueError
        payload = json.loads(payload_bytes.decode())
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError
        return str(payload["uid"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated session required") from exc


def session_uid_from_token(token: str | None) -> str | None:
    """Best-effort uid extraction from a signed session capability token.

    Returns None for missing/invalid/expired tokens instead of raising, so
    callers can detect owner changes without treating anonymous clients as
    errors.
    """
    try:
        raw, sig = (token or "").split(".", 1)
        payload_bytes = _b64url_decode(raw)
        expected = hmac.new(_session_secret().encode(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            return None
        payload = json.loads(payload_bytes.decode())
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return str(payload.get("uid"))
    except Exception:
        return None


def authenticate_admin_credentials(email: str, password: str) -> bool:
    configured_email = (os.getenv("ADMIN_AUTH_EMAIL") or "omega@oldmutual.co.ug").strip().lower()
    configured_password = (os.getenv("ADMIN_AUTH_PASSWORD") or "omega").strip()
    candidate_email = (email or "").strip().lower()
    candidate_password = (password or "").strip()
    return hmac.compare_digest(candidate_email, configured_email) and hmac.compare_digest(candidate_password, configured_password)


def create_admin_access_token(email: str) -> dict:
    exp = int(time.time()) + (_token_ttl_minutes() * 60)
    payload = {
        "sub": (email or "").strip().lower(),
        "exp": exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_get_admin_secret().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    token = f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
    }


def verify_admin_access_token(token: str) -> dict | None:
    candidate = (token or "").strip()
    if not candidate or "." not in candidate:
        return None

    try:
        payload_part, signature_part = candidate.split(".", 1)
        payload_bytes = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
        expected_signature = hmac.new(_get_admin_secret().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            return None

        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = int(payload.get("exp") or 0)
        if exp <= int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _extract_bearer_token(authorization: str | None) -> str | None:
    value = (authorization or "").strip()
    if not value:
        return None
    parts = value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def admin_auth_protection(
    request: Request,
    authorization: str = Header(default=None, alias="Authorization"),
):
    token = _extract_bearer_token(authorization) or request.cookies.get("om_admin_session")
    claims = verify_admin_access_token(token or "")
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin access token",
        )
    return claims


async def api_key_protection(
    request: Request = None,  # keep Request type so FastAPI injects it; default None for direct calls/tests
    websocket: WebSocket = None,
    x_api_key: str = Header(default=None, alias="X-API-KEY"),
):
    debug = os.getenv("API_KEY_DEBUG", "").lower() in ("1", "true", "yes")
    active_scope = request if request is not None else websocket
    path = active_scope.url.path if active_scope is not None else "<no-request>"
    if debug:
        logger.info("API key check: path=%s header_present=%s", path, bool(x_api_key))

    if active_scope is not None and active_scope.url.path in _ALLOWLIST_PATHS:
        if debug:
            logger.info("API key check: allowlisted path=%s", path)
        return

    valid_keys = get_api_keys()
    header_api_key = (x_api_key or "").strip()
    if active_scope is not None:
        header_api_key = str(active_scope.headers.get("x-api-key") or "").strip()

    candidate = header_api_key

    ok = bool(candidate) and any(hmac.compare_digest(candidate, k) for k in valid_keys)
    if debug:
        logger.info("API key check: path=%s ok=%s configured_keys=%d", path, ok, len(valid_keys))

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
