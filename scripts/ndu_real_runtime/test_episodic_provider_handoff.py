"""Actual localhost HTTP controls; these servers are not model executions."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
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
        if self.server.behavior == "slow_headers":
            try:
                self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                for _ in range(60):
                    self.connection.sendall(b"x")
                    time.sleep(0.03)
                self.connection.sendall(b"\r\nContent-Length: 0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
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
        for filename in (
            "response-headers.json",
            "response.bin",
            "worker-stdout.bin",
            "worker-stderr.bin",
        ):
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
        for field in (
            "response",
            "response_headers",
            "worker-stdout.bin",
            "worker-stderr.bin",
            "worker_reaped",
            "worker_returncode",
        ):
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
            self.endpoint + "/" + "x" * 4096,
            self.endpoint + "/" + "界" * 2048,
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

    def test_symlink_launch_input_rejects_before_admission(self):
        request = self.launch / "actor-output.bin"
        real = self.root / "unmounted-private-history"
        real.write_bytes(request.read_bytes())
        request.unlink()
        request.symlink_to(real)
        with self.assertRaises(ValueError):
            self.send()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_oversized_launch_metadata_is_refused_before_json_decode(self):
        receipt = self.launch / "RECEIPT.json"
        receipt.write_bytes(b" " * 65537)
        with self.assertRaisesRegex(ValueError, "bounded regular"):
            self.send()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO control")
    def test_fifo_launch_input_is_refused_without_opening_or_waiting(self):
        request = self.launch / "actor-output.bin"
        request.unlink()
        os.mkfifo(request)
        # The admission check must reject based on lstat before os.open can wait.
        from unittest.mock import patch

        original_open = os.open

        def reject_fifo(path, *args, **kwargs):
            if Path(path) == request:
                raise AssertionError("FIFO was opened")
            return original_open(path, *args, **kwargs)

        with patch("os.open", side_effect=reject_fifo):
            with self.assertRaisesRegex(ValueError, "bounded regular"):
                self.send()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.server.calls, [])

    def test_replay_rejects_symlinked_original_response(self):
        self.assertEqual(self.send()["status"], "RECEIVED")
        response = self.attempt() / "response.bin"
        real = self.root / "redirected-response"
        real.write_bytes(response.read_bytes())
        response.unlink()
        response.symlink_to(real)
        self.assertEqual(self.send()["status"], "UNKNOWN")
        self.assertEqual(len(self.server.calls), 1)

    def test_oversized_replay_metadata_stays_unknown_without_send(self):
        self.assertEqual(self.send()["status"], "RECEIVED")
        (self.attempt() / "RECEIPT.json").write_bytes(b" " * 65537)
        self.assertEqual(self.send()["status"], "UNKNOWN")
        self.assertEqual(len(self.server.calls), 1)

    def test_deeply_nested_replay_metadata_stays_unknown_without_send(self):
        self.assertEqual(self.send()["status"], "RECEIVED")
        (self.attempt() / "RECEIPT.json").write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
        self.assertEqual(self.send()["status"], "UNKNOWN")
        self.assertEqual(len(self.server.calls), 1)

    def test_slow_response_headers_hit_parent_deadline_and_never_retry(self):
        self.server.behavior = "slow_headers"
        profile = self.profile(timeout_seconds=0.25)
        started = time.monotonic()
        result = self.send(profile=profile)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result.get("reason"), "TRANSPORT_DEADLINE")
        self.assertTrue(result["worker_reaped"])
        self.assertEqual(len(self.server.calls), 1)
        self.assertEqual(self.send(profile=profile), result)
        self.assertEqual(len(self.server.calls), 1)

    def test_journal_is_synced_before_transport_child_is_started(self):
        from unittest.mock import patch
        import subprocess

        original = subprocess.Popen

        def checked_start(*args, **kwargs):
            self.assertTrue((self.attempt() / "ADMISSION.json").is_file())
            self.assertEqual(
                (self.attempt() / "request.bin").read_bytes(), self.request
            )
            self.assertTrue(kwargs["close_fds"])
            self.assertTrue(kwargs["start_new_session"])
            self.assertIn("-I", args[0])
            self.assertIn("-S", args[0])
            return original(*args, **kwargs)

        with patch("subprocess.Popen", side_effect=checked_start):
            result = self.send()
        self.assertEqual(result["status"], "RECEIVED")
        self.assertTrue(result["worker_reaped"])
        self.assertEqual(len(self.server.calls), 1)


if __name__ == "__main__":
    unittest.main()
