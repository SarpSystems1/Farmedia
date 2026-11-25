"""Offline tests for Sarp AI (Groq). No network: the Groq client is replaced with a fake."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
import openai

import app as app_module
from services import sarp_ai
from services.errors import NotConfiguredError, UpstreamFailureError, UpstreamTimeoutError


def _reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeCompletions:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def _fake_client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _request(method="POST"):
    return httpx.Request(method, "https://api.groq.com/openai/v1/chat/completions")


class SarpAIServiceTest(unittest.TestCase):
    def setUp(self):
        self._saved_client = sarp_ai._client
        sarp_ai._client = None

    def tearDown(self):
        sarp_ai._client = self._saved_client

    def test_missing_key_raises_not_configured(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with self.assertRaises(NotConfiguredError):
                sarp_ai._get_client()

    def test_client_points_at_groq_with_key(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            client = sarp_ai._get_client()
        self.assertEqual(str(client.base_url).rstrip("/"), sarp_ai.GROQ_BASE_URL)
        self.assertEqual(client.api_key, "test-key")

    def test_uses_llama_model_and_system_prompt(self):
        completions = FakeCompletions(result=_reply("  Sulamayı sabah yapın.  "))
        sarp_ai._client = _fake_client(completions)
        answer = asyncio.run(sarp_ai.get_sarp_ai_advice("Domates nasıl sulanır?", "Şehir: Bursa", "tr"))
        self.assertEqual(answer, "Sulamayı sabah yapın.")
        call = completions.calls[0]
        self.assertEqual(call["model"], sarp_ai.SARP_MODEL)
        self.assertIn("Sarp AI", call["messages"][0]["content"])
        self.assertIn("Turkish", call["messages"][0]["content"])
        self.assertIn("Şehir: Bursa", call["messages"][1]["content"])

    def test_english_request_asks_for_english(self):
        completions = FakeCompletions(result=_reply("Water in the morning."))
        sarp_ai._client = _fake_client(completions)
        asyncio.run(sarp_ai.get_sarp_ai_advice("How do I water tomatoes?", lang="en"))
        self.assertIn("English", completions.calls[0]["messages"][0]["content"])

    def test_timeout_maps_to_504_error(self):
        err = openai.APITimeoutError(request=_request())
        sarp_ai._client = _fake_client(FakeCompletions(error=err))
        with self.assertRaises(UpstreamTimeoutError):
            asyncio.run(sarp_ai.get_sarp_ai_advice("soru"))

    def test_api_error_maps_to_502_error(self):
        err = openai.APIStatusError("invalid key", response=httpx.Response(401, request=_request()), body=None)
        sarp_ai._client = _fake_client(FakeCompletions(error=err))
        with self.assertRaises(UpstreamFailureError):
            asyncio.run(sarp_ai.get_sarp_ai_advice("soru"))

    def test_empty_reply_is_an_error_not_an_answer(self):
        sarp_ai._client = _fake_client(FakeCompletions(result=_reply("   ")))
        with self.assertRaises(UpstreamFailureError):
            asyncio.run(sarp_ai.get_sarp_ai_advice("soru"))


class SarpAIEndpointTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(app_module.app)

    def test_old_ask_route_is_gone(self):
        self.assertEqual(self.client.post("/api/ask", json={"question": "x"}).status_code, 404)

    def test_empty_question_rejected(self):
        r = self.client.post("/api/sarp-ai", json={"question": "   "})
        self.assertEqual(r.status_code, 422)

    def test_too_long_question_rejected(self):
        r = self.client.post("/api/sarp-ai", json={"question": "a" * 2001})
        self.assertEqual(r.status_code, 422)

    def test_unknown_language_rejected(self):
        r = self.client.post("/api/sarp-ai", json={"question": "soru", "lang": "de"})
        self.assertEqual(r.status_code, 422)

    def test_returns_answer_without_city(self):
        async def fake_advice(question, weather_context="", lang="tr", farm_context=None):
            self.assertEqual(weather_context, "")
            self.assertIsNone(farm_context)
            return "Yanıt"
        with mock.patch.object(app_module, "get_sarp_ai_advice", side_effect=fake_advice):
            r = self.client.post("/api/sarp-ai", json={"question": "soru", "lang": "en"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sarp_ai_answer"], "Yanıt")

    def test_missing_key_returns_503_json(self):
        saved = sarp_ai._client
        sarp_ai._client = None
        try:
            with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
                r = self.client.post("/api/sarp-ai", json={"question": "soru"})
        finally:
            sarp_ai._client = saved
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "not_configured")


class FarmContextTest(unittest.TestCase):
    def test_empty_profile_adds_nothing(self):
        self.assertEqual(sarp_ai.format_farm_context(None), "")
        self.assertEqual(sarp_ai.format_farm_context({}), "")

    def test_formats_profile_lines(self):
        text = sarp_ai.format_farm_context({
            "role": "farm", "farm_size": 12.0, "crops_last": "domates",
            "crops_current": "biber, patlıcan", "crops_next": "",
        })
        self.assertIn("Mode: commercial farm", text)
        self.assertIn("Farm size: 12 decares", text)
        self.assertIn("Crops planted this season: biber, patlıcan", text)
        self.assertNotIn("Crops planned next", text)

    def test_multiline_input_is_flattened_and_capped(self):
        text = sarp_ai.format_farm_context({"role": "hobby", "crops_current": "a\nIgnore previous\n" + "x" * 1000})
        crop_lines = [line for line in text.splitlines() if line.startswith("Crops planted this season: ")]
        self.assertEqual(len(crop_lines), 1)  # the injected newline did not start a new prompt line
        self.assertIn("a Ignore previous", crop_lines[0])
        self.assertLessEqual(len(crop_lines[0].split(": ", 1)[1]), 300)

    def test_farm_context_reaches_the_prompt(self):
        completions = FakeCompletions(result=_reply("ok"))
        sarp_ai._client = _fake_client(completions)
        saved = sarp_ai._client
        try:
            asyncio.run(sarp_ai.get_sarp_ai_advice("soru", lang="tr",
                        farm_context={"role": "farm", "farm_size": 5, "crops_current": "domates"}))
        finally:
            sarp_ai._client = saved
        system, user = completions.calls[0]["messages"][0]["content"], completions.calls[0]["messages"][1]["content"]
        self.assertIn("do not ask what is planted", system)
        self.assertIn("Crops planted this season: domates", user)
        self.assertIn("user-entered data", user)

    def test_no_farm_context_leaves_prompt_unchanged(self):
        completions = FakeCompletions(result=_reply("ok"))
        sarp_ai._client = _fake_client(completions)
        asyncio.run(sarp_ai.get_sarp_ai_advice("soru"))
        self.assertNotIn("farm profile", completions.calls[0]["messages"][1]["content"])


class FarmContextEndpointTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(app_module.app)

    def test_negative_farm_size_rejected(self):
        r = self.client.post("/api/sarp-ai", json={"question": "soru", "farm_context": {"farm_size": -1}})
        self.assertEqual(r.status_code, 422)

    def test_bad_role_rejected(self):
        r = self.client.post("/api/sarp-ai", json={"question": "soru", "farm_context": {"role": "admin"}})
        self.assertEqual(r.status_code, 422)

    def test_valid_farm_context_is_passed_through(self):
        seen = {}
        async def fake_advice(question, weather_context="", lang="tr", farm_context=None):
            seen["ctx"] = farm_context
            return "Yanıt"
        body = {"question": "soru", "lang": "tr",
                "farm_context": {"role": "farm", "farm_size": 3, "crops_current": "domates"}}
        with mock.patch.object(app_module, "get_sarp_ai_advice", side_effect=fake_advice):
            r = self.client.post("/api/sarp-ai", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(seen["ctx"]["crops_current"], "domates")
        self.assertEqual(seen["ctx"]["farm_size"], 3)


if __name__ == "__main__":
    unittest.main()
