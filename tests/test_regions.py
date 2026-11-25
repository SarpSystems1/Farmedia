"""Offline tests: region lookup, cost figures by country, map search scope, and the market endpoint."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app as app_module
from services import geocoding, regions, suppliers
from services.cost_insights import ESTIMATES, build_cost_insights


class RegionsTest(unittest.TestCase):
    def test_names_map_to_codes(self):
        self.assertEqual(regions.code_from_name("Türkiye"), "TR")
        self.assertEqual(regions.code_from_name("  Turkey "), "TR")
        self.assertEqual(regions.code_from_name("Germany"), "DE")
        self.assertIsNone(regions.code_from_name("Atlantis"))
        self.assertIsNone(regions.code_from_name(""))

    def test_unknown_codes_are_rejected_not_defaulted(self):
        self.assertIsNone(regions.normalize_code("XX"))
        self.assertIsNone(regions.resolve_code(None, None))

    def test_currency_info_for_known_countries(self):
        self.assertEqual(regions.currency_info("TR")["symbol"], "₺")
        self.assertEqual(regions.currency_info("DE")["code"], "EUR")
        self.assertIsNone(regions.currency_info("ZZ"))


class CostInsightsTest(unittest.TestCase):
    def test_turkey_gets_benchmarks_in_lira(self):
        out = build_cost_insights("en", 10, "TR")
        self.assertTrue(out["benchmarks"])
        self.assertEqual(out["currency"]["code"], "TRY")
        self.assertEqual(out["total"], {"min": 10 * sum(e["min"] for e in ESTIMATES),
                                        "max": 10 * sum(e["max"] for e in ESTIMATES)})

    def test_other_country_gets_no_invented_figures(self):
        out = build_cost_insights("en", 10, "DE")
        self.assertFalse(out["benchmarks"])
        self.assertEqual(out["estimates"], [])
        self.assertIsNone(out["total"])
        self.assertEqual(out["currency"]["code"], "EUR")

    def test_turkish_institution_tips_are_turkey_only(self):
        tr_titles = [t["title"] for t in build_cost_insights("en", None, "TR")["tips"]]
        de_titles = [t["title"] for t in build_cost_insights("en", None, "DE")["tips"]]
        self.assertIn("Check support programmes", tr_titles)
        self.assertNotIn("Check support programmes", de_titles)

    def test_unknown_country_has_no_currency(self):
        out = build_cost_insights("en", None, None)
        self.assertFalse(out["benchmarks"])
        self.assertIsNone(out["currency"])


class SearchScopeTest(unittest.TestCase):
    def test_english_links_use_english_terms_and_the_place(self):
        links = suppliers.build_search_links("en", ["Bursa", "Turkey"])
        urls = " ".join(l["url"] for l in links)
        self.assertIn("seed+store+Bursa%2C+Turkey", urls)
        self.assertNotIn("tohumcu", urls)

    def test_turkish_links_use_turkish_terms(self):
        links = suppliers.build_search_links("tr", ["Bursa", "Türkiye"])
        self.assertIn("tohumcu", links[0]["url"])

    def test_empty_parts_are_dropped_not_guessed(self):
        links = suppliers.build_search_links("en", ["", None, "Germany"])
        self.assertIn("seed+store+Germany", links[0]["url"])

    def test_radius_follows_precision(self):
        self.assertLess(suppliers.radius_for_precision("district"), suppliers.radius_for_precision("city"))
        self.assertLess(suppliers.radius_for_precision("city"), suppliers.radius_for_precision("country"))
        self.assertEqual(suppliers.radius_for_precision(None), suppliers.DEFAULT_RADIUS_KM)


class MarketEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)
        self.fake = mock.AsyncMock(return_value=[])

    def _market(self, **params):
        base = {"latitude": 52.52, "longitude": 13.40, "lang": "en"}
        base.update(params)
        with mock.patch.object(app_module, "find_suppliers", self.fake):
            return self.client.get("/api/market", params=base)

    def test_germany_gets_no_cooperative_link_or_turkish_benchmarks(self):
        r = self._market(country="Germany", country_code="DE", city="Berlin", precision="city")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(body["coop_url"])
        self.assertFalse(body["costs"]["benchmarks"])
        self.assertEqual(body["country_code"], "DE")

    def test_turkey_keeps_the_cooperative_link(self):
        r = self._market(latitude=40.18, longitude=29.07, country="Turkey", country_code="TR", city="Bursa")
        self.assertEqual(r.json()["coop_url"], app_module.COOP_URL)

    def test_radius_comes_from_precision_when_not_given(self):
        r = self._market(precision="district")
        self.assertEqual(r.json()["radius_km"], suppliers.radius_for_precision("district"))
        self.assertEqual(self.fake.await_args.args[2], suppliers.radius_for_precision("district"))

    def test_search_centre_is_the_requested_coordinate(self):
        self._market(latitude=52.52, longitude=13.40, precision="city")
        self.assertEqual(self.fake.await_args.args[:2], (52.52, 13.40))

    def test_oversized_radius_rejected(self):
        self.assertEqual(self._market(radius_km=500).status_code, 422)

    def test_unknown_precision_rejected(self):
        self.assertEqual(self._market(precision="planet").status_code, 422)

    def test_no_country_means_no_region_data_and_no_turkey_links(self):
        r = self._market()
        body = r.json()
        self.assertIsNone(body["country_code"])
        self.assertIsNone(body["coop_url"])
        self.assertNotIn("tohumcu", " ".join(l["url"] for l in body["search_links"]))


class GeocodeCountryCodeTest(unittest.TestCase):
    def test_country_code_is_read_from_nominatim_address(self):
        payload = [{"lat": "52.5200", "lon": "13.4050", "display_name": "Berlin, Germany",
                    "address": {"country_code": "de"}}]

        class Resp:
            status_code = 200

            def json(self):
                return payload

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None):
                return Resp()

        geocoding._cache.clear()
        with mock.patch.object(geocoding.httpx, "AsyncClient", FakeClient):
            hit = asyncio.run(geocoding._query("Berlin, Germany", "en"))
        self.assertEqual(hit["country_code"], "DE")
        self.assertEqual(hit["latitude"], 52.52)


if __name__ == "__main__":
    unittest.main()
