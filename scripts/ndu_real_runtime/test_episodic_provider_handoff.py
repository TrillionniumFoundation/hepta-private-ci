"""Actual localhost HTTP controls; these servers are not model executions."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from .episodic_provider_handoff import HandoffProfile, handoff


class RecordingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), RecordingHandler)
        self.calls = []
        self.behavior = "normal"
        self.body = b'{"fixture":"transport only"}'
        self.response_status = 200


class RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.calls.append((self.path, dict(self.headers), body))
        if self.server.behavior == "disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.server.behavior == "redirect":
            self.send_response(307)
            self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        if self.server.behavior == "truncated":
            self.send_header("Content-Length", str(len(self.server.body) + 10))
        else:
            self.send_header("Content-Length", str(len(self.server.body)))
        if self.server.behavior == "ambiguous":
            self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        try:
            self.wfile.write(self.server.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class ProviderHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.launch = self.root / "launch"
        self.launch.mkdir()
        self.journal = self.root / "journal"
        self.server = RecordingServer()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        def close_server():
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=2)

        self.addCleanup(close_server)
        self.endpoint = (
            "http://127.0.0.1:" + str(self.server.server_port) + "/v1/responses"
        )
        self.request = (
            b'{ "model": "fixture-model", "input": "public task C", '
            b'"store": false, "max_output_tokens": 16, "temperature": 0 }\n'
        )
        self.launch_receipt = {
            "schema": "hepta.mem9.isolated-launch.v1",
            "mode": "off",
            "session_id": "fresh-c-off",
            "status": "EXECUTED",
            "returncode": 0,
            "capture_truncated": False,
            "source_unchanged": True,
            "launcher_sha256": "1" * 64,
            "actor_sha256": "2" * 64,
            "bootstrap": {"bootstrap": "synthetic-transport-only"},
        }
        self.write_launch()

    def profile(self, **changes):
        values = {
            "endpoint": self.endpoint,
            "model": "fixture-model",
            "launcher_sha256": "1" * 64,
            "actor_sha256": "2" * 64,
            "timeout_seconds": 2,
            "max_response_bytes": 1048576,
        }
        values.update(changes)
        return HandoffProfile(**values)

    def write_launch(self):
        self.launch_receipt["actor_output"] = {
            "sha256": hashlib.sha256(self.request).hexdigest(),
            "bytes": len(self.request),
        }
        (self.launch / "actor-output.bin").write_bytes(self.request)
        stdout = (
            json.dumps(self.launch_receipt["bootstrap"]).encode() + b"\n" + self.request
        )
        self.launch_receipt["stdout"] = {
            "sha256": hashlib.sha256(stdout).hexdigest(),
            "bytes": len(stdout),
        }
        (self.launch / "stdout.bin").write_bytes(stdout)
        (self.launch / "RECEIPT.json").write_text(json.dumps(self.launch_receipt))

    def send(self, **changes):
        options = {
            "request_id": "physical-pair-off",
            "case_id": "source-1-case-c",
            "profile": self.profile(),
        }
        options.update(changes)
        return handoff(self.journal, self.launch, **options)

    def attempt(self):
        return self.journal / hashlib.sha256(b"physical-pair-off").hexdigest()

    def test_body_is_byte_exact_and_replay_sends_no_second_request(self):
        receipt = self.send()
        self.assertEqual(receipt["status"], "RECEIVED")
        self.assertEqual(len(self.server.calls), 1)
        path, headers, body = self.server.calls[0]
        self.assertEqual(path, "/v1/responses")
        self.assertEqual(body, self.request)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual((self.attempt() / "request.bin").read_bytes(), self.request)
        self.assertEqual(
            (self.attempt() / "response.bin").read_bytes(), self.server.body
        )
        self.assertEqual(self.send(), receipt)
        self.assertEqual(len(self.server.calls), 1)
        self.assertEqual(
            json.loads((self.attempt() / "RECEIPT.json").read_bytes()), receipt
        )

    def test_same_identity_cannot_change_case_profile_or_actor_output(self):
        self.send()
        for change in (
            {"case_id": "different-case"},
            {"profile": self.profile(endpoint=self.endpoint + "/changed")},
            {"profile": self.profile(timeout_seconds=1)},
        ):
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                self.send(**change)
        self.request = self.request.replace(b"public task C", b"different task")
        self.write_launch()
        with self.assertRaises(ValueError):
            self.send()
        self.assertEqual(len(self.server.calls), 1)

    def test_incomplete_admission_never_replays_a_potential_send(self):
        self.attempt().mkdir(parents=True)
        result = self.send()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.send()["status"], "UNKNOWN")
        self.assertEqual(self.server.calls, [])

    def test_non_success_http_is_received_without_retry(self):
        self.server.response_status = 503
        self.server.body = b'{"error":"fixture overload"}'
        result = self.send()
        self.assertEqual(result["status"], "RECEIVED")
        self.assertEqual(
            (self.attempt() / "response.bin").read_bytes(), self.server.body
        )
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_lost_response_or_headers_remain_unknown_without_another_send(self):
        result = self.send()
        self.assertEqual(result["status"], "RECEIVED")
        for filename in ("response-headers.json", "response.bin"):
            path = self.attempt() / filename
            original = path.read_bytes()
            path.write_bytes(b"changed retained transport evidence")
            with self.subTest(filename=filename):
                self.assertEqual(self.send()["status"], "UNKNOWN")
                self.assertEqual(len(self.server.calls), 1)
            path.write_bytes(original)
        self.assertEqual(self.send(), result)

    def test_received_terminal_cannot_drop_required_response_pins(self):
        result = self.send()
        self.assertEqual(result["status"], "RECEIVED")
        terminal = self.attempt() / "RECEIPT.json"
        original = terminal.read_bytes()
        for field in ("response", "response_headers"):
            terminal.write_text(json.dumps({**result, field: None}))
            with self.subTest(field=field):
                try:
                    replay = self.send()
                except ValueError:
                    pass
                else:
                    self.assertEqual(replay["status"], "UNKNOWN")
                self.assertEqual(len(self.server.calls), 1)
            terminal.write_bytes(original)
        self.assertEqual(self.send(), result)

    def test_redirect_response_does_not_follow_or_retry(self):
        self.server.behavior = "redirect"
        result = self.send()
        self.assertEqual(result["status"], "RECEIVED")
        self.assertEqual([call[0] for call in self.server.calls], ["/v1/responses"])
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_connection_loss_after_server_receives_body_stays_unknown(self):
        self.server.behavior = "disconnect"
        result = self.send()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.server.calls[0][2], self.request)
        self.server.behavior = "normal"
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_oversized_response_retains_unknown_and_cannot_be_replayed(self):
        self.server.body = b"x" * 1024
        profile = self.profile(max_response_bytes=32)
        result = self.send(profile=profile)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.send(profile=profile), result)
        self.assertEqual(len(self.server.calls), 1)
        self.assertLessEqual((self.attempt() / "response.bin").stat().st_size, 33)

    def test_short_response_retains_actual_bytes_and_never_retries(self):
        self.server.behavior = "truncated"
        result = self.send()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(
            (self.attempt() / "response.bin").read_bytes(), self.server.body
        )
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_duplicate_response_length_is_unknown_with_original_bytes(self):
        self.server.behavior = "ambiguous"
        result = self.send()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(
            (self.attempt() / "response.bin").read_bytes(), self.server.body
        )
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_failed_or_unbound_actor_never_admits_or_sends(self):
        original = self.launch_receipt.copy()
        for change in (
            {"status": "ACTOR_FAILED", "returncode": 1},
            {"returncode": 1},
            {"capture_truncated": True},
            {"source_unchanged": False},
            {"launcher_sha256": "3" * 64},
            {"actor_sha256": "3" * 64},
        ):
            self.launch_receipt = {**original, **change}
            self.write_launch()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.send()
            self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_output_hash_mismatch_cannot_reach_transport(self):
        (self.launch / "actor-output.bin").write_bytes(b"host-added history")
        with self.assertRaises(ValueError):
            self.send()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_history_tools_store_and_changed_model_are_rejected(self):
        original = json.loads(self.request)
        for change in (
            {"previous_response_id": "old-response"},
            {"conversation": "old-conversation"},
            {"tools": [{"type": "function", "name": "recall"}]},
            {"store": True},
            {"model": "other-model"},
            {"input": [{"role": "user", "content": "prior chat"}]},
        ):
            self.request = json.dumps({**original, **change}).encode()
            self.write_launch()
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                self.send()
            self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_external_and_credentialed_endpoints_reject_before_dispatch(self):
        for endpoint in (
            "http://example.com/v1/responses",
            "ftp://127.0.0.1/v1/responses",
            "http://credential@127.0.0.1/v1/responses",
            self.endpoint + "#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.send(profile=self.profile(endpoint=endpoint))
            self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_duplicate_json_keys_and_nonfinite_decoding_reject_before_send(self):
        original = self.request
        for raw in (
            original.replace(b'"store": false', b'"store": true, "store": false'),
            original.replace(b'"temperature": 0', b'"temperature": NaN'),
            original.replace(b'"temperature": 0', b'"temperature": Infinity'),
        ):
            self.request = raw
            self.write_launch()
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.send()
            self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])


if __name__ == "__main__":
    unittest.main()
