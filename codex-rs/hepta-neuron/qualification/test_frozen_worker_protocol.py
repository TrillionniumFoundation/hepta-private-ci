"""Validate private worker framing before any encoder work."""
import hashlib
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"))
import frozen_decision_cell_worker as worker


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        projection = {"projection_schema": "hepta.decision-cell-text-projection.v1",
                      "texts": ("select the observed file",),
                      "candidates": (("file A", "file B", "file C", "file D"),)}
        self.value = {"schema": worker.SCHEMA, "request_id": "request.1",
            "projection_sha256": hashlib.sha256(worker._canonical(projection)).hexdigest(),
            "deadline_monotonic_ns": time.monotonic_ns() + 10**10,
            "text": projection["texts"][0], "candidates": list(projection["candidates"][0])}

    def test_admits_exact_projection(self):
        self.assertEqual(worker.request(worker._canonical(self.value)), self.value)

    def test_rejects_text_changed_under_old_digest(self):
        self.value["text"] = "different observation"
        with self.assertRaisesRegex(ValueError, "substitution"):
            worker.request(worker._canonical(self.value))

    def test_rejects_noncanonical_shape_and_unbounded_deadline(self):
        for key, value in (("schema", "unsupported"), ("request_id", "invalid id"),
                           ("deadline_monotonic_ns", True),
                           ("deadline_monotonic_ns", time.monotonic_ns() + 121 * 10**9),
                           ("candidates", ["a", "b"]), ("text", "")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                worker.request(worker._canonical({**self.value, key: value}))

    def test_rejects_truncated_and_oversized_frames(self):
        data = worker._canonical(self.value)
        for raw in (data[:-1], b"x" * (worker.MAX_FRAME + 1)):
            with self.assertRaisesRegex(ValueError, "frame length"):
                worker.request(raw)

    def test_rejects_duplicate_and_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            worker.request(b'{"request_id":"a","request_id":"b"}\n')
        with self.assertRaisesRegex(ValueError, "unknown"):
            worker.request(worker._canonical({**self.value, "authority": True}))



class ScalarTensor:
    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


class FakeEncoder:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def observe(self, texts, candidates, *, deadline_ns):
        self.calls += 1
        if self.fail:
            raise OSError("lost model observation")
        projection = {"projection_schema": "hepta.decision-cell-text-projection.v1",
                      "texts": texts, "candidates": candidates}
        return {"input_sha256": hashlib.sha256(worker._canonical(projection)).hexdigest(),
                "scores": {"action": ScalarTensor([[1, 2]])},
                "probabilities": {"action": ScalarTensor([[0.2, 0.8]])},
                "advisory_only": True, "external_effect": False}


class WorkerSessionTests(unittest.TestCase):
    setUp = WorkerProtocolTests.setUp

    def command(self, *, kind="infer", invocation="a" * 64):
        return worker._canonical({"schema": worker.COMMAND_SCHEMA, "session_id": "session.1",
            "kind": kind, "invocation_sha256": invocation, "request": self.value})

    def test_repeated_infer_and_lookup_reuse_exact_bytes(self):
        model = FakeEncoder()
        session = worker.WorkerSession(model, "session.1")
        first = session.handle(self.command())
        self.assertEqual(session.handle(self.command()), first)
        self.assertEqual(session.handle(self.command(kind="lookup")), first)
        self.assertEqual(model.calls, 1)

    def test_invocation_drift_never_reexecutes(self):
        model = FakeEncoder()
        session = worker.WorkerSession(model, "session.1")
        session.handle(self.command())
        with self.assertRaisesRegex(ValueError, "changed semantics"):
            session.handle(self.command(invocation="b" * 64))
        self.assertEqual(model.calls, 1)

    def test_restart_lookup_is_unknown_not_absence_or_reexecution(self):
        import json
        model = FakeEncoder()
        original = worker.WorkerSession(model, "session.1")
        original.handle(self.command())
        reopened = worker.WorkerSession(model, "session.1")
        result = json.loads(reopened.handle(self.command(kind="lookup")))
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(model.calls, 1)

    def test_failed_inference_is_retained_indeterminate(self):
        import json
        model = FakeEncoder(fail=True)
        session = worker.WorkerSession(model, "session.1")
        first = session.handle(self.command())
        self.assertEqual(json.loads(first)["status"], "indeterminate")
        self.assertEqual(session.handle(self.command()), first)
        self.assertEqual(model.calls, 1)

    def test_expired_lookup_does_not_admit_new_inference(self):
        import json
        model = FakeEncoder()
        session = worker.WorkerSession(model, "session.1")
        self.value["deadline_monotonic_ns"] = 1
        self.assertEqual(json.loads(session.handle(self.command(kind="lookup")))["status"], "unknown")
        with self.assertRaisesRegex(ValueError, "deadline"):
            session.handle(self.command())
        self.assertEqual(model.calls, 0)

    def test_frame_loss_closes_without_parsing_appended_command(self):
        import io
        model = FakeEncoder()
        source = io.BytesIO(b"x" * (worker.MAX_FRAME + 1) + b"\n" + self.command())
        output = io.BytesIO()
        worker.serve(worker.WorkerSession(model, "session.1"), source, output)
        self.assertEqual(model.calls, 0)
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_capacity_rejects_before_compute_without_evicting(self):
        model = FakeEncoder()
        session = worker.WorkerSession(model, "session.1")
        session._bytes = worker.MAX_CACHE_BYTES
        with self.assertRaisesRegex(ValueError, "capacity"):
            session.handle(self.command())
        self.assertEqual(model.calls, 0)


if __name__ == "__main__":
    unittest.main()
