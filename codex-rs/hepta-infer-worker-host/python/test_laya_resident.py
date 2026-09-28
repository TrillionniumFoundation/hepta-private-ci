"""Resident lifecycle regressions: real children, deliberately synthetic models."""
import io
from pathlib import Path
import struct
import selectors
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hepta_retrieval_wire import MAX_FRAME, decode_reply, encode_request
from laya_binary import BinaryRetrievalDriver, OwnerDeadline
from laya_process import ProcessFailure
from laya_resident import ResidentLaya, serve
from laya_retrieval import Rejected
from laya_wait import observe_owned_exit
from test_laya_binary import Predictor, request


ROOT = Path(__file__).resolve().parent


def fresh(index=1, seconds=5):
    value = request()
    value["operation_id"] = f"resident.{index}"
    value["deadline_ms"] = int(time.time() * 1000 + seconds * 1000)
    return value


def framed(value):
    wire = encode_request(value)
    return struct.pack(">I", len(wire)) + wire


class ResidentServiceTests(unittest.TestCase):
    def setUp(self):
        self.agent = Predictor()
        self.loads = 0

    def loader(self, value):
        self.loads += 1
        return BinaryRetrievalDriver(self.agent, value["bundle_digest"])

    def test_load_once_distinct_operations_preserve_original_wire(self):
        values = [fresh(index) for index in range(3)]
        output = io.BytesIO()
        self.assertEqual(serve(io.BytesIO(b"".join(map(framed, values))), output, self.loader), 3)
        self.assertEqual((self.loads, self.agent.calls), (1, 3))
        remaining = output.getvalue()
        for value in values:
            length = struct.unpack(">I", remaining[:4])[0]
            reply = decode_reply(remaining[4:4 + length], encode_request(value))
            self.assertEqual(reply["input_tokens"], 37)
            remaining = remaining[4 + length:]
        self.assertEqual(remaining, b"")

    def test_duplicate_never_calls_model_twice(self):
        value = fresh()
        with self.assertRaises(Rejected):
            serve(io.BytesIO(framed(value) * 2), io.BytesIO(), self.loader)
        self.assertEqual((self.loads, self.agent.calls), (1, 1))

    def test_session_identity_cannot_change_after_load(self):
        for field, changed in [("generation", 4), ("workspace_id", "elsewhere"),
                               ("bundle_digest", "4" * 64)]:
            with self.subTest(field=field):
                self.setUp()
                one, two = fresh(1), fresh(2)
                two[field] = changed
                with self.assertRaises(Rejected):
                    serve(io.BytesIO(framed(one) + framed(two)), io.BytesIO(), self.loader)
                self.assertEqual((self.loads, self.agent.calls), (1, 1))

    def test_partial_zero_and_oversized_frames_never_load(self):
        for raw in [b"\0", b"\0\0\0\0", struct.pack(">I", MAX_FRAME + 1), b"\0\0\0\x10a"]:
            with self.subTest(raw=raw), self.assertRaises(Exception):
                serve(io.BytesIO(raw), io.BytesIO(), self.loader)
        self.assertEqual(self.loads, 0)

    def test_loading_consumes_original_deadline(self):
        value = fresh(seconds=0.03)
        def slow_loader(value):
            time.sleep(0.05)
            return self.loader(value)
        with self.assertRaises(Rejected):
            serve(io.BytesIO(framed(value)), io.BytesIO(), slow_loader)
        self.assertEqual(self.agent.calls, 0)

    def test_operation_bound_stops_before_additional_model_call(self):
        self.assertEqual(serve(io.BytesIO(framed(fresh(1)) + framed(fresh(2))),
                               io.BytesIO(), self.loader, maximum_operations=1), 1)
        self.assertEqual((self.loads, self.agent.calls), (1, 1))

    def test_invalid_lifetime_and_count_profiles_reject(self):
        for limit in [0, -1, 65, True, 1.0]:
            with self.subTest(limit=limit), self.assertRaises(Rejected):
                serve(io.BytesIO(), io.BytesIO(), self.loader, maximum_operations=limit)
        for limit in [0, 301, float("nan"), float("inf"), True]:
            with self.subTest(limit=limit), self.assertRaises(Rejected):
                serve(io.BytesIO(), io.BytesIO(), self.loader, lifetime_seconds=limit)

    def test_partial_output_writes_preserve_complete_frame(self):
        class ShortWriter(io.BytesIO):
            def write(self, value):
                return super().write(value[:3])
        output = ShortWriter()
        value = fresh()
        serve(io.BytesIO(framed(value)), output, self.loader)
        raw = output.getvalue()
        self.assertEqual(struct.unpack(">I", raw[:4])[0], len(raw) - 4)
        decode_reply(raw[4:], encode_request(value))

    def test_zero_progress_output_rejects_instead_of_looping(self):
        class StalledWriter(io.BytesIO):
            def write(self, value):
                return 0
        with self.assertRaises(Rejected):
            serve(io.BytesIO(framed(fresh())), StalledWriter(), self.loader)
        self.assertEqual(self.agent.calls, 1)


class ResidentProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def start(self, code=None, **limits):
        session = ResidentLaya(self.root, self.root / "pins.json", **limits)
        # This is an explicit process fixture, not a public arbitrary-command API.
        code = code or (
            "from laya_resident import serve; from laya_binary import BinaryRetrievalDriver; "
            "from test_laya_binary import Predictor; import sys; "
            "serve(sys.stdin.buffer,sys.stdout.buffer,"
            "lambda r: BinaryRetrievalDriver(Predictor(),r['bundle_digest']))")
        session._command = [sys.executable, "-u", "-c", f"import sys; sys.path.insert(0,{str(ROOT)!r}); " + code]
        self.addCleanup(session.close)
        return session

    def predict(self, session, value=None, cancel=None):
        value = value or fresh()
        return session.predict(encode_request(value), OwnerDeadline.start(value["deadline_ms"]), cancel)

    def test_real_process_reuses_pid_then_reaps_once(self):
        session = self.start()
        one = self.predict(session, fresh(1))
        two = self.predict(session, fresh(2))
        self.assertEqual(one.observation["process_id"], two.observation["process_id"])
        self.assertEqual(two.observation["completed_exchanges"], 2)
        self.assertFalse(two.observation["direct_child_reaped"])
        self.assertFalse(two.observation["model_reservation_released"])
        with self.assertRaises(Rejected):
            self.predict(session, fresh(2))
        self.assertEqual(session.observation["completed_exchanges"], 2)
        result = session.close()
        self.assertTrue(result["direct_child_reaped"])
        self.assertFalse(result["descendant_exit_verified"])
        self.assertIsNone(result["observed_memory_bytes"])
        self.assertEqual(session.close(), result)

    def test_wrong_generation_is_rejected_before_more_io(self):
        session = self.start()
        self.predict(session)
        count = session.observation["input_bytes_written"]
        value = fresh(2); value["generation"] += 1
        with self.assertRaises(Rejected): self.predict(session, value)
        self.assertEqual(session.observation["input_bytes_written"], count)
        self.assertEqual(self.predict(session, fresh(3)).observation["completed_exchanges"], 2)

    def test_expired_and_cancelled_before_spawn_create_no_child(self):
        session = self.start()
        event = threading.Event(); event.set()
        with self.assertRaises(Rejected): self.predict(session, cancel=event)
        self.assertFalse(session.observation["spawned"])
        value = fresh(seconds=0.01)
        deadline = OwnerDeadline.start(value["deadline_ms"])
        time.sleep(0.02)
        with self.assertRaises(Rejected): session.predict(encode_request(value), deadline)
        self.assertFalse(session.observation["spawned"])

    def test_deadline_kills_real_child_and_no_retry_uses_new_process(self):
        session = self.start("import time; time.sleep(10)")
        with self.assertRaises(ProcessFailure) as failed:
            self.predict(session, fresh(seconds=0.08))
        self.assertTrue(failed.exception.observation["direct_child_reaped"])
        self.assertFalse(failed.exception.observation["eligible_reply"])
        previous = session.observation
        with self.assertRaises(Rejected): self.predict(session, fresh(2))
        self.assertEqual(session.observation, previous)

    def test_cancellation_of_active_request_reaps_and_fences(self):
        session = self.start("import time; time.sleep(10)")
        event = threading.Event()
        timer = threading.Timer(0.08, event.set)
        timer.start()
        try:
            with self.assertRaises(ProcessFailure) as failed: self.predict(session, cancel=event)
        finally:
            timer.join()
        self.assertTrue(failed.exception.observation["direct_child_reaped"])
        self.assertFalse(failed.exception.observation["retry_allowed"])

    def test_bad_reply_partial_eof_and_stderr_overflow_fence_session(self):
        for code in ["import os; os.read(0,65536); os.write(1,b'\\0\\0\\0\\5a')",
                     "import os; os.read(0,65536); os.write(1,b'\\0\\0\\0\\1x')",
                     "import os; os.read(0,65536); os.write(2,b'x'*9000); import time; time.sleep(3)"]:
            with self.subTest(code=code):
                session = self.start(code)
                with self.assertRaises(ProcessFailure): self.predict(session)
                with self.assertRaises(Rejected): self.predict(session, fresh(2))
                self.assertTrue(session.observation["direct_child_reaped"])

    def test_failed_signal_retains_identity_until_cleanup_reconciliation(self):
        session = self.start("import time; time.sleep(10)")
        with patch("laya_process.signal_owned_group", side_effect=PermissionError("denied")):
            with self.assertRaises(ProcessFailure) as failed:
                self.predict(session, fresh(seconds=0.06))
        error = failed.exception
        self.assertIsNotNone(error.child)
        self.assertIsNone(error.child.returncode)
        self.assertFalse(error.observation["direct_child_reaped"])
        settled = session.close()
        self.assertTrue(settled["direct_child_reaped"])
        self.assertFalse(settled["eligible_reply"])
        with self.assertRaises(Rejected): self.predict(session, fresh(2))

    def test_selector_failure_after_spawn_retains_cleanup(self):
        session = self.start("import time; time.sleep(10)")
        with patch.object(selectors.DefaultSelector, "register", side_effect=OSError("register")):
            with self.assertRaises(ProcessFailure): self.predict(session)
        self.assertTrue(session.observation["spawned"])
        self.assertTrue(session.observation["direct_child_reaped"])

    def test_concurrent_use_does_not_queue_or_touch_transport(self):
        session = self.start()
        session._lock.acquire()
        try:
            with self.assertRaises(Rejected): self.predict(session)
        finally: session._lock.release()
        self.assertFalse(session.observation["spawned"])

    def test_real_idle_child_has_bounded_lifetime(self):
        session = self.start(
            "from laya_resident import serve; import sys; "
            "serve(sys.stdin.buffer,sys.stdout.buffer,lambda r:None,lifetime_seconds=0.04)")
        # Deliberately no input; the real child checks its idle deadline, not only predictions.
        session._start()
        limit = time.monotonic() + 2
        while observe_owned_exit(session._child.pid) is None and time.monotonic() < limit:
            time.sleep(0.01)
        self.assertIsNotNone(observe_owned_exit(session._child.pid))
        result = session.close()
        self.assertTrue(result["direct_child_reaped"])
        self.assertEqual(result["completed_exchanges"], 0)

    def test_cancellation_at_last_reply_check_cannot_publish(self):
        session = self.start()
        event = threading.Event()
        def decode_then_cancel(reply, wire):
            result = decode_reply(reply, wire)
            event.set()
            return result
        with patch("laya_resident.decode_reply", side_effect=decode_then_cancel):
            with self.assertRaises(ProcessFailure) as failed:
                self.predict(session, cancel=event)
        self.assertTrue(failed.exception.observation["direct_child_reaped"])
        self.assertFalse(failed.exception.observation["eligible_reply"])
        self.assertEqual(session.observation["completed_exchanges"], 0)

    def test_parent_operation_limit_retains_model_until_explicit_close(self):
        session = self.start(maximum_operations=1)
        self.predict(session)
        written = session.observation["input_bytes_written"]
        with self.assertRaises(Rejected): self.predict(session, fresh(2))
        self.assertEqual(session.observation["input_bytes_written"], written)
        self.assertFalse(session.observation["model_reservation_released"])

    def test_unresolved_reconciliation_is_not_successful_close(self):
        session = self.start("import time; time.sleep(10)")
        with patch("laya_process.signal_owned_group", side_effect=PermissionError("denied")):
            with self.assertRaises(ProcessFailure): self.predict(session, fresh(seconds=0.06))
            with self.assertRaises(ProcessFailure): session.close()
            self.assertIsNotNone(session._child)
        self.assertTrue(session.close()["direct_child_reaped"])


if __name__ == "__main__":
    unittest.main()
