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
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m",
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

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
            "weather_code,wind_speed_10m,wind_gusts_10m,surface_pressure,is_day"
        ),
        "hourly": "temperature_2m,dew_point_2m,wind_speed_10m,soil_temperature_0cm",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max,uv_index_max"
        ),
        "forecast_days": 7,
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
