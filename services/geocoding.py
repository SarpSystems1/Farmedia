"""Nominatim (OpenStreetMap) geocoding for the profile location."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from services.errors import (
    InvalidInputError,
    LocationNotFoundError,
    UpstreamFailureError,
    UpstreamTimeoutError,
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim usage policy: identify the application, max 1 request/second.
USER_AGENT = "Farmedia/2.0 (agricultural weather assistant)"

_lock = asyncio.Lock()
_last_call = 0.0
_cache: dict[tuple, dict[str, Any]] = {}


async def _query(q: str, lang: str) -> dict[str, Any] | None:
    global _last_call
    key = (q.lower(), lang)
    if key in _cache:
        return _cache[key]

    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
        "accept-language": lang,
    }
    async with _lock:
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(NOMINATIM_URL, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("Nominatim timed out.") from exc
        except httpx.RequestError as exc:
            raise UpstreamFailureError(f"Nominatim request failed: {exc}") from exc
        finally:
            _last_call = time.monotonic()

    if resp.status_code != 200:
        raise UpstreamFailureError(f"Nominatim returned status {resp.status_code}")
    data = resp.json()
    if not data:
        return None
    hit = data[0]
    result = {
        "latitude": round(float(hit["lat"]), 5),
        "longitude": round(float(hit["lon"]), 5),
        "display_name": hit.get("display_name", q),
        # ISO 3166-1 alpha-2 from Nominatim's address details; drives currency and map searches.
        "country_code": ((hit.get("address") or {}).get("country_code") or "").upper() or None,
    }
    _cache[key] = result
    return result


async def geocode_location(
    country: str, state: str = "", city: str = "", district: str = "", lang: str = "en"
) -> dict[str, Any]:
    """Resolve the most specific location possible, relaxing from district upwards."""
    country, state, city, district = (s.strip() for s in (country, state, city, district))
    if not country and not city:
        raise InvalidInputError("Country or city is required.", field="location")

    # Most specific first; progressively drop the finest level until something matches.
    levels = [district, city, state, country]
    names = ["district", "city", "state", "country"]
    tried: set[str] = set()
    for start in range(len(levels)):
        parts = [p for p in levels[start:] if p]
        if not parts:
            continue
        q = ", ".join(parts)
        if q in tried:
            continue
        tried.add(q)
        hit = await _query(q, lang)
        if hit:
            # The precision is the finest level that was really searched. An empty district must
            # not be reported as "district" precision: the search started at the city.
            finest = next(i for i in range(start, len(levels)) if levels[i])
            hit["precision"] = names[finest]
            return hit
    raise LocationNotFoundError(query=", ".join(p for p in levels if p))
