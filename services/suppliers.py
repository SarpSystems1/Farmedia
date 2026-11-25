"""Local seed / agricultural-machinery supplier lookup (OpenStreetMap via Overpass API)."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any
from urllib.parse import quote_plus

import httpx

from services.errors import UpstreamFailureError

# Public Overpass mirrors, tried in order. Checked live: the main server often answers 502 when
# busy; the two fallbacks answered within seconds. kumi.systems timed out, so it comes last.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# Overpass usage policy: identify the application.
USER_AGENT = "Farmedia/2.0 (agricultural weather assistant)"
OVERPASS_TIMEOUT_S = 40          # server-side query timeout (was 25)
HTTP_TIMEOUT_S = 45.0            # client-side timeout per request (was 25)
FETCH_BUDGET_S = 75.0            # total time across all mirrors and retries for one request
CACHE_TTL_S = 24 * 3600          # fresh: served without contacting any mirror
STALE_TTL_S = 7 * 24 * 3600      # stale: served only when every mirror fails
CACHE_MAX_ENTRIES = 256
MAX_RESULTS = 15
MAX_FETCH = 100
RETRIES_PER_MIRROR = 1
RETRYABLE_STATUS = {429, 502, 503, 504}

# Keyed by (lat rounded to 2 dp, lon rounded to 2 dp, radius km). 2 dp is about 1 km, so nearby
# users share one entry. Only successful lookups are stored, so an outage is never cached.
_cache: dict[tuple[float, float, int], tuple[float, list[dict[str, Any]]]] = {}

_CATEGORY_PATTERNS = (
    ("seed", re.compile(r"tohum|seed|fide|fidan|nursery|sapling")),
    ("machinery", re.compile(r"traktor|tractor|makin|machin|ekipman|equipment|motor|sulama|irrigat")),
)

# Search shortcuts opened in the browser (Google Maps), in the UI language.
SEARCH_TERMS = {
    "tr": {"seed": "tohumcu", "machinery": "tarım makineleri bayii", "inputs": "tarım ilacı gübre bayii"},
    "en": {"seed": "seed store", "machinery": "farm machinery dealer", "inputs": "agricultural supplies fertiliser pesticide"},
}

# Search radius follows how precisely the location is known. A district search should not pull in
# dealers from the next province; a country-level location needs a wide net.
RADIUS_KM_BY_PRECISION = {"district": 15, "city": 40, "state": 80, "country": 200}
DEFAULT_RADIUS_KM = 40


def _fold(s: str) -> str:
    """Lowercase and strip Turkish diacritics so keyword matching works on both spellings."""
    return s.translate(str.maketrans("İI", "ii")).lower().translate(str.maketrans("ışğüöç", "isguoc"))


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _category(tags: dict[str, Any]) -> str:
    if tags.get("shop") == "garden_centre":
        return "garden"
    haystack = _fold(" ".join(str(tags.get(k, "")) for k in ("name", "operator", "brand", "description")))
    for cat, pat in _CATEGORY_PATTERNS:
        if pat.search(haystack):
            return cat
    return "inputs"


def _address(tags: dict[str, Any]) -> str:
    if tags.get("addr:full"):
        return str(tags["addr:full"])
    street = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
    return ", ".join(filter(None, [street, tags.get("addr:district"), tags.get("addr:city")]))


def _query(lat: float, lon: float, radius_m: int) -> str:
    around = f"(around:{radius_m},{lat},{lon})"
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];("
        f'nwr["shop"="agrarian"]{around};'
        f'nwr["shop"="garden_centre"]{around};'
        f");out center tags {MAX_FETCH};"
    )


async def _fetch(query: str) -> dict[str, Any]:
    """POST the query to each mirror in turn until one answers, within FETCH_BUDGET_S.

    Raises UpstreamFailureError only when every mirror failed or the time budget ran out.
    """
    errors: list[str] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    deadline = time.monotonic() + FETCH_BUDGET_S
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers) as client:
        for url in OVERPASS_URLS:
            host = url.split("/")[2]
            for attempt in range(RETRIES_PER_MIRROR + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append("time budget exhausted")
                    raise UpstreamFailureError("Overpass unavailable: " + "; ".join(errors))
                if attempt:
                    await asyncio.sleep(min(2.0 * attempt, remaining))
                try:
                    resp = await client.post(url, data={"data": query},
                                             timeout=min(HTTP_TIMEOUT_S, deadline - time.monotonic()))
                except httpx.RequestError as exc:  # includes timeouts
                    errors.append(f"{host}: {type(exc).__name__}")
                    continue
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        errors.append(f"{host}: invalid json")
                        break
                errors.append(f"{host}: status {resp.status_code}")
                if resp.status_code not in RETRYABLE_STATUS:
                    break
    raise UpstreamFailureError("Overpass unavailable: " + "; ".join(errors))


async def find_suppliers(latitude: float, longitude: float, radius_km: float = 50.0) -> list[dict[str, Any]]:
    """Return up to MAX_RESULTS mapped agricultural suppliers, nearest first. Cached for a day."""
    key = (round(latitude, 2), round(longitude, 2), int(radius_km))
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]

    try:
        data = await _fetch(_query(latitude, longitude, int(radius_km * 1000)))
    except UpstreamFailureError:
        # All mirrors are down or busy: a week-old answer for the same area is still useful.
        if hit and now - hit[0] < STALE_TTL_S:
            return hit[1]
        raise

    items: list[dict[str, Any]] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        center = el.get("center") or {}
        lat = el.get("lat", center.get("lat"))
        lon = el.get("lon", center.get("lon"))
        if lat is None or lon is None:
            continue
        items.append(
            {
                "name": tags.get("name"),
                "category": _category(tags),
                "distance_km": round(_distance_km(latitude, longitude, lat, lon), 1),
                "address": _address(tags),
                "phone": tags.get("phone") or tags.get("contact:phone"),
                "website": tags.get("website") or tags.get("contact:website"),
                "opening_hours": tags.get("opening_hours"),
                "osm_url": f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id')}",
            }
        )

    items.sort(key=lambda i: i["distance_km"])
    items = items[:MAX_RESULTS]

    if len(_cache) >= CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[key] = (now, items)
    return items


def radius_for_precision(precision: str | None) -> int:
    return RADIUS_KM_BY_PRECISION.get(precision or "", DEFAULT_RADIUS_KM)


def build_search_links(lang: str, place_parts: list[str]) -> list[dict[str, str]]:
    """Map-search shortcuts for the place the user chose, e.g. "seed store, Bursa, Turkey".

    place_parts are ordered most specific first (city, state, country name). Only the parts that
    are known are used, so no country is guessed.
    """
    terms = SEARCH_TERMS["tr" if lang == "tr" else "en"]
    seen: set[str] = set()
    parts = []
    for p in place_parts:
        p = (p or "").strip()
        if p and p.casefold() not in seen:   # "Berlin" as city and as state is one place, not two
            seen.add(p.casefold())
            parts.append(p)
    place = ", ".join(parts)[:200]
    links = []
    for cat, term in terms.items():
        q = f"{term} {place}".strip()
        links.append(
            {
                "category": cat,
                "url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q),
            }
        )
    return links
