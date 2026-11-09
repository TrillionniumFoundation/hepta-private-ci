"""Causality and time semantics, not learned content/encoder qualification."""

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .event_stream import ArrivalStream, EncodedEvent, FrontendIdentity, Prefix, PrefixEncoder


class ProbeCore:
    def __init__(self, width=2):
        self.state = np.zeros(width)
        self.calls = []

    def advance(self, seconds):
        self.calls.append(("advance", seconds))
        self.state *= np.exp(-seconds)

    def observe(self, tokens, modality):
        self.calls.append(("observe", tokens.copy(), modality))
        self.state += tokens.sum(0)

    def query(self, vector):
        return np.array([self.state @ vector])


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.identity = FrontendIdentity("1"*64, "2"*64, "3"*64, 2, 128)

    def event(self, time, order, tokens=((1, 0),), *, source_end=None):
        return EncodedEvent(time, time, time, order, time if source_end is None else source_end,
                            0, "4"*64, self.identity, np.array(tokens))

    def test_simultaneous_contents_survive_without_fake_time(self):
        core = ProbeCore()
        stream = ArrivalStream(core, {0: self.identity})
        stream.push([self.event(1_000_000, 0), self.event(1_000_000, 1, ((0, 2),))])
        self.assertEqual([call[0] for call in core.calls], ["advance", "observe", "observe"])
        np.testing.assert_array_equal(stream.query([1, 0], at_micros=1_000_000), [1])
        np.testing.assert_array_equal(stream.query([0, 1], at_micros=1_000_000), [2])

    def test_async_source_order_does_not_rewrite_past(self):
        core = ProbeCore()
        stream = ArrivalStream(core, {0: self.identity})
        stream.push([self.event(1_000_000, 0, source_end=900_000)])
        first = stream.query([1, 0], at_micros=1_000_000)
        stream.push([self.event(2_000_000, 0, ((0, 2),), source_end=100_000)])
        np.testing.assert_array_equal(first, [1])
        np.testing.assert_allclose(core.state, [np.exp(-1), 2])
        with self.assertRaises(ValueError):
            stream.query([1, 0], at_micros=1_000_000)

    def test_long_interference_and_query_swap_do_not_advance_clock(self):
        core = ProbeCore()
        stream = ArrivalStream(core, {0: self.identity})
        events = [self.event(0, 0, ((1, 2),))]
        events += [self.event(i*1000, 0, ((0, 0),)) for i in range(1, 129)]
        stream.push(events)
        original = core.state.copy()
        a = stream.query([1, 0], at_micros=128_000)
        b = stream.query([0, 1], at_micros=128_000)
        np.testing.assert_array_equal(core.state, original)
        np.testing.assert_allclose(b, 2*a)

    def test_invalid_later_event_rejects_whole_batch_before_effects(self):
        core = ProbeCore()
        stream = ArrivalStream(core, {0: self.identity})
        with self.assertRaises(ValueError):
            stream.push([self.event(10, 0), self.event(9, 1)])
        self.assertEqual(core.calls, [])
        self.assertEqual(stream.time, 0)
        self.assertFalse(stream.poisoned)

    def test_identity_mismatch_and_token_budget_are_atomic(self):
        core = ProbeCore()
        stream = ArrivalStream(core, {0: self.identity}, max_batch_tokens=1)
        with self.assertRaises(ValueError):
            stream.push([replace(self.event(1, 0), frontend=replace(
                self.identity, runtime_sha256="9"*64))])
        with self.assertRaises(ValueError):
            stream.push([self.event(1, 0), self.event(1, 1)])
        self.assertEqual(core.calls, [])

    def test_event_owns_immutable_tokens(self):
        source = np.array([[1., 2.]])
        event = EncodedEvent(1, 1, 1, 0, 1, 0, "4"*64, self.identity, source)
        source[0, 0] = 99
        np.testing.assert_array_equal(event.tokens, [[1, 2]])
        with self.assertRaises(ValueError):
            event.tokens.setflags(write=True)

    def test_replay_and_nonfinite_tokens_reject(self):
        stream = ArrivalStream(ProbeCore(), {0: self.identity})
        event = self.event(0, 0)
        stream.push([event])
        with self.assertRaises(ValueError):
            stream.push([event])
        with self.assertRaises(ValueError):
            self.event(1, 1, ((np.nan, 1),))

    def test_partial_core_failure_poison_requires_recovery(self):
        class Broken(ProbeCore):
            def observe(self, tokens, modality):
                super().observe(tokens, modality)
                raise RuntimeError("lost core reply")
        stream = ArrivalStream(Broken(), {0: self.identity})
        with self.assertRaises(RuntimeError):
            stream.push([self.event(1, 0)])
        self.assertTrue(stream.poisoned)
        with self.assertRaises(RuntimeError):
            stream.push([self.event(1, 0)])
        with self.assertRaises(RuntimeError):
            stream.query([1, 0], at_micros=1)

    def test_prefix_is_cropped_before_encoding_and_weights_checked(self):
        payload = b"visible prefix"
        checkpoint = b"fixture weights, not a pretrained encoder"
        identity = replace(self.identity, checkpoint_sha256=hashlib.sha256(checkpoint).hexdigest())
        observed = []
        def encode(raw):
            observed.append(raw)
            return [[len(raw), 1.]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"weights"
            path.write_bytes(checkpoint)
            clock = iter([170, 210])
            encoder = PrefixEncoder(identity, path, encode, clock_micros=lambda: next(clock))
            event = encoder.encode(Prefix(payload, 0, 100, 150), order=0, modality=0)
            self.assertEqual(observed, [payload])
            self.assertEqual((event.raw_arrival_micros, event.encode_started_micros,
                              event.ready_micros), (150, 170, 210))
            stream = ArrivalStream(ProbeCore(), {0: identity})
            stream.push([event])
            with self.assertRaises(ValueError):
                stream.query([1, 0], at_micros=200)
            self.assertEqual(event.prefix_sha256, hashlib.sha256(payload).hexdigest())
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                PrefixEncoder(identity, path, encode, clock_micros=lambda: 300)
        with self.assertRaises(ValueError):
            Prefix(payload, 0, 151, 150)

    def test_wide_real_frontend_dimensions_are_preserved(self):
        for width in (768, 1536):
            with self.subTest(width=width):
                identity = replace(self.identity, width=width)
                tokens = np.arange(3*width, dtype=float).reshape(3, width)
                event = EncodedEvent(0, 0, 0, 0, 0, 0, "4"*64, identity, tokens)
                core = ProbeCore(width)
                ArrivalStream(core, {0: identity}).push([event])
                np.testing.assert_array_equal(core.calls[0][1], tokens)

    def test_chunking_preserves_events_and_query_time(self):
        events = [self.event(0, 0), self.event(100, 0), self.event(100, 1), self.event(300, 0)]
        full_core, chunk_core = ProbeCore(), ProbeCore()
        full = ArrivalStream(full_core, {0: self.identity})
        chunk = ArrivalStream(chunk_core, {0: self.identity})
        full.push(events)
        chunk.push(events[:2])
        chunk.push(events[2:])
        np.testing.assert_array_equal(full.query([1, 1], at_micros=400),
                                      chunk.query([1, 1], at_micros=400))
        self.assertEqual((full.time, full.last_order), (400, -1))
        with self.assertRaises(ValueError):
            chunk.push([self.event(399, 0)])

    def test_interrupted_partial_operation_cannot_replay(self):
        class Interrupted(ProbeCore):
            def observe(self, tokens, modality):
                super().observe(tokens, modality)
                raise KeyboardInterrupt("interrupted after mutation")
        core = Interrupted()
        stream = ArrivalStream(core, {0: self.identity})
        event = self.event(0, 0)
        with self.assertRaises(KeyboardInterrupt):
            stream.push([event])
        self.assertTrue(stream.poisoned)
        with self.assertRaises(RuntimeError):
            stream.push([event])
        self.assertEqual(len(core.calls), 1)

    def test_interrupted_query_after_advance_poisons(self):
        class Interrupted(ProbeCore):
            def query(self, vector):
                raise KeyboardInterrupt("lost readout")
        stream = ArrivalStream(Interrupted(), {0: self.identity})
        with self.assertRaises(KeyboardInterrupt):
            stream.query([1, 0], at_micros=1)
        with self.assertRaises(RuntimeError):
            stream.query([1, 0], at_micros=1)

    def test_reversed_ready_clock_rejects(self):
        with self.assertRaises(ValueError):
            replace(self.event(100, 0), ready_micros=99)

    def test_ready_clock_follows_lazy_token_materialization(self):
        now = [100]
        class LazyTokens:
            def __array__(self, dtype=None, copy=None):
                now[0] = 900
                return np.array([[7., 0.]], dtype=dtype)
        weights = b"fixture only"
        identity = replace(self.identity, checkpoint_sha256=hashlib.sha256(weights).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"weights"
            path.write_bytes(weights)
            encoder = PrefixEncoder(identity, path, lambda raw: LazyTokens(),
                                    clock_micros=lambda: now[0])
            event = encoder.encode(Prefix(b"prefix", 0, 50, 100), order=0, modality=0)
            self.assertEqual((event.encode_started_micros, event.ready_micros), (100, 900))
            np.testing.assert_array_equal(event.tokens, [[7., 0.]])
            stream = ArrivalStream(ProbeCore(), {0: identity})
            stream.push([event])
            with self.assertRaises(ValueError):
                stream.query([1, 0], at_micros=100)
            np.testing.assert_array_equal(stream.query([1, 0], at_micros=900), [7.])

    def test_query_seals_all_events_at_its_ready_time(self):
        stream = ArrivalStream(ProbeCore(), {0: self.identity})
        np.testing.assert_array_equal(stream.query([1, 0], at_micros=0), [0])
        with self.assertRaises(ValueError):
            stream.push([self.event(0, 99)])
        stream.push([self.event(1, 0), self.event(1, 1, ((0, 2),))])
        first = stream.query([1, 0], at_micros=1)
        second = stream.query([0, 1], at_micros=1)
        np.testing.assert_array_equal(first, [1])
        np.testing.assert_array_equal(second, [2])
        with self.assertRaises(ValueError):
            stream.push([self.event(1, 2, ((7, 0),))])


if __name__ == "__main__":
    unittest.main()
