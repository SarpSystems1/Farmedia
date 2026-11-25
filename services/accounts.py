"""Account rules: registration, login, legal consents, profile reads and updates.

All user-data access goes through services.supabase_client with the user's own token, so
RLS in db/schema.sql is the final authority. Sign-up consents are checked here first for a
clear error message, and re-checked by the database trigger, which is the real guarantee.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from services import compliance as legal
from services import supabase_client as sb
from services.errors import (
    AuthenticationError,
    ConflictError,
    ConsentRequiredError,
    InvalidInputError,
    NotConfiguredError,
)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Fields a user may change after sign-up, and the consent type each one logs under.
_CONSENT_FIELDS = {
    "alert_email_consent": "alert_email",
    "alert_sms_consent": "alert_sms",
    "marketing_email_consent": "marketing_email",
    "do_not_sell": "do_not_sell",
}
_PROFILE_FIELDS = {"first_name", "last_name", "role", "farm_size", "location", "crops", "preferences"} | set(_CONSENT_FIELDS)

# UI preferences that follow the user across devices. Anything else is dropped, not stored.
_PREF_ALLOWED = {
    "theme": {"system", "light", "dark"},
    "density": {"comfortable", "compact"},
    "forecastDays": {3, 5, 7},
}


def _checked_preferences(prefs: Any) -> dict[str, Any]:
    if not isinstance(prefs, dict):
        raise InvalidInputError("preferences must be an object.", field="preferences")
    clean: dict[str, Any] = {}
    for key, allowed in _PREF_ALLOWED.items():
        if key in prefs:
            value = prefs[key]
            if isinstance(value, bool) or not isinstance(value, (str, int)) or value not in allowed:
                raise InvalidInputError(f"preferences.{key} has an unsupported value.", field="preferences")
            clean[key] = value
    return clean


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise InvalidInputError("Enter a valid email address.", field="email")
    return email


PASSWORD_MIN = 6    # the product requirement; enable Supabase's leaked-password check for more safety
PASSWORD_MAX = 128


def validate_password(password: str) -> None:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise InvalidInputError(
            f"Password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters.", field="password")


def _name(value: str, field: str) -> str:
    value = (value or "").strip()
    if not 1 <= len(value) <= 60:
        raise InvalidInputError(f"{field} must be 1 to 60 characters.", field=field)
    return value


def _country(value: str) -> str:
    code = (value or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise InvalidInputError("Country must be a 2-letter ISO code, e.g. TR or US.", field="country")
    return code


def _checked_consents(consents: dict[str, Any]) -> dict[str, bool]:
    """Consent values must be real booleans. "false" or 1 would otherwise be read as a yes."""
    for key, value in consents.items():
        if not isinstance(value, bool):
            raise InvalidInputError(f"{key} must be true or false.", field=key)
    return consents


# ---------- legal documents ----------

async def current_documents(locale: str) -> dict[str, dict[str, str]]:
    """Currently published Terms and Privacy Policy for a locale. Readable without sign-in."""
    rows = await sb.rest("GET", "legal_documents", sb.anon_key(),
                         params={"is_current": "eq.true", "locale": f"eq.{locale}",
                                 "select": "doc_type,version,url"})
    return {r["doc_type"]: {"version": r["version"], "url": r["url"]} for r in rows}


async def legal_requirements(country: str, locale: str | None) -> dict[str, Any]:
    """What the sign-up form must show for this country and language."""
    loc = legal.normalize_locale(locale)
    reqs = legal.requirements_for(_country(country))
    docs = await current_documents(loc)
    return {
        "country": country.upper(),
        "jurisdiction": reqs.jurisdiction,
        "locale": loc,
        "required_consents": list(reqs.required),
        "optional_consents": list(reqs.optional),
        "documents": docs,
        "ready": "terms" in docs and "privacy" in docs,
    }


# ---------- registration / login ----------

async def register(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    country: str,
    locale: str | None,
    terms_version: str,
    privacy_version: str,
    consents: dict[str, bool],
) -> dict[str, Any]:
    """Create an account. The database trigger writes the profile and the consent log."""
    email = normalize_email(email)
    validate_password(password)
    country = _country(country)
    loc = legal.normalize_locale(locale)
    reqs = legal.requirements_for(country)
    consents = _checked_consents(consents)

    missing = [c for c in reqs.required if consents.get(c) is not True]
    if missing:
        raise ConsentRequiredError(f"Required consent not given: {', '.join(missing)}")

    docs = await current_documents(loc)
    if "terms" not in docs or "privacy" not in docs:
        raise NotConfiguredError("Legal documents have not been published yet.")
    if terms_version != docs["terms"]["version"] or privacy_version != docs["privacy"]["version"]:
        raise ConsentRequiredError("Please review the latest Terms of Service and Privacy Policy.")

    metadata = {
        "first_name": _name(first_name, "first_name"),
        "last_name": _name(last_name, "last_name"),
        "country": country,
        "locale": loc,
        "terms_accepted": True,
        "terms_version": docs["terms"]["version"],
        "privacy_accepted": True,
        "privacy_version": docs["privacy"]["version"],
        "kvkk_explicit": consents.get(legal.KVKK_EXPLICIT) is True,
        "kvkk_transfer": consents.get(legal.KVKK_TRANSFER) is True,
        "alert_email": consents.get(legal.ALERT_EMAIL) is True,
        "alert_sms": consents.get(legal.ALERT_SMS) is True,
        "marketing_email": consents.get(legal.MARKETING_EMAIL) is True,
        "do_not_sell": consents.get(legal.DO_NOT_SELL) is True,
    }
    try:
        result = await sb.auth_signup(email, password, metadata)
    except ConflictError:
        # Do not reveal that this email is already registered. The response has the same shape
        # as a new sign-up that awaits confirmation, and no second account is created.
        return {"user": None, "jurisdiction": reqs.jurisdiction, "session": None,
                "confirmation_required": True}
    # With email confirmation enabled, Supabase returns the user without a session.
    session = result if "access_token" in result else None
    return {
        "user": {"id": (result.get("user") or result).get("id"), "email": email},
        "jurisdiction": reqs.jurisdiction,
        "session": _session(session) if session else None,
        "confirmation_required": session is None,
    }


async def login(email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    if not password:
        raise InvalidInputError("Password is required.", field="password")
    tokens = await sb.auth_password_login(email, password)
    return {"session": _session(tokens), "user": tokens.get("user", {})}


async def refresh_session(refresh_token: str) -> dict[str, Any]:
    """Get a new session from a refresh token. The returned refresh token replaces the old one."""
    if not refresh_token or len(refresh_token) > 512:
        raise AuthenticationError()
    tokens = await sb.auth_refresh(refresh_token)
    return {"session": _session(tokens), "user": tokens.get("user", {})}


async def logout(access_token: str) -> None:
    """Revoke this user's sessions at Supabase."""
    await sb.auth_logout(access_token)


def _session(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_in": tokens.get("expires_in"),
        "token_type": "bearer",
    }


async def get_current_user(access_token: str) -> dict[str, Any]:
    """Validate the token and return the user together with their profile (RLS-scoped)."""
    user = await sb.auth_get_user(access_token)
    rows = await sb.rest("GET", "profiles", access_token,
                         params={"id": f"eq.{user['id']}", "select": "*"})
    return {"user": {"id": user["id"], "email": user.get("email")},
            "profile": rows[0] if rows else None}


# ---------- profile updates ----------

async def update_profile(access_token: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Update editable fields and log consent changes, in one database transaction.

    The SQL function public.update_profile_with_consents (db/schema.sql) runs as the signed-in
    user, so RLS applies. It writes the profile row and the consent_log rows together, so a
    failed log write cannot leave a changed consent without its audit entry.
    """
    unknown = set(changes) - _PROFILE_FIELDS
    if unknown:
        raise InvalidInputError(f"Field(s) cannot be updated: {', '.join(sorted(unknown))}", field="body")
    if not changes:
        raise InvalidInputError("No fields to update.", field="body")

    payload = dict(changes)
    for field in _CONSENT_FIELDS:
        if field in payload and not isinstance(payload[field], bool):
            raise InvalidInputError(f"{field} must be true or false.", field=field)
    if "preferences" in payload:
        payload["preferences"] = _checked_preferences(payload["preferences"])
    if "first_name" in payload:
        payload["first_name"] = _name(payload["first_name"], "first_name")
    if "last_name" in payload:
        payload["last_name"] = _name(payload["last_name"], "last_name")

    row = await sb.rpc("update_profile_with_consents", access_token, {"p_changes": payload})
    return row or {}


# ---------- data-subject rights: export and deletion ----------

async def export_user_data(access_token: str) -> dict[str, Any]:
    """A portable JSON copy of the signed-in user's personal data (GDPR Art. 20, CCPA, KVKK Art. 11).

    Reads run as the user, so RLS limits them to the user's own rows.
    """
    me = await get_current_user(access_token)
    consents = await sb.rest("GET", "consent_log", access_token, params={
        "select": "consent_type,granted,version,recorded_at",
        "order": "recorded_at.asc",
    })
    return {
        "format": "farmedia-export",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": me["user"],
        "profile": me["profile"],
        "consent_history": consents,
    }


async def delete_account(access_token: str, password: str) -> None:
    """Permanently delete the signed-in account.

    The password is required again, so a stolen access token alone cannot delete the account.
    The deletion itself runs in one database transaction (public.delete_own_account): it
    removes the profile and login, and keeps consent records as anonymous proof of consent.
    """
    if not password:
        raise InvalidInputError("Password is required to delete your account.", field="password")
    user = await sb.auth_get_user(access_token)
    email = user.get("email")
    if not email:
        raise AuthenticationError()
    # Raises AuthenticationError on a wrong password. The session it returns is discarded.
    await sb.auth_password_login(email, password)
    await sb.rpc("delete_own_account", access_token, {})
