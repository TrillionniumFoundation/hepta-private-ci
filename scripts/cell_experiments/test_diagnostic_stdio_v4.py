"""Test only pipe framing, failure and owned cleanup; zero model evidence."""

from pathlib import Path
import sys
import tempfile
import unittest

from .diagnostic_run_v4 import LIMIT, ProviderProcess

STUB = """import json, os, sys, time
print(json.dumps({"status":"READY", "pid":os.getpid(), "scope":"protocol_fixture"}), flush=True)
for raw in sys.stdin:
    request = json.loads(raw)
    if request["op"] == "close":
        print(json.dumps({"status":"CLOSED", "id":request["id"]}), flush=True)
        if sys.argv[1] == "trailing":
            time.sleep(0.05)
            sys.stdout.buffer.write(b"AFTER_CLOSE\\n")
            sys.stdout.buffer.flush()
        break
    if sys.argv[1] in ("malformed", "partial", "oversized"):
        payload = {"malformed": b"NOT JSON\\n", "partial": b'{"status":',
                   "oversized": b"X" * (262144 + 17) + b"\\n"}[sys.argv[1]]
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
        break
    if sys.argv[1] == "timeout":
        time.sleep(5)
    number = request["id"] + (sys.argv[1] == "stale")
    print(json.dumps({"status":"OUTPUT", "id":number,
                      "output":{"answer":request["request"], "protocol_fixture":True}}), flush=True)
"""


class DiagnosticStdioTests(unittest.TestCase):
    def test_bounded_framing_and_real_close_with_large_fixture_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ProviderProcess(
                [sys.executable, "-I", "-c", STUB, "normal"], tmp, timeout=5
            )
            try:
                self.assertEqual(client.read()["pid"], client.child.pid)
                content = 'quoted " text\\ with newline\n' * 2500
                result = client.call(
                    "generate", cell="F", request=content, call_dir=tmp
                )
                self.assertEqual(result, {"answer": content, "protocol_fixture": True})
                self.assertEqual(client.call("close")["status"], "CLOSED")
                self.assertEqual(client.child.wait(timeout=5), 0)
                client.require_eof()
                self.assertEqual((client.dispatched, len(client.outputs)), (1, 1))
            finally:
                client.finish()
            self.assertTrue((Path(tmp) / "PROVIDER_EXIT.json").is_file())

    def test_wrong_response_sequence_is_rejected_and_owned_child_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ProviderProcess(
                [sys.executable, "-I", "-c", STUB, "stale"], tmp, timeout=5
            )
            try:
                client.read()
                with self.assertRaisesRegex(ValueError, "wrong sequence/status"):
                    client.call("generate", cell="F", request="fixture", call_dir=tmp)
            finally:
                client.finish()
            self.assertIsNotNone(client.child.poll())

    def test_response_deadline_keeps_timeout_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ProviderProcess(
                [sys.executable, "-I", "-c", STUB, "timeout"], tmp, timeout=5
            )
            try:
                client.read()
                client.timeout = 0.05
                with self.assertRaises(TimeoutError):
                    client.call("generate", cell="F", request="fixture", call_dir=tmp)
                self.assertEqual(len(client.outputs), 0)
            finally:
                client.finish()

    def test_invalid_raw_stdout_survives_protocol_failure(self):
        for mode, expected in (
            ("malformed", b"NOT JSON\n"),
            ("partial", b'{"status":'),
            ("oversized", b"X" * (LIMIT + 1)),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                client = ProviderProcess(
                    [sys.executable, "-I", "-c", STUB, mode], tmp, timeout=5
                )
                try:
                    client.read()
                    before = (Path(tmp) / "PROVIDER_STDOUT.bin").read_bytes()
                    with self.assertRaises(ValueError):
                        client.call(
                            "generate", cell="F", request="fixture", call_dir=tmp
                        )
                    self.assertEqual(
                        (Path(tmp) / "PROVIDER_STDOUT.bin").read_bytes(),
                        before + expected,
                    )
                    self.assertEqual((client.dispatched, len(client.outputs)), (1, 0))
                finally:
                    client.finish()

    def test_trailing_stdout_is_retained_before_close_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ProviderProcess(
                [sys.executable, "-I", "-c", STUB, "trailing"], tmp, timeout=5
            )
            try:
                client.read()
                self.assertEqual(client.call("close")["status"], "CLOSED")
                self.assertEqual(client.child.wait(timeout=5), 0)
                with self.assertRaisesRegex(ValueError, "after close"):
                    client.require_eof()
                self.assertTrue(
                    (Path(tmp) / "PROVIDER_STDOUT.bin")
                    .read_bytes()
                    .endswith(b"AFTER_CLOSE\n")
                )
                self.assertEqual((client.dispatched, len(client.outputs)), (0, 0))
            finally:
                client.finish()


if __name__ == "__main__":
    unittest.main()
