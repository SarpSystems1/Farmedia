"""Offline tests: registration, per-country consent rules, login, profile and consent logging.

A fake Supabase (httpx.MockTransport) stands in for the real project, so no network or
credentials are needed. Run from the project root:  python tests/test_accounts.py
"""

import json
import os
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon-test-key"

from fastapi.testclient import TestClient  # noqa: E402

import app as farmedia_app  # noqa: E402
from services import supabase_client as sb  # noqa: E402
from services.i18n import t  # noqa: E402

TR_REGISTRATION_REJECTED = t("tr", "error.registration_rejected")
TR_CONSENT_REQUIRED = t("tr", "error.consent_required")

GOOD_TOKEN = "good-token"
USER_ID = "11111111-2222-3333-4444-555555555555"
PROFILE = {"id": USER_ID, "email": "ayse@example.com", "first_name": "Ayse", "last_name": "Test",
           "role": "hobby", "alert_email_consent": False, "alert_sms_consent": False}
DOCS = {
    "tr": {"terms": {"version": "2026-11-tr", "url": "https://example.com/tr/terms"},
           "privacy": {"version": "2026-11-tr", "url": "https://example.com/tr/privacy"}},
    "en": {"terms": {"version": "2026-11-en", "url": "https://example.com/en/terms"},
           "privacy": {"version": "2026-11-en", "url": "https://example.com/en/privacy"}},
}


class FakeSupabase:
    """Records calls and answers like Supabase Auth + PostgREST would."""

    def __init__(self):
        self.calls = []
        self.signup_exists = False
        self.signup_db_error = False   # Supabase Auth hides the trigger's text behind this 500
        self.docs_published = True
        self.rpc_error = None          # a PostgREST error body, e.g. a DB trigger's RAISE message
        self.rpc_list_error = False    # a 500 whose body is a JSON array, not an object
        self.delete_error = None       # PostgREST error body from delete_own_account

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        path, method = request.url.path, request.method
        auth = request.headers.get("authorization", "")

        if path == "/rest/v1/legal_documents" and method == "GET":
            locale = request.url.params.get("locale", "eq.en").split(".", 1)[1]
            if not self.docs_published:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {"doc_type": d, "version": v["version"], "url": v["url"]}
                for d, v in DOCS[locale].items()])

        if path == "/auth/v1/signup" and method == "POST":
            if self.signup_db_error:
                return httpx.Response(500, json={"code": 500, "error_code": "unexpected_failure",
                                                 "msg": "Database error saving new user"})
            if self.signup_exists:
                return httpx.Response(422, json={"error_code": "user_already_exists",
                                                 "msg": "User already registered"})
            return httpx.Response(200, json={"id": USER_ID, "email": body["email"]})

        if path == "/auth/v1/token" and method == "POST":
            if body.get("password") == "Correct123":
                return httpx.Response(200, json={"access_token": GOOD_TOKEN, "refresh_token": "r",
                                                 "expires_in": 3600, "user": {"id": USER_ID}})
            return httpx.Response(400, json={"error": "invalid_grant",
                                             "error_description": "Invalid login credentials"})

        if path == "/auth/v1/user" and method == "GET":
            if auth == f"Bearer {GOOD_TOKEN}":
                return httpx.Response(200, json={"id": USER_ID, "email": PROFILE["email"]})
            return httpx.Response(401, json={"msg": "invalid JWT"})

        if path == "/rest/v1/profiles":
            if auth != f"Bearer {GOOD_TOKEN}":
                return httpx.Response(401, json={"message": "JWT expired"})
            if method == "GET":
                return httpx.Response(200, json=[PROFILE])
            if method == "PATCH":
                return httpx.Response(200, json=[{**PROFILE, **body}])

        if path == "/rest/v1/rpc/update_profile_with_consents" and method == "POST":
            if auth != f"Bearer {GOOD_TOKEN}":
                return httpx.Response(401, json={"message": "JWT expired"})
            if self.rpc_error:
                return httpx.Response(400, json=self.rpc_error)
            if self.rpc_list_error:
                return httpx.Response(500, json=[{"message": "unexpected"}])
            return httpx.Response(200, json={**PROFILE, **body["p_changes"]})

        if path == "/rest/v1/consent_log" and method == "GET":
            if auth != f"Bearer {GOOD_TOKEN}":
                return httpx.Response(401, json={"message": "JWT expired"})
            return httpx.Response(200, json=[
                {"consent_type": "terms", "granted": True, "version": "2026-11-tr",
                 "recorded_at": "2026-11-01T10:00:00+00:00"},
                {"consent_type": "alert_sms", "granted": True, "version": None,
                 "recorded_at": "2026-11-02T10:00:00+00:00"},
            ])

        if path == "/rest/v1/rpc/delete_own_account" and method == "POST":
            if auth != f"Bearer {GOOD_TOKEN}":
                return httpx.Response(401, json={"message": "JWT expired"})
            if self.delete_error:
                return httpx.Response(400, json=self.delete_error)
            return httpx.Response(204)

        if path == "/rest/v1/consent_log" and method == "POST":
            return httpx.Response(201)

        return httpx.Response(404, json={"message": "not found in fake"})

    def signups(self):
        return [c for c in self.calls if c[1] == "/auth/v1/signup"]


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSupabase()
        sb._transport = httpx.MockTransport(self.fake)
        self.client = TestClient(farmedia_app.app)

    def tearDown(self):
        sb._transport = None

    def body(self, **overrides):
        """A valid Turkish (KVKK) sign-up request; override fields per test."""
        b = {"email": "Ayse@Example.com", "password": "Correct123", "first_name": "Ayse",
             "last_name": "Test", "country": "TR", "locale": "tr",
             "terms_version": "2026-11-tr", "privacy_version": "2026-11-tr",
             "terms_accepted": True, "privacy_accepted": True,
             "kvkk_explicit": True, "kvkk_transfer": True,
             "alert_email": True, "alert_sms": False, "marketing_email": False, "do_not_sell": False}
        b.update(overrides)
        return b

    def register(self, **overrides):
        return self.client.post("/api/auth/register", json=self.body(**overrides))

    # --- Turkey (KVKK) ------------------------------------------------------

    def test_turkey_requires_kvkk_explicit_consent(self):
        r = self.register(kvkk_explicit=False)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "consent_required")
        self.assertEqual(self.fake.signups(), [])

    def test_turkey_requires_transfer_consent(self):
        r = self.register(kvkk_transfer=False)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.fake.signups(), [])

    def test_turkey_registration_sends_full_consent_metadata(self):
        r = self.register()
        self.assertEqual(r.status_code, 201, r.text)
        sent = self.fake.signups()[0][2]
        self.assertEqual(sent["email"], "ayse@example.com")
        meta = sent["data"]
        self.assertEqual(meta["country"], "TR")
        self.assertTrue(meta["terms_accepted"] and meta["privacy_accepted"])
        self.assertEqual(meta["terms_version"], "2026-11-tr")
        self.assertTrue(meta["kvkk_explicit"] and meta["kvkk_transfer"])
        self.assertTrue(meta["alert_email"])
        self.assertFalse(meta["alert_sms"] or meta["marketing_email"] or meta["do_not_sell"])
        self.assertNotIn("Correct123", r.text)
        self.assertEqual(r.json()["jurisdiction"], "kvkk")

    # --- Versions and terms -------------------------------------------------

    def test_outdated_document_version_is_rejected(self):
        r = self.register(terms_version="2025-01-tr")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.fake.signups(), [])

    def test_no_published_documents_blocks_registration(self):
        self.fake.docs_published = False
        r = self.register()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "not_configured")
        self.assertEqual(self.fake.signups(), [])

    def test_english_locale_uses_english_versions(self):
        r = self.register(locale="en", terms_version="2026-11-en", privacy_version="2026-11-en")
        self.assertEqual(r.status_code, 201, r.text)

    # --- International (GDPR / CCPA / other) --------------------------------

    def test_gdpr_country_does_not_need_kvkk_flags(self):
        r = self.register(country="DE", locale="en", terms_version="2026-11-en",
                          privacy_version="2026-11-en", kvkk_explicit=False, kvkk_transfer=False)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["jurisdiction"], "gdpr")

    def test_us_user_can_opt_out_of_sale_at_signup(self):
        r = self.register(country="US", locale="en", terms_version="2026-11-en",
                          privacy_version="2026-11-en", kvkk_explicit=False, kvkk_transfer=False,
                          do_not_sell=True)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(self.fake.signups()[0][2]["data"]["do_not_sell"])
        self.assertEqual(r.json()["jurisdiction"], "ccpa")

    def test_other_country_is_global(self):
        r = self.register(country="JP", locale="en", terms_version="2026-11-en",
                          privacy_version="2026-11-en", kvkk_explicit=False, kvkk_transfer=False)
        self.assertEqual(r.json()["jurisdiction"], "global")

    def test_marketing_is_off_unless_chosen(self):
        self.register(country="US", locale="en", terms_version="2026-11-en",
                      privacy_version="2026-11-en", kvkk_explicit=False, kvkk_transfer=False)
        self.assertFalse(self.fake.signups()[0][2]["data"]["marketing_email"])

    def test_terms_and_privacy_must_be_ticked(self):
        r = self.register(terms_accepted=False)
        self.assertEqual(r.status_code, 422)
        r = self.register(privacy_accepted=False)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.fake.signups(), [])

    def test_bad_country_code_is_rejected(self):
        r = self.register(country="Turkey")
        self.assertEqual(r.status_code, 422)

    # --- requirements endpoint ---------------------------------------------

    def test_requirements_for_turkey(self):
        r = self.client.get("/api/legal/requirements", params={"country": "TR", "locale": "tr"})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["jurisdiction"], "kvkk")
        self.assertIn("kvkk_explicit", data["required_consents"])
        self.assertTrue(data["ready"])
        self.assertEqual(data["documents"]["terms"]["version"], "2026-11-tr")

    def test_requirements_for_us_offers_do_not_sell(self):
        r = self.client.get("/api/legal/requirements", params={"country": "US", "locale": "en"})
        data = r.json()
        self.assertEqual(data["jurisdiction"], "ccpa")
        self.assertIn("do_not_sell", data["optional_consents"])
        self.assertNotIn("kvkk_explicit", data["required_consents"])

    def test_requirements_unknown_locale_falls_back_to_english(self):
        r = self.client.get("/api/legal/requirements", params={"country": "US", "locale": "de"})
        self.assertEqual(r.json()["locale"], "en")

    # --- duplicate / login --------------------------------------------------

    def test_duplicate_email_does_not_reveal_existing_account(self):
        self.fake.signup_exists = True
        r = self.register()
        self.assertEqual(r.status_code, 201, r.text)
        self.assertNotIn("already", r.text.lower())
        self.assertTrue(r.json()["confirmation_required"])
        self.assertIsNone(r.json()["user"])

    def test_signup_db_rejection_is_reported_as_rule_violation(self):
        self.fake.signup_db_error = True
        r = self.register()
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "rule_violation")
        self.assertEqual(r.json()["error"]["message"], TR_REGISTRATION_REJECTED)

    def test_non_boolean_consent_at_signup_is_rejected(self):
        for bad in ("false", 0, 1, "yes", None):
            r = self.register(kvkk_explicit=bad)
            self.assertEqual(r.status_code, 422, f"accepted {bad!r}")
        self.assertEqual(self.fake.signups(), [])

    def test_login_success_returns_tokens(self):
        r = self.client.post("/api/auth/login", json={"email": "ayse@example.com", "password": "Correct123"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["session"]["access_token"], GOOD_TOKEN)

    def test_login_failure_is_generic(self):
        r = self.client.post("/api/auth/login", json={"email": "ayse@example.com", "password": "Wrong123"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "auth_failed")
        self.assertNotIn("Invalid login credentials", r.text)

    # --- authenticated access and profile ----------------------------------

    def test_me_requires_bearer_token(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": "Basic x"}).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": "Bearer bad"}).status_code, 401)

    def test_me_returns_user_and_profile(self):
        r = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {GOOD_TOKEN}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["profile"]["first_name"], "Ayse")

    def test_profile_patch_uses_user_token(self):
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"first_name": "Zeynep", "farm_size": 12})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["profile"]["first_name"], "Zeynep")
        self.assertNotIn("service", json.dumps(self.fake.calls).lower())

    def test_profile_patch_drops_protected_fields(self):
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"country": "US", "jurisdiction": "global", "email": "x@x.com",
                                    "first_name": "A"})
        self.assertEqual(r.status_code, 200, r.text)
        sent = [c[2] for c in self.fake.calls if c[1] == "/rest/v1/rpc/update_profile_with_consents"][0]
        self.assertEqual(set(sent["p_changes"]), {"first_name"})

    def rpc_calls(self):
        return [c[2] for c in self.fake.calls if c[1] == "/rest/v1/rpc/update_profile_with_consents"]

    def test_profile_update_is_one_atomic_rpc(self):
        # Profile write and consent log go through a single SQL function call, so there is no
        # separate PATCH or consent_log POST that could succeed on one and fail on the other.
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"alert_sms_consent": True, "first_name": "Zeynep"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.rpc_calls()), 1)
        self.assertEqual(self.rpc_calls()[0]["p_changes"],
                         {"alert_sms_consent": True, "first_name": "Zeynep"})
        self.assertFalse([c for c in self.fake.calls
                          if c[1] in ("/rest/v1/consent_log", "/rest/v1/profiles") and c[0] != "GET"])

    def test_do_not_sell_change_is_sent_as_consent(self):
        self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                          json={"do_not_sell": True})
        self.assertIs(self.rpc_calls()[0]["p_changes"]["do_not_sell"], True)

    def test_profile_consent_must_be_strict_boolean(self):
        for bad in ("false", 0, 1, "yes", None):
            r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                                  json={"alert_sms_consent": bad})
            self.assertEqual(r.status_code, 422, f"accepted {bad!r}")
        self.assertEqual(self.rpc_calls(), [])

    def test_db_trigger_message_reaches_the_user(self):
        self.fake.rpc_error = {"code": "P0001", "message": "KVKK explicit consent and cross-border transfer consent are required in Turkey", "hint": None}
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"first_name": "Zeynep"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "rule_violation")
        self.assertEqual(r.json()["error"]["message"], TR_CONSENT_REQUIRED)
        self.assertIn("KVKK explicit consent", r.json()["error"]["detail"])

    def test_unknown_db_message_is_still_passed_through_as_detail(self):
        self.fake.rpc_error = {"code": "P0001", "message": "Protected profile field cannot be changed"}
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"first_name": "Zeynep"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["message"], t("tr", "error.protected_field"))
        self.assertEqual(r.json()["error"]["detail"], "Protected profile field cannot be changed")

    def test_non_rule_database_error_is_still_upstream_failure(self):
        # A PostgREST error without the RAISE code (e.g. a constraint violation) must not leak as a rule message.
        self.fake.rpc_error = {"code": "23514", "message": "new row violates check constraint"}
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"first_name": "Zeynep"})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["error"]["code"], "upstream_failure")

    def test_array_error_body_does_not_crash(self):
        self.fake.rpc_list_error = True
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"first_name": "Zeynep"})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["error"]["code"], "upstream_failure")

    def test_error_text_handles_list_bodies(self):
        self.assertIn("boom", sb._error_text(httpx.Response(400, json=[{"message": "boom"}])))
        self.assertEqual(sb._error_text(httpx.Response(400, json=["plain"])).strip(), "")
        self.assertEqual(sb._error_text(httpx.Response(400, text="not json")).strip(), "")
        self.assertEqual(sb._error_payload(httpx.Response(400, json=[1, 2])), {})

    def test_profile_patch_rejects_bad_role(self):
        r = self.client.patch("/api/profile", headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
                              json={"role": "admin"})
        self.assertEqual(r.status_code, 422)

    # --- configuration ------------------------------------------------------

    def test_missing_configuration_returns_503(self):
        saved = os.environ.pop("SUPABASE_URL")
        try:
            r = self.client.post("/api/auth/login", json={"email": "a@b.co", "password": "x"})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "not_configured")
        finally:
            os.environ["SUPABASE_URL"] = saved


class NoContentTest(unittest.TestCase):
    """rest() must treat 204 No Content as success (used by DELETE endpoints)."""

    def setUp(self):
        self.seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.seen.append((request.method, request.url.path))
            return httpx.Response(204)

        sb._transport = httpx.MockTransport(handler)

    def tearDown(self):
        sb._transport = None

    def test_204_returns_empty_list(self):
        import asyncio
        rows = asyncio.run(sb.rest("DELETE", "profiles", "tok", params={"id": "eq.x"}))
        self.assertEqual(rows, [])
        self.assertEqual(self.seen, [("DELETE", "/rest/v1/profiles")])

    def test_rpc_204_returns_none(self):
        import asyncio
        self.assertIsNone(asyncio.run(sb.rpc("some_fn", "tok", {})))


class DataRightsTest(unittest.TestCase):
    """Export (portability) and deletion (right to erasure) endpoints."""

    AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}

    def setUp(self):
        self.fake = FakeSupabase()
        sb._transport = httpx.MockTransport(self.fake)
        self.client = TestClient(farmedia_app.app)

    def tearDown(self):
        sb._transport = None

    def delete(self, body=None, headers=None):
        return self.client.request("DELETE", "/api/account", json=body, headers=headers or {})

    def delete_calls(self):
        return [c for c in self.fake.calls if c[1] == "/rest/v1/rpc/delete_own_account"]

    # --- export ---

    def test_export_requires_bearer_token(self):
        self.assertEqual(self.client.get("/api/profile/export").status_code, 401)
        self.assertEqual(self.client.get("/api/profile/export",
                                         headers={"Authorization": "Bearer bad"}).status_code, 401)

    def test_export_contains_profile_and_consent_history(self):
        r = self.client.get("/api/profile/export", headers=self.AUTH)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["format"], "farmedia-export")
        self.assertEqual(data["account"]["email"], "ayse@example.com")
        self.assertEqual(data["profile"]["first_name"], "Ayse")
        self.assertEqual([c["consent_type"] for c in data["consent_history"]], ["terms", "alert_sms"])
        self.assertIn("exported_at", data)

    def test_export_is_a_download_and_not_cached(self):
        r = self.client.get("/api/profile/export", headers=self.AUTH)
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_export_reads_consent_history_with_user_token(self):
        self.client.get("/api/profile/export", headers=self.AUTH)
        consent_reads = [c for c in self.fake.calls if c[1] == "/rest/v1/consent_log"]
        self.assertEqual(len(consent_reads), 1)

    # --- deletion ---

    def test_delete_requires_password_in_body(self):
        self.assertEqual(self.delete(body={}, headers=self.AUTH).status_code, 422)
        self.assertEqual(self.delete(body={"password": ""}, headers=self.AUTH).status_code, 422)
        self.assertEqual(self.delete_calls(), [])

    def test_delete_requires_bearer_token(self):
        r = self.delete(body={"password": "Correct123"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.delete_calls(), [])

    def test_delete_with_bad_token_is_rejected(self):
        r = self.delete(body={"password": "Correct123"}, headers={"Authorization": "Bearer bad"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.delete_calls(), [])

    def test_delete_with_wrong_password_deletes_nothing(self):
        r = self.delete(body={"password": "Wrong123"}, headers=self.AUTH)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "auth_failed")
        self.assertEqual(self.delete_calls(), [])

    def test_delete_with_correct_password_runs_atomic_deletion(self):
        r = self.delete(body={"password": "Correct123"}, headers=self.AUTH)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(r.content, b"")
        calls = self.delete_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], {})

    def test_delete_failure_is_reported_not_hidden(self):
        self.fake.delete_error = {"code": "P0001", "message": "Sign in required"}
        r = self.delete(body={"password": "Correct123"}, headers=self.AUTH)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["detail"], "Sign in required")


if __name__ == "__main__":
    unittest.main()
