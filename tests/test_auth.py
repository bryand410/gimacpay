"""Authentication: the OAuth 2.0 password grant, caching, and refresh.

The specification declares a single security scheme::

    securitySchemes:
      gimac_pay_auth:
        type: oauth2
        flows:
          password:
            tokenUrl: .../oauth/token

with tokens that ``expires_in`` in 3600 seconds. The client caches, and
refreshes on a 401 rather than trusting its own clock.
"""

from __future__ import annotations

import pytest
from conftest import TOKEN, wallet_to_wallet_payload

from gimacpay import GimacPayAuthError, GimacPayClient, GimacPayConfigError
from gimacpay.client import REFERENCE_SERVER


class TestConfiguration:
    def test_a_client_needs_credentials(self):
        with pytest.raises(GimacPayConfigError, match="client_id"):
            GimacPayClient(
                base_url="https://example.invalid",
                client_id="",
                client_secret="s",
                username="u",
                password="p",
            )

    def test_every_missing_field_is_named(self):
        with pytest.raises(GimacPayConfigError) as excinfo:
            GimacPayClient(
                base_url="https://example.invalid",
                client_id="",
                client_secret="",
                username="u",
                password="",
            )
        message = str(excinfo.value)
        assert "client_id" in message
        assert "client_secret" in message
        assert "password" in message

    def test_the_default_base_url_is_the_specifications_reference_server(self):
        """Which is ``localhost`` -- reachable only inside GIMAC's network."""
        client = GimacPayClient(client_id="i", client_secret="s", username="u", password="p")
        assert client.base_url == REFERENCE_SERVER
        assert client.base_url.endswith("/stdendpointfacade/v1/external")

    def test_a_trailing_slash_is_normalised(self):
        client = GimacPayClient(
            base_url="https://example.invalid/external/",
            client_id="i",
            client_secret="s",
            username="u",
            password="p",
        )
        assert client.base_url == "https://example.invalid/external"
        assert client.token_endpoint == "https://example.invalid/external/oauth/token"


class TestTokenAcquisition:
    def test_authenticate_returns_a_token(self, client, mock):
        assert client.authenticate() == TOKEN
        assert mock.tokens_issued == 1

    def test_the_token_is_cached_across_calls(self, client, mock):
        """Two payments must not mean two token requests."""
        client.send_payment(wallet_to_wallet_payload())
        client.send_payment(wallet_to_wallet_payload(issuertrxref="ORD-2026-0002"))
        assert mock.tokens_issued == 1

    def test_the_bearer_header_is_sent(self, client, mock):
        client.send_payment(wallet_to_wallet_payload())
        _method, _path, _body, headers = mock.last_request()
        assert headers.get("Authorization") == f"Bearer {TOKEN}"

    def test_the_password_grant_fields_are_sent(self, client, mock):
        client.authenticate()
        _method, path, body, headers = mock.requests[0]
        assert path.endswith("/oauth/token")
        assert headers.get("Content-Type") == "application/x-www-form-urlencoded"
        assert body["grant_type"] == "password"
        assert body["username"] == "participant"
        assert body["client_id"] == "client-id"


class TestRefreshOn401:
    def test_a_stale_token_is_refreshed_and_the_call_retried(self, client, mock):
        """The spec's 401 means "No or invalid access token" -- recoverable."""
        mock.script(401, {"error": "Invalid access token", "error_description": "expired"})

        payment = client.send_payment(wallet_to_wallet_payload())

        assert payment.is_accepted
        assert mock.tokens_issued == 2, "should have fetched a second token"

    def test_a_second_401_is_reported_rather_than_retried_forever(self, client, mock):
        mock.script(401, {"error": "Invalid access token", "error_description": "still bad"})
        mock.script(401, {"error": "Invalid access token", "error_description": "still bad"})

        with pytest.raises(GimacPayAuthError) as excinfo:
            client.send_payment(wallet_to_wallet_payload())

        assert excinfo.value.status == 401
        assert mock.tokens_issued == 2, "must not loop"

    def test_bad_credentials_surface_as_an_auth_error(self, client, mock):
        mock.token_returns(401, {"error": "invalid_grant", "error_description": "Bad credentials"})

        with pytest.raises(GimacPayAuthError, match="Bad credentials"):
            client.authenticate()

    def test_a_token_response_without_a_token_is_a_protocol_error(self, client, mock):
        """A 200 with no ``access_token`` is not a successful login."""
        from gimacpay import GimacPayProtocolError

        mock.token_returns(200, {"expires_in": 3600, "token_type": "Bearer"})

        with pytest.raises(GimacPayProtocolError, match="access_token"):
            client.authenticate()

    def test_the_safety_margin_is_applied(self, client, mock):
        """A 3600s token is cached for ~3540s, so it is refreshed before it dies."""
        import time

        mock.token_returns(200, {"access_token": "long", "expires_in": 3600})
        client.authenticate()
        remaining = client._token_expires_at - time.monotonic()
        assert 3530 < remaining <= 3541

    def test_a_very_short_lived_token_is_floored_at_one_second(self, client, mock):
        """The margin can exceed the advertised lifetime.

        A 30s token with a 60s margin would be dead on arrival, so the cached
        lifetime is floored at one second rather than going negative -- which
        would make every call re-authenticate in a loop.
        """
        import time

        mock.token_returns(200, {"access_token": "short", "expires_in": 30})
        client.authenticate()
        remaining = client._token_expires_at - time.monotonic()
        assert 0 < remaining <= 1.1
