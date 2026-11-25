"""Legal-compliance rules: jurisdiction from country, and which consents each jurisdiction needs.

Mirrors public.jurisdiction_for() in db/schema.sql. Keep both in sync. The database re-checks
everything at sign-up, so this module is the friendly, early check; the trigger is the guarantee.

NOTE: This is an engineering mapping of publicly known rules (KVKK, GDPR, CCPA). It is not legal
advice. Wording of the documents and the final consent set must be approved by counsel.
"""

from __future__ import annotations

from dataclasses import dataclass

# Countries under the GDPR regime (EU-27, EEA extras, UK).
_GDPR_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    "IS", "LI", "NO", "GB",
})

SUPPORTED_LOCALES = ("tr", "en")

# Consent keys accepted by the API and stored in consent_log.
TERMS = "terms"
PRIVACY = "privacy_policy"
KVKK_EXPLICIT = "kvkk_explicit"
KVKK_TRANSFER = "kvkk_transfer"
ALERT_EMAIL = "alert_email"
ALERT_SMS = "alert_sms"
MARKETING_EMAIL = "marketing_email"
DO_NOT_SELL = "do_not_sell"


@dataclass(frozen=True)
class Requirements:
    jurisdiction: str
    required: tuple[str, ...]  # must be accepted (true) to register
    optional: tuple[str, ...]  # default off; user may switch on


def jurisdiction_for(country: str) -> str:
    code = (country or "").strip().upper()
    if code == "TR":
        return "kvkk"
    if code in _GDPR_COUNTRIES:
        return "gdpr"
    if code == "US":  # CCPA applies to California residents; US-wide is the conservative choice
        return "ccpa"
    return "global"


def requirements_for(country: str) -> Requirements:
    j = jurisdiction_for(country)
    required = [TERMS, PRIVACY]
    if j == "kvkk":
        required += [KVKK_EXPLICIT, KVKK_TRANSFER]
    optional = [ALERT_EMAIL, ALERT_SMS, MARKETING_EMAIL]
    if j == "ccpa":
        optional.append(DO_NOT_SELL)  # opt-out switch, off by default
    return Requirements(jurisdiction=j, required=tuple(required), optional=tuple(optional))


def normalize_locale(locale: str | None) -> str:
    return locale if locale in SUPPORTED_LOCALES else "en"
