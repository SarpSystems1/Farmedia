"""Offline tests for the Overpass supplier lookup: caching, stale fallback and mirror order."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest import mock

from services import suppliers
from services.errors import UpstreamFailureError

ELEMENT = {"type": "node", "id": 1, "lat": 40.19, "lon": 29.07,
           "tags": {"name": "Bursa Tohumculuk", "shop": "agrarian"}}


def _run(coro):
    return asyncio.run(coro)


class SuppliersCacheTest(unittest.TestCase):
    def setUp(self):
        suppliers._cache.clear()

    def test_mirror_list_has_fallbacks_and_longer_timeouts(self):
        self.assertGreaterEqual(len(suppliers.OVERPASS_URLS), 3)
        self.assertGreaterEqual(suppliers.OVERPASS_TIMEOUT_S, 40)
        self.assertGreaterEqual(suppliers.HTTP_TIMEOUT_S, suppliers.OVERPASS_TIMEOUT_S)

    def test_success_is_cached_by_rounded_coordinates(self):
        fetch = mock.AsyncMock(return_value={"elements": [ELEMENT]})
        with mock.patch.object(suppliers, "_fetch", fetch):
            first = _run(suppliers.find_suppliers(40.1826, 29.0665))
            # 40.1830 and 40.1826 round to the same 2-decimal key, so no second mirror call.
            second = _run(suppliers.find_suppliers(40.1830, 29.0670))
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["name"], "Bursa Tohumculuk")

    def test_failed_lookup_is_not_cached(self):
        fetch = mock.AsyncMock(side_effect=[UpstreamFailureError("down"), {"elements": [ELEMENT]}])
        with mock.patch.object(suppliers, "_fetch", fetch):
            with self.assertRaises(UpstreamFailureError):
                _run(suppliers.find_suppliers(40.18, 29.07))
            items = _run(suppliers.find_suppliers(40.18, 29.07))
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(len(items), 1)

    def test_stale_result_served_when_all_mirrors_fail(self):
        key = (round(40.18, 2), round(29.07, 2), 50)
        old = [{"name": "Eski kayıt", "distance_km": 1.0}]
        suppliers._cache[key] = (time.monotonic() - suppliers.CACHE_TTL_S - 60, old)
        fetch = mock.AsyncMock(side_effect=UpstreamFailureError("busy"))
        with mock.patch.object(suppliers, "_fetch", fetch):
            items = _run(suppliers.find_suppliers(40.18, 29.07))
        self.assertEqual(items, old)

    def test_very_old_result_is_not_served(self):
        key = (round(40.18, 2), round(29.07, 2), 50)
        suppliers._cache[key] = (time.monotonic() - suppliers.STALE_TTL_S - 60, [{"name": "x"}])
        fetch = mock.AsyncMock(side_effect=UpstreamFailureError("busy"))
        with mock.patch.object(suppliers, "_fetch", fetch):
            with self.assertRaises(UpstreamFailureError):
                _run(suppliers.find_suppliers(40.18, 29.07))


class SuppliersFetchTest(unittest.TestCase):
    """_fetch walks the mirrors in order and falls through on failure."""

    class _Resp:
        def __init__(self, status, body=None):
            self.status_code = status
            self._body = body

        def json(self):
            if self._body is None:
                raise ValueError("no json")
            return self._body

    def _run_fetch(self, responses):
        seen = []

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, data=None, timeout=None):
                seen.append(url)
                r = responses[len(seen) - 1]
                if isinstance(r, Exception):
                    raise r
                return r

        async def no_sleep(_):
            return None

        with mock.patch.object(suppliers.httpx, "AsyncClient", FakeClient), \
             mock.patch.object(suppliers.asyncio, "sleep", no_sleep):
            try:
                result = _run(suppliers._fetch("q"))
            except UpstreamFailureError as exc:
                result = exc
        return result, seen

    def test_falls_through_to_the_fallback_mirror(self):
        ok = self._Resp(200, {"elements": []})
        # Main mirror: 502 twice (one retry), then the first fallback answers.
        result, seen = self._run_fetch([self._Resp(502), self._Resp(502), ok])
        self.assertEqual(result, {"elements": []})
        self.assertEqual(seen[0], suppliers.OVERPASS_URLS[0])
        self.assertEqual(seen[2], suppliers.OVERPASS_URLS[1])

    def test_all_mirrors_down_raises(self):
        down = [self._Resp(503)] * (len(suppliers.OVERPASS_URLS) * 2)
        result, _ = self._run_fetch(down)
        self.assertIsInstance(result, UpstreamFailureError)

    def test_non_retryable_status_skips_retry_of_same_mirror(self):
        result, seen = self._run_fetch([self._Resp(400), self._Resp(200, {"elements": []})])
        self.assertEqual(seen[0], suppliers.OVERPASS_URLS[0])
        self.assertEqual(seen[1], suppliers.OVERPASS_URLS[1])
        self.assertEqual(result, {"elements": []})


if __name__ == "__main__":
    unittest.main()
