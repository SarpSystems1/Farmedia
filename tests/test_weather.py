"""Offline tests: forecast parameters (sea-level pressure, fixed model, coordinate precision) and
geocoder precision labels. Network calls are replaced with fakes."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from services import geocoding, weather_service


class _Resp:
    status_code = 200

    def json(self):
        return {"current": {}, "hourly": {}}


class _CapturingClient:
    calls: list[dict] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        _CapturingClient.calls.append({"url": url, "params": params})
        return _Resp()


def _run(coro):
    return asyncio.run(coro)


class ForecastParamsTest(unittest.TestCase):
    def setUp(self):
        _CapturingClient.calls = []

    def _capture(self, fn, *args):
        with mock.patch.object(weather_service.httpx, "AsyncClient", _CapturingClient):
            _run(fn(*args))
        return _CapturingClient.calls[-1]["params"]

    def test_forecast_uses_sea_level_pressure_not_station_pressure(self):
        params = self._capture(weather_service.get_forecast, 39.9043, 41.2679)
        requested = params["current"].split(",")
        self.assertIn("pressure_msl", requested)
        self.assertNotIn("surface_pressure", requested)

    def test_forecast_pins_one_model(self):
        params = self._capture(weather_service.get_forecast, 40.18, 29.07)
        self.assertEqual(params["models"], weather_service.FORECAST_MODEL)
        self.assertEqual(weather_service.FORECAST_MODEL, "ecmwf_ifs025")

    def test_hourly_analysis_uses_the_same_model(self):
        params = self._capture(weather_service.get_weather_data, 40.18, 29.07)
        self.assertEqual(params["models"], weather_service.FORECAST_MODEL)

    def test_coordinates_are_rounded_to_four_decimals(self):
        params = self._capture(weather_service.get_forecast, 40.182612345, 29.066512345)
        self.assertEqual(params["latitude"], 40.1826)
        self.assertEqual(params["longitude"], 29.0665)

    def test_out_of_range_coordinates_rejected(self):
        from services.errors import InvalidInputError
        with self.assertRaises(InvalidInputError):
            _run(weather_service.get_forecast(95.0, 0.0))


class GeocodePrecisionTest(unittest.TestCase):
    """The precision label must name the finest level that was really searched."""

    def _geocode(self, found_queries, **kwargs):
        async def fake_query(q, lang):
            if q in found_queries:
                return {"lat": 40.18, "lon": 29.07, "display_name": q}
            return None

        with mock.patch.object(geocoding, "_query", side_effect=fake_query):
            return _run(geocoding.geocode_location(**kwargs))

    def test_empty_district_is_not_reported_as_district(self):
        hit = self._geocode({"Bursa, Turkey"}, country="Turkey", city="Bursa", district="")
        self.assertEqual(hit["precision"], "city")

    def test_district_found_reports_district(self):
        hit = self._geocode({"Nilüfer, Bursa, Turkey"}, country="Turkey", city="Bursa", district="Nilüfer")
        self.assertEqual(hit["precision"], "district")

    def test_district_not_found_falls_back_to_city(self):
        hit = self._geocode({"Bursa, Turkey"}, country="Turkey", city="Bursa", district="Yokİlçe")
        self.assertEqual(hit["precision"], "city")

    def test_only_country_reports_country(self):
        hit = self._geocode({"Turkey"}, country="Turkey", city="", district="")
        self.assertEqual(hit["precision"], "country")


if __name__ == "__main__":
    unittest.main()
