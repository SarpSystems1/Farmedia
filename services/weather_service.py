"""Open-Meteo API ile iletişim kuran hava durumu ve geocoding servisi."""

from __future__ import annotations

import httpx
from typing import Any

from services.errors import (
    LocationNotFoundError,
    UpstreamFailureError,
    UpstreamTimeoutError,
    InvalidInputError,
)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# One forecast model for every request, so the numbers do not change with the server's default.
# ECMWF IFS 0.25 deg (global, live-checked against Open-Meteo).
FORECAST_MODEL = "ecmwf_ifs025"
# Open-Meteo snaps to its model grid (about 0.25 deg), so more decimals add nothing. 4 decimals
# (about 11 m) keeps the request exact and gives stable values for caching.
COORD_DECIMALS = 4


def _grid_point(latitude: float, longitude: float) -> tuple[float, float]:
    return round(float(latitude), COORD_DECIMALS), round(float(longitude), COORD_DECIMALS)


async def get_coordinates(city: str) -> dict[str, Any]:
    """Şehir adını alarak enlem, boylam, ülke ve şehir bilgilerini döndürür."""
    if not city or not city.strip():
        raise InvalidInputError("City name cannot be empty.", field="city")

    params = {"name": city.strip(), "count": 1, "language": "tr", "format": "json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(GEOCODE_URL, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("Geocoding service timed out.") from exc
        except httpx.RequestError as exc:
            raise UpstreamFailureError(f"Geocoding request failed: {exc}") from exc

    if response.status_code != 200:
        raise UpstreamFailureError(f"Geocoding returned status code {response.status_code}")

    data = response.json()
    results = data.get("results")

    if not results:
        raise LocationNotFoundError(query=city)

    location = results[0]
    return {
        "name": location.get("name"),
        "country": location.get("country"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "elevation": location.get("elevation", 0.0),
        "timezone": location.get("timezone", "Europe/Istanbul"),
    }


async def get_weather_data(latitude: float, longitude: float) -> dict[str, Any]:
    """Belirtilen koordinatlar için güncel ve saatlik hava durumu verilerini çeker."""
        
    # Şafak öncesi ve don analitiği için gerekli saatlik parametreler:
    # temperature_2m, relative_humidity_2m, dew_point_2m, wind_speed_10m
    lat, lon = _grid_point(latitude, longitude)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m",
        "models": FORECAST_MODEL,
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(WEATHER_URL, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("Weather forecast service timed out.") from exc
        except httpx.RequestError as exc:
            raise UpstreamFailureError(f"Weather forecast request failed: {exc}") from exc

    if response.status_code != 200:
        raise UpstreamFailureError(f"Weather forecast returned status code {response.status_code}")

    return response.json()

async def get_forecast(latitude: float, longitude: float) -> dict[str, Any]:
    """Current conditions, 48h hourly series and a 7-day daily forecast for the dashboard."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidInputError("Coordinates out of range.", field="coordinates")

    lat, lon = _grid_point(latitude, longitude)
    params = {
        "latitude": lat,
        "longitude": lon,
        # pressure_msl is sea-level pressure. surface_pressure is the raw station value, which
        # reads about 810 hPa at 1,900 m (Erzurum) and made the dashboard look wrong.
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
            "weather_code,wind_speed_10m,wind_gusts_10m,pressure_msl,is_day"
        ),
        "hourly": "temperature_2m,dew_point_2m,wind_speed_10m,soil_temperature_0cm",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max,uv_index_max"
        ),
        "forecast_days": 7,
        "models": FORECAST_MODEL,
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            response = await client.get(WEATHER_URL, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("Weather forecast service timed out.") from exc
        except httpx.RequestError as exc:
            raise UpstreamFailureError(f"Weather forecast request failed: {exc}") from exc

    if response.status_code != 200:
        raise UpstreamFailureError(f"Weather forecast returned status code {response.status_code}")
    return response.json()
