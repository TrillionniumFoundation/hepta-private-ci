"""Actual resident-child boundaries with controlled cancellation/clock faults.

Predictors are synthetic. These tests do not establish native host composition,
source authority, hard memory isolation, real-model efficacy or resource release.
"""
from dataclasses import replace
import hashlib
import selectors
import threading
import unittest
from unittest.mock import patch

from hepta_retrieval_wire import decode_reply, encode_request
from laya_binary import OwnerDeadline
from laya_process import ProcessFailure
from laya_retrieval import Rejected
import test_laya_resident as fixtures


class ResidentBoundaryTests(unittest.TestCase):
    setUp = fixtures.ResidentProcessTests.setUp
    start = fixtures.ResidentProcessTests.start
    predict = fixtures.ResidentProcessTests.predict

    def test_cancel_after_readiness_before_first_write_keeps_zero_dispatch_bytes(self):
        session = self.start("import time; time.sleep(10)")
        cancel = threading.Event()
        select = selectors.DefaultSelector.select
        def ready(selector, timeout=None):
            events = select(selector, timeout)
            cancel.set()
            return events
        with patch.object(selectors.DefaultSelector, "select", ready):
            with self.assertRaises(ProcessFailure) as caught:
                self.predict(session, cancel=cancel)
        observed = caught.exception.observation
        self.assertEqual(observed["input_bytes_written"], 0)
        self.assertEqual(observed["completed_exchanges"], 0)
        self.assertTrue(observed["direct_child_reaped"])
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])
        with self.assertRaises(Rejected):
            self.predict(session, fixtures.fresh(2))

    def test_request_expiry_after_readiness_cannot_write(self):
        session = self.start("import time; time.sleep(10)")
        request = fixtures.fresh()
        ticks = [100.0]
        deadline = OwnerDeadline.start(request["deadline_ms"], monotonic_clock=lambda: ticks[0])
        select = selectors.DefaultSelector.select
        def ready(selector, timeout=None):
            events = select(selector, timeout)
            ticks[0] = deadline.monotonic_end
            return events
        with patch.object(selectors.DefaultSelector, "select", ready):
            with self.assertRaises(ProcessFailure) as caught:
                session.predict(encode_request(request), deadline)
        self.assertEqual(caught.exception.observation["input_bytes_written"], 0)
        self.assertTrue(caught.exception.observation["direct_child_reaped"])

    def test_session_expiry_after_readiness_cannot_write(self):
        session = self.start("import time; time.sleep(10)")
        select = selectors.DefaultSelector.select
        def ready(selector, timeout=None):
            events = select(selector, timeout)
            session._lifetime = replace(session._lifetime, monotonic_end=-1.0)
            return events
        with patch.object(selectors.DefaultSelector, "select", ready):
            with self.assertRaises(ProcessFailure) as caught:
                self.predict(session)
        self.assertEqual(caught.exception.observation["input_bytes_written"], 0)
        self.assertTrue(caught.exception.observation["direct_child_reaped"])

    def test_cancellation_during_preflight_hash_prevents_process_creation(self):
        session = self.start("import time; time.sleep(10)")
        cancel = threading.Event()
        request = fixtures.fresh()
        wire = encode_request(request)
        deadline = OwnerDeadline.start(request["deadline_ms"])
        sha256 = hashlib.sha256
        def hash_then_cancel(value=b"", **kwargs):
            result = sha256(value, **kwargs)
            if value == wire:
                cancel.set()
            return result
        with patch("laya_resident.hashlib.sha256", side_effect=hash_then_cancel):
            with self.assertRaises(ProcessFailure) as caught:
                session.predict(wire, deadline, cancel)
        self.assertFalse(caught.exception.observation["spawned"])
        self.assertEqual(caught.exception.observation["input_bytes_written"], 0)

    def test_later_failed_reply_does_not_relabel_the_previous_reply_digest(self):
        session = self.start()
        first = self.predict(session, fixtures.fresh(1))
        previous = first.observation.copy()
        second = fixtures.fresh(2)
        with patch("laya_resident.decode_reply", side_effect=Rejected("controlled bad reply")):
            with self.assertRaises(ProcessFailure) as caught:
                self.predict(session, second)
        observed = caught.exception.observation
        self.assertEqual(observed["operation_id"], second["operation_id"])
        self.assertEqual(observed["request_sha256"], hashlib.sha256(encode_request(second)).hexdigest())
        self.assertIsNone(observed["reply_sha256"])
        self.assertFalse(observed["eligible_reply"])
        self.assertEqual(observed["completed_exchanges"], 1)
        self.assertEqual(first.observation, previous)
        self.assertEqual(previous["reply_sha256"], hashlib.sha256(first.wire).hexdigest())

    def test_preflight_rejection_leaves_the_previous_historical_observation_intact(self):
        session = self.start()
        request = fixtures.fresh(1)
        first = self.predict(session, request)
        before = session.observation
        with self.assertRaises(Rejected):
            self.predict(session, request)
        self.assertEqual(session.observation, before)
        self.assertEqual(first.observation, before)
        second = self.predict(session, fixtures.fresh(2))
        self.assertEqual(second.observation["completed_exchanges"], 2)

    def test_each_success_binds_its_own_deadline_and_complete_reply(self):
        session = self.start()
        for index in range(3):
            request = fixtures.fresh(index, seconds=5 + index)
            result = self.predict(session, request)
            observed = result.observation
            self.assertEqual(observed["operation_id"], request["operation_id"])
            self.assertEqual(observed["deadline_ms"], request["deadline_ms"])
            self.assertEqual(observed["reply_sha256"], hashlib.sha256(result.wire).hexdigest())
            decode_reply(result.wire, encode_request(request))
            self.assertFalse(observed["model_reservation_released"])
        self.assertEqual(session.observation["completed_exchanges"], 3)

    def test_cancel_during_reply_hash_retains_observation_but_cannot_deliver(self):
        session = self.start()
        cancel = threading.Event()
        sha256 = hashlib.sha256
        def hash_then_cancel(value=b"", **kwargs):
            result = sha256(value, **kwargs)
            if value.startswith(b"HPTARS"):
                cancel.set()
            return result
        with patch("laya_resident.hashlib.sha256", side_effect=hash_then_cancel):
            with self.assertRaises(ProcessFailure) as caught:
                self.predict(session, cancel=cancel)
        observed = caught.exception.observation
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])
        self.assertTrue(observed["direct_child_reaped"])
        self.assertEqual(len(observed["reply_sha256"]), 64)
        self.assertGreater(observed["stdout_bytes"], 0)

    def test_expiry_during_reply_hash_cannot_deliver(self):
        session = self.start()
        request = fixtures.fresh()
        ticks = [100.0]
        deadline = OwnerDeadline.start(request["deadline_ms"], monotonic_clock=lambda: ticks[0])
        sha256 = hashlib.sha256
        def hash_then_expire(value=b"", **kwargs):
            result = sha256(value, **kwargs)
            if value.startswith(b"HPTARS"):
                ticks[0] = deadline.monotonic_end
            return result
        with patch("laya_resident.hashlib.sha256", side_effect=hash_then_expire):
            with self.assertRaises(ProcessFailure) as caught:
                session.predict(encode_request(request), deadline)
        self.assertFalse(caught.exception.observation["eligible_reply"])
        self.assertTrue(caught.exception.observation["direct_child_reaped"])


if __name__ == "__main__":
    unittest.main()
