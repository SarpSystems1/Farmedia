"""Offline tests for the email/password auth flow: password rule, preference checks, Supabase error
mapping, refresh and logout. Supabase is replaced with an httpx MockTransport, so nothing is sent."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import app as app_module
from services import accounts
from services import supabase_client as sb
from services.errors import AuthenticationError, EmailNotConfirmedError, InvalidInputError, UpstreamFailureError

ENV = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "anon-test-key"}


def _run(coro):
    return asyncio.run(coro)


class MockSupabase:
    """Routes keyed by (method, path). Each handler gets the request and returns an httpx.Response."""

    def __init__(self, routes):
        self.routes = routes
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"message": "no route in test"})
        return handler(request)


class _Base(unittest.TestCase):
    def install(self, routes):
        self.mock = MockSupabase(routes)
        self._saved = sb._transport
        sb._transport = httpx.MockTransport(self.mock)
        self._env = mock.patch.dict(os.environ, ENV)
        self._env.start()

    def tearDown(self):
        if hasattr(self, "_env"):
            self._env.stop()
        sb._transport = getattr(self, "_saved", None)


class PasswordRuleTest(unittest.TestCase):
    def test_six_characters_is_enough(self):
        accounts.validate_password("abcdef")

    def test_letters_only_or_digits_only_are_accepted(self):
        accounts.validate_password("abcdefg")
        accounts.validate_password("123456")

    def test_five_characters_rejected(self):
        with self.assertRaises(InvalidInputError):
            accounts.validate_password("abcde")

    def test_over_128_rejected(self):
        with self.assertRaises(InvalidInputError):
            accounts.validate_password("a" * 129)

    def test_api_rejects_short_password_at_signup(self):
        client = TestClient(app_module.app)
        body = {"email": "a@example.com", "password": "abcde", "first_name": "A", "last_name": "B",
                "country": "TR", "terms_version": "v1", "privacy_version": "v1", "terms_accepted": True,
                "privacy_accepted": True, "kvkk_explicit": True, "kvkk_transfer": True}
        self.assertEqual(client.post("/api/auth/register", json=body).status_code, 422)


class PreferencesTest(unittest.TestCase):
    def test_valid_preferences_pass_and_unknown_keys_are_dropped(self):
        clean = accounts._checked_preferences({"theme": "dark", "density": "compact", "forecastDays": 5,
                                               "lang": "tr", "evil": "<script>"})
        self.assertEqual(clean, {"theme": "dark", "density": "compact", "forecastDays": 5})

    def test_bad_theme_rejected(self):
        with self.assertRaises(InvalidInputError):
            accounts._checked_preferences({"theme": "neon"})

    def test_forecast_days_must_be_an_allowed_integer(self):
        with self.assertRaises(InvalidInputError):
            accounts._checked_preferences({"forecastDays": 4})
        with self.assertRaises(InvalidInputError):
            accounts._checked_preferences({"forecastDays": True})

    def test_list_value_rejected_without_crashing(self):
        with self.assertRaises(InvalidInputError):
            accounts._checked_preferences({"theme": ["dark"]})

    def test_preferences_must_be_an_object(self):
        with self.assertRaises(InvalidInputError):
            accounts._checked_preferences(["dark"])

    def test_preferences_are_accepted_as_a_profile_field(self):
        with mock.patch.object(accounts.sb, "rpc", mock.AsyncMock(return_value={"id": "x"})) as rpc:
            _run(accounts.update_profile("tok", {"preferences": {"theme": "light"}}))
        self.assertEqual(rpc.await_args.args[2], {"p_changes": {"preferences": {"theme": "light"}}})


class SupabaseErrorMappingTest(_Base):
    def test_unconfirmed_email_gets_its_own_error(self):
        self.install({("POST", "/auth/v1/token"): lambda r: httpx.Response(
            400, json={"error_code": "email_not_confirmed", "msg": "Email not confirmed"})})
        with self.assertRaises(EmailNotConfirmedError) as ctx:
            _run(sb.auth_password_login("a@example.com", "abcdef"))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_wrong_password_is_the_generic_error(self):
        self.install({("POST", "/auth/v1/token"): lambda r: httpx.Response(
            400, json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"})})
        with self.assertRaises(AuthenticationError):
            _run(sb.auth_password_login("a@example.com", "wrong"))

    def test_missing_table_grant_is_a_server_error_not_a_bad_password(self):
        self.install({("GET", "/rest/v1/legal_documents"): lambda r: httpx.Response(
            401, json={"code": "42501", "message": "permission denied for table legal_documents"})})
        with self.assertRaises(UpstreamFailureError) as ctx:
            _run(sb.rest("GET", "legal_documents", "anon-test-key", params={"select": "*"}))
        self.assertNotIsInstance(ctx.exception, AuthenticationError)
        self.assertIn("grants", ctx.exception.detail)

    def test_expired_session_on_rest_is_authentication_error(self):
        self.install({("GET", "/rest/v1/profiles"): lambda r: httpx.Response(
            401, json={"message": "JWT expired"})})
        with self.assertRaises(AuthenticationError):
            _run(sb.rest("GET", "profiles", "old-token", params={"select": "*"}))


class RefreshAndLogoutTest(_Base):
    def test_refresh_returns_a_rotated_session(self):
        seen = {}

        def refresh(request):
            seen["body"] = json.loads(request.content)
            seen["grant"] = request.url.params.get("grant_type")
            return httpx.Response(200, json={"access_token": "new-a", "refresh_token": "new-r",
                                             "expires_in": 3600, "user": {"id": "u1"}})
        self.install({("POST", "/auth/v1/token"): refresh})
        out = _run(accounts.refresh_session("old-r"))
        self.assertEqual(seen["grant"], "refresh_token")
        self.assertEqual(seen["body"], {"refresh_token": "old-r"})
        self.assertEqual(out["session"]["refresh_token"], "new-r")

    def test_refresh_with_rejected_token(self):
        self.install({("POST", "/auth/v1/token"): lambda r: httpx.Response(400, json={"msg": "bad"})})
        with self.assertRaises(AuthenticationError):
            _run(accounts.refresh_session("revoked"))

    def test_refresh_rejects_empty_or_huge_token_without_calling_supabase(self):
        self.install({})
        with self.assertRaises(AuthenticationError):
            _run(accounts.refresh_session(""))
        with self.assertRaises(AuthenticationError):
            _run(accounts.refresh_session("x" * 600))
        self.assertEqual(self.mock.seen, [])

    def test_logout_revokes_only_this_device(self):
        self.install({("POST", "/auth/v1/logout"): lambda r: httpx.Response(204)})
        _run(accounts.logout("tok"))
        request = self.mock.seen[-1]
        self.assertEqual(request.url.params.get("scope"), "local")

    def test_logout_survives_supabase_being_unreachable(self):
        def boom(request):
            raise httpx.ConnectError("down", request=request)
        self.install({("POST", "/auth/v1/logout"): boom})
        _run(accounts.logout("tok"))  # must not raise


class AuthRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_logout_needs_a_bearer_token(self):
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 401)

    def test_refresh_needs_a_token(self):
        self.assertEqual(self.client.post("/api/auth/refresh", json={"refresh_token": ""}).status_code, 422)

    def test_refresh_route_returns_session(self):
        async def fake(refresh_token):
            return {"session": {"access_token": "a", "refresh_token": "r2", "expires_in": 3600,
                                "token_type": "bearer"}, "user": {}}
        with mock.patch.object(app_module.accounts, "refresh_session", side_effect=fake):
            r = self.client.post("/api/auth/refresh", json={"refresh_token": "r1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["session"]["refresh_token"], "r2")


if __name__ == "__main__":
    unittest.main()
