"""Thin async client for Supabase Auth (GoTrue) and PostgREST, built on httpx.

Security model
--------------
* Passwords never reach our database or logs. Supabase Auth stores them hashed (bcrypt).
* The backend only uses the public ``anon`` key. Every data request carries the
  signed-in user's access token, so Postgres Row Level Security decides what the
  user may read or write. The ``service_role`` key (which bypasses RLS) is deliberately
  NOT used anywhere in this code base.

Configuration (environment / .env)
----------------------------------
SUPABASE_URL       e.g. https://<project-ref>.supabase.co
SUPABASE_ANON_KEY  the public anon key from the Supabase dashboard
"""

from __future__ import annotations

import os
from typing import Any, NoReturn

import httpx
from dotenv import load_dotenv

from services.errors import (
    AuthenticationError,
    ConflictError,
    EmailNotConfirmedError,
    InvalidInputError,
    NotConfiguredError,
    RuleViolationError,
    UpstreamFailureError,
    UpstreamTimeoutError,
    rule_violation_from_db,
)

load_dotenv()

# Tests may inject an httpx.MockTransport here; production leaves it as None.
_transport: httpx.AsyncBaseTransport | None = None
_TIMEOUT = 10.0
_RAISE_SQLSTATE = "P0001"  # plpgsql RAISE EXCEPTION without an explicit SQLSTATE


def _config() -> tuple[str, str]:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY") or ""
    if not url or not anon:
        raise NotConfiguredError("SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
    return url, anon


def anon_key() -> str:
    """The public anon key, for reads that need no user (e.g. published legal documents)."""
    return _config()[1]


async def _request(
    method: str,
    path: str,
    *,
    bearer: str | None = None,
    json: Any = None,
    params: dict[str, str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Send one request. Maps transport failures only; HTTP status handling is done by the callers."""
    url, anon = _config()
    headers = {"apikey": anon, "Authorization": f"Bearer {bearer or anon}"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=_transport) as client:
            return await client.request(method, url + path, json=json, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Supabase did not respond in time.") from exc
    except httpx.RequestError as exc:
        raise UpstreamFailureError(f"Supabase request failed: {type(exc).__name__}") from exc


# ---------- response helpers ----------

def _error_payload(resp: httpx.Response) -> dict[str, Any]:
    """The error body as a dict. Never raises: Supabase may send an object, an array, or plain text."""
    try:
        body = resp.json()
    except ValueError:
        return {}
    if isinstance(body, list):
        body = next((item for item in body if isinstance(item, dict)), {})
    return body if isinstance(body, dict) else {}


def _error_text(resp: httpx.Response) -> str:
    body = _error_payload(resp)
    return " ".join(str(body.get(k, "")) for k in ("error_code", "msg", "message", "error_description", "error"))


def _json_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamFailureError("Supabase returned a response that is not valid JSON.") from exc


def _db_rejection(resp: httpx.Response) -> RuleViolationError | None:
    """A rule raised inside the database (trigger or SQL function). Its text is ours, so it is safe to show."""
    body = _error_payload(resp)
    if body.get("code") == _RAISE_SQLSTATE and body.get("message"):
        return rule_violation_from_db(str(body["message"]))
    return None


def _raise_for_status(resp: httpx.Response, context: str) -> NoReturn:
    if resp.status_code in (401, 403):
        # PostgreSQL 42501 = insufficient privilege: a database grant is missing (see db/schema.sql).
        # That is a server problem, not a bad password or an expired session.
        if _error_payload(resp).get("code") == "42501":
            raise UpstreamFailureError(f"Supabase {context}: missing table privilege, run db/schema.sql grants.")
        raise AuthenticationError()
    rejection = _db_rejection(resp)
    if rejection is not None:
        raise rejection
    raise UpstreamFailureError(f"Supabase {context} returned status {resp.status_code}")


# ---------- Auth ----------

async def auth_signup(email: str, password: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Create an account. Returns the Supabase response (a session if email confirmation is off)."""
    resp = await _request(
        "POST", "/auth/v1/signup",
        json={"email": email, "password": password, "data": metadata},
    )
    if resp.status_code in (200, 201):
        return _json_body(resp)
    text = _error_text(resp).lower()
    if "already" in text or "exists" in text:
        raise ConflictError()
    if "database error" in text:
        # Supabase Auth does not forward the message raised by the sign-up trigger in
        # db/schema.sql. services/accounts.py checks the same rules first, so this is a rare race.
        error = RuleViolationError("Supabase Auth rejected the sign-up in the database.")
        error.message_key = "error.registration_rejected"
        raise error
    if resp.status_code in (400, 422):
        raise InvalidInputError("Registration rejected by the auth provider.", field="registration")
    raise UpstreamFailureError(f"Supabase signup returned status {resp.status_code}")


async def auth_password_login(email: str, password: str) -> dict[str, Any]:
    """Exchange email + password for an access/refresh token pair."""
    resp = await _request(
        "POST", "/auth/v1/token", params={"grant_type": "password"},
        json={"email": email, "password": password},
    )
    if resp.status_code == 200:
        return _json_body(resp)
    if resp.status_code in (400, 401, 403):
        # Supabase checks the password before reporting an unconfirmed email, so telling the user
        # to confirm reveals nothing to someone who does not know the password.
        if _error_payload(resp).get("error_code") == "email_not_confirmed":
            raise EmailNotConfirmedError()
        # Same generic message for wrong password and unknown email, so the endpoint does not
        # reveal which accounts exist.
        raise AuthenticationError()
    raise UpstreamFailureError(f"Supabase login returned status {resp.status_code}")


async def auth_refresh(refresh_token: str) -> dict[str, Any]:
    """Trade a refresh token for a new session. Supabase rotates refresh tokens, so store the new one."""
    resp = await _request(
        "POST", "/auth/v1/token", params={"grant_type": "refresh_token"},
        json={"refresh_token": refresh_token},
    )
    if resp.status_code == 200:
        return _json_body(resp)
    if resp.status_code in (400, 401, 403):
        raise AuthenticationError()
    raise UpstreamFailureError(f"Supabase refresh returned status {resp.status_code}")


async def auth_logout(access_token: str) -> None:
    """Revoke this device's session at Supabase (scope=local). Other devices stay signed in.

    Failures are not fatal: the client drops its tokens anyway.
    """
    try:
        await _request("POST", "/auth/v1/logout", bearer=access_token, params={"scope": "local"})
    except UpstreamFailureError:
        return


async def auth_get_user(access_token: str) -> dict[str, Any]:
    """Validate an access token with Supabase and return the user it belongs to."""
    resp = await _request("GET", "/auth/v1/user", bearer=access_token)
    if resp.status_code == 200:
        return _json_body(resp)
    if resp.status_code in (401, 403):
        raise AuthenticationError()
    raise UpstreamFailureError(f"Supabase user lookup returned status {resp.status_code}")


# ---------- Data (PostgREST, RLS enforced) ----------

async def rest(
    method: str,
    table: str,
    access_token: str,
    *,
    params: dict[str, str] | None = None,
    json: Any = None,
    return_representation: bool = False,
) -> list[dict[str, Any]]:
    """Run a query against ``/rest/v1/<table>`` as the given user (RLS applies).

    Returns a list of rows. An empty success body, including 204 No Content (e.g. DELETE),
    returns an empty list.
    """
    extra = {"Prefer": "return=representation"} if return_representation else None
    resp = await _request(
        method, f"/rest/v1/{table}", bearer=access_token,
        json=json, params=params, extra_headers=extra,
    )
    if resp.status_code == 204 or (resp.status_code in (200, 201) and not resp.content):
        return []
    if resp.status_code in (200, 201):
        body = _json_body(resp)
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            return [body]
        raise UpstreamFailureError("Supabase data request returned an unexpected body.")
    _raise_for_status(resp, "data request")


async def rpc(name: str, access_token: str, args: dict[str, Any]) -> Any:
    """Call a SQL function exposed through PostgREST, as the given user.

    One call is one database transaction, so a function that writes several tables
    either commits all of its writes or none of them.
    """
    resp = await _request("POST", f"/rest/v1/rpc/{name}", bearer=access_token, json=args)
    if resp.status_code == 204 or (resp.status_code in (200, 201) and not resp.content):
        return None
    if resp.status_code in (200, 201):
        return _json_body(resp)
    _raise_for_status(resp, f"rpc {name}")
