"""Country facts used across the app: display name, currency and number format.

Only the countries offered at sign-up are listed. For any other country the functions return None,
and the app shows no region-specific prices or cooperative links. It never falls back to Turkey.
"""

from __future__ import annotations

from typing import Any

REGIONS: dict[str, dict[str, Any]] = {
    "TR": {"name": {"tr": "Türkiye", "en": "Turkey"}, "currency": "TRY", "symbol": "₺", "locale": "tr-TR"},
    "US": {"name": {"tr": "ABD", "en": "United States"}, "currency": "USD", "symbol": "$", "locale": "en-US"},
    "GB": {"name": {"tr": "Birleşik Krallık", "en": "United Kingdom"}, "currency": "GBP", "symbol": "£", "locale": "en-GB"},
    "DE": {"name": {"tr": "Almanya", "en": "Germany"}, "currency": "EUR", "symbol": "€", "locale": "de-DE"},
    "FR": {"name": {"tr": "Fransa", "en": "France"}, "currency": "EUR", "symbol": "€", "locale": "fr-FR"},
    "NL": {"name": {"tr": "Hollanda", "en": "Netherlands"}, "currency": "EUR", "symbol": "€", "locale": "nl-NL"},
    "ES": {"name": {"tr": "İspanya", "en": "Spain"}, "currency": "EUR", "symbol": "€", "locale": "es-ES"},
    "IT": {"name": {"tr": "İtalya", "en": "Italy"}, "currency": "EUR", "symbol": "€", "locale": "it-IT"},
    "PL": {"name": {"tr": "Polonya", "en": "Poland"}, "currency": "PLN", "symbol": "zł", "locale": "pl-PL"},
    "CA": {"name": {"tr": "Kanada", "en": "Canada"}, "currency": "CAD", "symbol": "CA$", "locale": "en-CA"},
    "AU": {"name": {"tr": "Avustralya", "en": "Australia"}, "currency": "AUD", "symbol": "A$", "locale": "en-AU"},
}

# Names users may have typed in the free-text profile field before country codes were stored.
_NAME_TO_CODE = {
    "turkey": "TR", "türkiye": "TR", "turkiye": "TR", "tr": "TR", "türkei": "TR",
    "united states": "US", "usa": "US", "us": "US", "united states of america": "US", "abd": "US",
    "united kingdom": "GB", "uk": "GB", "gb": "GB", "england": "GB", "birleşik krallık": "GB",
    "germany": "DE", "deutschland": "DE", "de": "DE", "almanya": "DE",
    "france": "FR", "fr": "FR", "fransa": "FR",
    "netherlands": "NL", "nederland": "NL", "hollanda": "NL", "nl": "NL",
    "spain": "ES", "españa": "ES", "espana": "ES", "es": "ES", "ispanya": "ES", "i̇spanya": "ES",
    "italy": "IT", "italia": "IT", "it": "IT", "italya": "IT",
    "poland": "PL", "polska": "PL", "pl": "PL", "polonya": "PL",
    "canada": "CA", "ca": "CA", "kanada": "CA",
    "australia": "AU", "au": "AU", "avustralya": "AU",
}


def normalize_code(value: str | None) -> str | None:
    """A two-letter code from a client, if it is one we know. Unknown codes return None."""
    code = (value or "").strip().upper()
    return code if code in REGIONS else None


def code_from_name(name: str | None) -> str | None:
    """Best-effort mapping from a typed country name to a code. None when unsure."""
    return _NAME_TO_CODE.get((name or "").strip().lower())


def resolve_code(code: str | None, name: str | None = None) -> str | None:
    return normalize_code(code) or code_from_name(name)


def country_name(code: str | None, lang: str) -> str:
    region = REGIONS.get(code or "")
    if not region:
        return ""
    return region["name"]["tr" if lang == "tr" else "en"]


def currency_info(code: str | None) -> dict[str, str] | None:
    region = REGIONS.get(code or "")
    if not region:
        return None
    return {"code": region["currency"], "symbol": region["symbol"], "locale": region["locale"]}
