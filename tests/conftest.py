"""Test fixtures: a real HTTP server standing in for GIMACPay.

There is no public sandbox -- the specification's own ``servers`` block points
at ``localhost:8005``, inside GIMAC's network. So the tests run against a local
server that speaks the same protocol, which has the advantage of exercising the
actual :mod:`urllib` transport rather than mocking it away.

The mock is deliberately scriptable: :meth:`MockGimac.script` queues the next
response, so a test can make the server answer 418 or drop the connection and
assert what the client does about it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import pytest

from gimacpay import GimacPayClient

TOKEN = "test-access-token"
REFRESHED_TOKEN = "test-access-token-refreshed"

# A payment object in the shape of the specification's Payment schema.
PAYMENT_PENDING: dict[str, Any] = {
    "issuertrxref": "ORD-2026-0001",
    "acquirertrxref": "CI20261010.1030.ADFDF",
    "state": "PENDING",
    "intent": "mobile_transfer",
    "amount": 500,
    "currency": "950",
    "tomember": "22001",
    "frommember": "12001",
    "description": "Test transfer",
    "createtime": "1760000000",
}

PAYMENT_ACCEPTED: dict[str, Any] = {**PAYMENT_PENDING, "state": "ACCEPTED"}
PAYMENT_REJECTED: dict[str, Any] = {
    **PAYMENT_PENDING,
    "state": "REJECTED",
    "rejectmessage": "Wallet<2356789009> Not Found",
}


class MockGimac:
    """A scriptable stand-in for the GIMACPay participant API."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self._script: list[tuple[int, Any]] = []
        self._inquiry_results: list[dict[str, Any]] = []
        self._default_send: tuple[int, Any] = (200, PAYMENT_ACCEPTED)
        self._tokens_issued = 0
        self._token_script: tuple[int, Any] | None = None
        self._fail_next_with: BaseException | None = None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        # Do not wait for handler threads on shutdown; with one server per test
        # the default behaviour dominates the suite's runtime.
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    # -- lifecycle ------------------------------------------------------ #

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/stdendpointfacade/v1/external"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def reset(self) -> None:
        """Return the server to a clean state between tests.

        The server is session-scoped so the suite does not pay for a socket
        bind per test; state is cleared here instead.
        """
        self.requests.clear()
        self._script.clear()
        self._inquiry_results = []
        self._default_send = (200, PAYMENT_ACCEPTED)
        self._tokens_issued = 0
        self._token_script = None
        self._fail_next_with = None

    # -- scripting ------------------------------------------------------ #

    def script(self, status: int, body: Any) -> None:
        """Queue the next response. Consumed one per non-token request."""
        self._script.append((status, body))

    def send_returns(self, status: int, body: Any) -> None:
        """Set the standing response for ``/payment/send``."""
        self._default_send = (status, body)

    def token_returns(self, status: int, body: Any) -> None:
        """Make the next call to ``/oauth/token`` answer with *status* and *body*.

        The token endpoint is handled before the general script queue, so
        without this there is no way to simulate bad credentials.
        """
        self._token_script = (status, body)

    def inquiry_returns(self, *payments: dict[str, Any]) -> None:
        """Set what ``/payment/inquiry`` returns."""
        self._inquiry_results = list(payments)

    def fail_next_with(self, exc: BaseException) -> None:
        """Raise *exc* from the next non-token request, to simulate a dropped link."""
        self._fail_next_with = exc

    @property
    def tokens_issued(self) -> int:
        return self._tokens_issued

    def last_request(self) -> tuple[str, str, dict[str, Any], dict[str, str]]:
        return self.requests[-1]

    # -- handler -------------------------------------------------------- #

    def _handler(self) -> type:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence the test output
                pass

            def do_POST(self) -> None:  # noqa: N802 - stdlib naming
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                content_type = self.headers.get("Content-Type", "")

                if "application/x-www-form-urlencoded" in content_type:
                    # The OAuth 2.0 password grant is form-encoded, per RFC 6749.
                    parsed = parse_qs(raw.decode("utf-8"))
                    body: Any = {key: values[0] for key, values in parsed.items()}
                else:
                    try:
                        body = json.loads(raw.decode("utf-8")) if raw else {}
                    except json.JSONDecodeError:
                        body = {"__raw__": raw.decode("utf-8", "replace")}

                path = self.path
                if path.endswith("/oauth/token"):
                    mock._tokens_issued += 1
                    mock.requests.append(("POST", path, body, dict(self.headers)))
                    if mock._token_script is not None:
                        status, payload = mock._token_script
                        mock._token_script = None
                        self._reply(status, payload)
                        return
                    self._reply(
                        200,
                        {
                            "access_token": TOKEN if mock._tokens_issued == 1 else REFRESHED_TOKEN,
                            "expires_in": 3600,
                            "token_type": "Bearer",
                            "scope": "read:payment",
                        },
                    )
                    return

                mock.requests.append(("POST", path, body, dict(self.headers)))

                if mock._fail_next_with is not None:
                    exc = mock._fail_next_with
                    mock._fail_next_with = None
                    # Close without answering: the client sees a transport error.
                    self.close_connection = True
                    raise exc

                if mock._script:
                    status, payload = mock._script.pop(0)
                    self._reply(status, payload)
                    return

                if path.endswith("/payment/inquiry"):
                    self._reply(200, mock._inquiry_results)
                    return

                if path.endswith("/payment/update"):
                    self._reply(200, {"error": "0", "error_description": "updated"})
                    return

                if path.endswith("/payment/send"):
                    status, payload = mock._default_send
                    self._reply(status, payload)
                    return

                self._reply(404, {"error": "404", "error_description": "unknown path"})

            def _reply(self, status: int, payload: Any) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler


@pytest.fixture(scope="session")
def _mock_server() -> MockGimac:
    server = MockGimac()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def mock(_mock_server: MockGimac) -> MockGimac:
    _mock_server.reset()
    return _mock_server


@pytest.fixture
def client(mock: MockGimac) -> GimacPayClient:
    return GimacPayClient(
        base_url=mock.base_url,
        client_id="client-id",
        client_secret="client-secret",
        username="participant",
        password="secret",
        default_dial_code="237",
        timeout=5.0,
    )


def wallet_to_wallet_payload(**overrides: Any) -> dict[str, Any]:
    """The specification's ``WalletToWalletRequestExample``, with overrides."""
    payload = {
        "intent": "mobile_transfer",
        "amount": 500,
        "currency": "950",
        "issuertrxref": "ORD-2026-0001",
        "walletsource": "2356789009",
        "walletdestination": "237699947943",
        "tomember": "22001",
        "description": "John Doe refund",
    }
    payload.update(overrides)
    return payload
