"""Qualification controls for public OAuth observations, without native claims."""

import json
import threading
import unittest
import urllib.parse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import codex_conformance_adapter as adapter


class _RpcClient:
    def __init__(
        self,
        response: dict[str, object],
        completion: dict[str, object] | None = None,
    ) -> None:
        self.response = response
        self.completion = completion
        self.events: list[object] = []
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.waits: list[str] = []

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.requests.append((method, params))
        return self.response

    def wait_for_notification(
        self, method: str, *, predicate: object, after_event_index: int
    ) -> dict[str, object]:
        if self.completion is None:
            raise AssertionError("login RPC rejection must not wait for a callback")
        if not callable(predicate) or not predicate(self.completion["params"]):
            raise AssertionError("completion must match this server")
        if after_event_index != len(self.events):
            raise AssertionError("completion must use this attempt's event cursor")
        self.waits.append(method)
        return self.completion


def _rpc_failure(message: str) -> _RpcClient:
    return _RpcClient(
        {"id": 1, "error": {"code": -32603, "message": message, "data": None}}
    )


@contextmanager
def _callback_client(
    *, success: bool, error: str | None = None
) -> Iterator[tuple[_RpcClient, list[str]]]:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            requests.append(parsed.path)
            if parsed.path == "/authorize":
                query = urllib.parse.parse_qs(parsed.query)
                callback = query["redirect_uri"][0]
                parameters = urllib.parse.urlencode(
                    {"code": "fixture-code", "state": query["state"][0]}
                )
                self.send_response(302)
                self.send_header("Location", f"{callback}?{parameters}")
            elif parsed.path == "/callback":
                self.send_response(200)
            else:
                self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        worker.start()
        port = server.server_address[1]
        query = urllib.parse.urlencode(
            {
                "redirect_uri": f"http://127.0.0.1:{port}/callback",
                "state": "fixture-state",
            }
        )
        client = _RpcClient(
            {
                "id": 1,
                "result": {
                    "authorizationUrl": f"http://127.0.0.1:{port}/authorize?{query}"
                },
            },
            {
                "method": adapter.AUTH_COMPLETION_METHOD,
                "params": {
                    "name": adapter.TEST_SERVER_NAME,
                    "threadId": None,
                    "success": success,
                    "error": error,
                },
            },
        )
        try:
            yield client, requests
        finally:
            server.shutdown()
            worker.join(timeout=2)
            if worker.is_alive():
                raise AssertionError("owned HTTP fixture did not shut down")


class AuthRejectionQualificationTests(unittest.TestCase):
    def exercise(self, client: _RpcClient, scenario: str) -> str:
        return adapter._exercise_auth_scenario(
            client,
            scenario=scenario,
            workspace=Path("."),
            timeout_seconds=2,
        )

    def test_rpc_errors_cannot_qualify_expected_rejections(self) -> None:
        for scenario in sorted(adapter.EXPECTED_AUTH_REJECTION_SCENARIOS):
            for diagnostic in (
                "HTTP destination is outside the configured address capability",
                "TransportClosed",
                "Authorization server issuer mismatch: expected A, received B",
            ):
                with self.subTest(scenario=scenario, diagnostic=diagnostic):
                    client = _rpc_failure(diagnostic)
                    with self.assertRaises(adapter.AdapterFailure) as raised:
                        self.exercise(client, scenario)
                    self.assertIn(
                        "OAuth rejection is unqualified", str(raised.exception)
                    )
                    self.assertIn("login_request", str(raised.exception))
                    self.assertEqual(client.waits, [])
                    self.assertEqual(
                        client.requests,
                        [
                            (
                                "mcpServer/oauth/login",
                                {"name": adapter.TEST_SERVER_NAME, "timeoutSecs": 2},
                            )
                        ],
                    )

    def test_callback_failure_does_not_prove_a_semantic_rejection(self) -> None:
        for scenario in sorted(adapter.EXPECTED_AUTH_REJECTION_SCENARIOS):
            with self.subTest(scenario=scenario):
                with _callback_client(success=False, error="TransportClosed") as (
                    client,
                    requests,
                ):
                    with self.assertRaises(adapter.AdapterFailure) as raised:
                        self.exercise(client, scenario)
                    self.assertIn(
                        "OAuth rejection is unqualified", str(raised.exception)
                    )
                    self.assertIn("callback_completion", str(raised.exception))
                    self.assertEqual(requests, ["/authorize", "/callback"])
                    self.assertEqual(client.waits, [adapter.AUTH_COMPLETION_METHOD])

    def test_unexpected_success_still_fails(self) -> None:
        for scenario in sorted(adapter.EXPECTED_AUTH_REJECTION_SCENARIOS):
            with self.subTest(scenario=scenario):
                with _callback_client(success=True) as (client, requests):
                    with self.assertRaisesRegex(
                        adapter.AdapterFailure, "unexpectedly accepted"
                    ):
                        self.exercise(client, scenario)
                    self.assertEqual(requests, ["/authorize", "/callback"])

    def test_ordinary_login_success_preserves_existing_result(self) -> None:
        with _callback_client(success=True) as (client, requests):
            self.assertEqual(
                adapter._oauth_login(
                    client, scopes=None, timeout_seconds=2, client_registration="dcr"
                ),
                (True, None),
            )
            self.assertEqual(requests, ["/authorize", "/callback"])
            self.assertEqual(
                client.requests,
                [
                    (
                        "mcpServer/oauth/login",
                        {
                            "name": adapter.TEST_SERVER_NAME,
                            "timeoutSecs": 2,
                            "clientRegistration": "dcr",
                        },
                    )
                ],
            )

    def test_ordinary_rpc_failure_preserves_existing_result(self) -> None:
        client = _rpc_failure("transport closed")
        success, error = adapter._oauth_login(client, scopes=None, timeout_seconds=2)
        self.assertFalse(success)
        self.assertEqual(
            json.loads(error),
            {"code": -32603, "message": "transport closed", "data": None},
        )
        self.assertEqual(client.waits, [])

    def test_ordinary_callback_failure_preserves_existing_result(self) -> None:
        with _callback_client(success=False, error="transport closed") as (
            client,
            requests,
        ):
            self.assertEqual(
                adapter._oauth_login(client, scopes=None, timeout_seconds=2),
                (False, "transport closed"),
            )
            self.assertEqual(requests, ["/authorize", "/callback"])

    def test_observed_stages_are_separate_from_qualification(self) -> None:
        first = adapter._observe_oauth_login(
            _rpc_failure("closed"), scopes=None, timeout_seconds=2
        )
        self.assertEqual(
            first,
            adapter._OAuthLoginObservation(
                False,
                json.dumps(
                    {"code": -32603, "message": "closed", "data": None}, sort_keys=True
                ),
                "login_request",
            ),
        )
        with _callback_client(success=False, error="closed") as (client, requests):
            second = adapter._observe_oauth_login(
                client, scopes=None, timeout_seconds=2
            )
            self.assertEqual(
                second,
                adapter._OAuthLoginObservation(False, "closed", "callback_completion"),
            )
            self.assertEqual(requests, ["/authorize", "/callback"])


if __name__ == "__main__":
    unittest.main()
