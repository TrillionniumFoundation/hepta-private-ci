import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from teacher_router import canonical, identity, observe, read_inputs, request_body, write_json
from transport import SseEvidence, post_once


def event(kind, **values):
    return b"data: " + canonical({"type": kind, **values}) + b"\n\n"


def stream(label="at", final_id="resp-original"):
    return event("response.created", response={"id": "resp-original"}) + event(
        "response.completed", response={"id": final_id, "status": "completed",
        "output": [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": json.dumps({"intent": label})}]}],
        "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}})


class Peer:
    def __init__(self, mode):
        self.calls = []
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                peer.calls.append((self.path, body, self.headers.get("Idempotency-Key")))
                self.send_response(307 if mode == "redirect" else 200)
                self.send_header("Content-Type", "text/plain" if mode == "redirect" else "text/event-stream")
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                try:
                    if mode == "complete":
                        self.wfile.write(stream())
                    elif mode == "redirect":
                        self.wfile.write(b"redirect-body")
                    else:
                        self.wfile.write(event("response.created", response={"id": "resp-original"}))
                        self.wfile.flush()
                        if mode == "trickle":
                            for _ in range(40):
                                time.sleep(0.04)
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()


class TeacherTests(unittest.TestCase):
    def test_sse_boundaries_and_original_identity(self):
        decoder = SseEvidence()
        for byte in stream("__reject__"):
            decoder.feed(bytes([byte]))
        self.assertEqual((decoder.result()["raw_label"], decoder.result()["accepted"]), ("__reject__", False))
        with self.assertRaises(ValueError):
            SseEvidence().feed(stream(final_id="different"))
        # JSON for the assistant message is itself escaped, so build it explicitly.
        duplicate = event("response.created", response={"id": "resp-original"}) + event(
            "response.completed", response={"id": "resp-original", "status": "completed",
                "output": [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": '{"intent":"at","intent":"change"}'}]}]})
        decoder = SseEvidence()
        decoder.feed(duplicate)
        with self.assertRaises(ValueError):
            decoder.result()

    def test_exact_one_post_and_ambiguous_disconnect_is_not_rejection(self):
        for mode, expected in (("complete", "completed"), ("disconnect", "unknown_or_invalid"), ("redirect", "unknown_or_invalid")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                peer = Peer(mode)
                try:
                    path = Path(temp) / "response.sse"
                    result = post_once(peer.url, b'{"exact":true}', "original-operation", path, 2)
                    self.assertEqual(peer.calls, [("/v1/responses", b'{"exact":true}', "original-operation")])
                    self.assertEqual(result["status"], expected)
                    if mode != "complete":
                        self.assertIsNone(result["raw_label"])
                    if mode == "disconnect":
                        self.assertEqual(result["provider_response_id"], "resp-original")
                    if mode == "redirect":
                        self.assertEqual(path.read_bytes(), b"redirect-body")
                finally:
                    peer.close()

    def test_absolute_deadline_despite_continuous_keepalive(self):
        with tempfile.TemporaryDirectory() as temp:
            peer = Peer("trickle")
            try:
                start = time.monotonic()
                result = post_once(peer.url, b"{}", "one-operation", Path(temp) / "response.sse", 0.15)
                elapsed = time.monotonic() - start
                self.assertLess(elapsed, 0.8)
                self.assertEqual(result["status"], "unknown_or_invalid")
                self.assertEqual(len(peer.calls), 1)
            finally:
                peer.close()

    def test_labeled_input_is_rejected_and_retained_completion_is_observed_without_post(self):
        request = {"utterance": "Read temperature for 2024-07.", "series_name": "temperature", "date": "2024-07"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = canonical({**request, "intent": "at"}) + b"\n"
            path = root / "input.jsonl"
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                read_inputs(path, hashlib.sha256(raw).hexdigest())
            run = {"run_id": "original-run", "input_sha256": "a" * 64, "freeze_sha256": "b" * 64}
            body = request_body("test-only contract", request)
            operation = identity(run, 0, body)
            case = root / "case-0000"
            case.mkdir()
            (case / "request.body.json").write_bytes(body)
            write_json(case / "admission.json", {"operation_id": operation, "body_sha256": hashlib.sha256(body).hexdigest()})
            (case / "response.sse").write_bytes(stream())
            result = observe(0, request, "test-only contract", run, root)
            self.assertEqual((result["status"], result["operation_id"], result["network_requests"]), ("completed", operation, 0))
            self.assertEqual(result["accepted_intent"], "at")


if __name__ == "__main__":
    unittest.main()
