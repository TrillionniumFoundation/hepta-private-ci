"""Maximum-menu and partial-compute regressions; all model/data are fixtures.

These tests exercise the existing Group owner's real chunking and forward hooks.
Object construction is bypassed ONLY in fixture setup, never in production or
formal experiment admission. No pretrained performance claim is made here.
"""
from copy import deepcopy
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

import torch
from torch import nn

import five_causal_experiments as c
import five_group_search as g
from experiments.shared_stem_cell.execution import canonical, sha, tensor_digest, parameters
from test_five_group_search import FixedCell, request


class ScalarDigestTests(unittest.TestCase):
    def test_zero_dim_float_can_be_hashed(self):
        value = torch.tensor(0.8, dtype=torch.float32)
        expected = sha(canonical(["torch.float32", []]) + value.reshape(1).numpy().tobytes())
        self.assertEqual(tensor_digest(value), expected)

    def test_scalar_geometry_does_not_alias_single_element_vector(self):
        value = torch.tensor(7, dtype=torch.int64)
        self.assertNotEqual(tensor_digest(value), tensor_digest(value.reshape(1)))

    def test_non_scalar_historical_digest_bytes_preserved(self):
        tensors = [torch.arange(6, dtype=torch.float32).reshape(2, 3),
                   torch.arange(6).reshape(2, 3).t(), torch.zeros(0, 3),
                   torch.ones(3, dtype=torch.bfloat16), torch.tensor([True, False])]
        for value in tensors:
            original = value.detach().cpu().contiguous()
            legacy = sha(canonical([str(original.dtype), list(original.shape)])
                         + original.view(torch.uint8).numpy().tobytes())
            self.assertEqual(tensor_digest(value), legacy)

    def test_scalar_parameter_mutation_changes_model_identity(self):
        cell = FixedCell()
        before = parameters(cell)
        self.assertEqual(before["parameters"], 1)
        with torch.no_grad():
            cell.anchor.add_(0.1)
        self.assertNotEqual(parameters(cell)["sha256"], before["sha256"])


class BoundedEncoder:
    """Instrumented tensor-only stand-in, not a runtime fallback."""
    def __init__(self, maximum_tokens=512, fail_at=None, bad_at=None):
        self.maximum_tokens = maximum_tokens
        self.fail_at, self.bad_at = fail_at, bad_at
        self.model = nn.Identity()
        self.batches = []

    def encode(self, texts):
        if not 1 <= len(texts) <= 32 or len(texts)*self.maximum_tokens > 32768:
            raise ValueError("fixture physical batch cap")
        self.batches.append(list(texts))
        value = self.model(torch.tensor([[float(len(t)), float(sum(t.encode()) % 997)]
                                        for t in texts], dtype=torch.float32))
        if len(self.batches) == self.fail_at:
            raise RuntimeError("fixture error AFTER a counted Encoder forward")
        if len(self.batches) == self.bad_at:
            value[0, 0] = float("nan")
        return value

    def close(self):
        return None


class NativePort:
    def __init__(self, fail=False):
        self.observations = []
        self.fail = fail
        self.requests = []

    def answer(self, packet, *, arm):
        self.requests.append(deepcopy(packet))
        if self.fail:
            raise RuntimeError("fixture unknown Reader work")
        self.observations.append({"model_calls": 2})
        return {"answer": "fixture unmodified answer"}


def owner(maximum_tokens=512, fail_at=None, bad_at=None, reader_fail=False):
    result = object.__new__(g.NativeGroupOwner)
    result.closed = False
    result.encoder = BoundedEncoder(maximum_tokens, fail_at, bad_at)
    result.controller = FixedCell()
    result.encoder_calls = 0
    result.encoder_batches = []
    result.last_run_cost = None
    result.native = NativePort(reader_fail)
    result.spec = {"reader_checkpoint_sha256": "a"*64, "bindings": {},
                   "maximum_reader_calls": 3, "call_cost": .1, "confidence_threshold": .8}
    return result


class MaximumMenuTests(unittest.TestCase):
    def test_eight_sources_all_37_views_keep_original_order(self):
        texts = [g.public_text(v) for v in g.evidence_views(request(8))]
        native = owner()
        actual = native.encode(texts)
        expected = torch.cat([BoundedEncoder().encode([t]) for t in texts])
        self.assertTrue(torch.equal(actual, expected))
        self.assertEqual([len(b) for b in native.encoder.batches], [32, 5])
        self.assertEqual(sum(native.encoder.batches, []), texts)
        self.assertEqual(native.encoder_calls, 2)
        self.assertEqual([r["actual_forwards"] for r in native.encoder_batches], [1, 1])
        self.assertTrue(all("wall_ns" in r["cost"] for r in native.encoder_batches))

    def test_padded_token_ceiling_can_force_smaller_batches(self):
        native = owner(8192)
        actual = native.encode(["fixture "+str(i) for i in range(37)])
        self.assertEqual(actual.shape, (37, 2))
        self.assertEqual([len(b) for b in native.encoder.batches], [4]*9+[1])
        self.assertEqual(native.encoder_calls, 10)

    def test_single_short_request_is_still_one_forward(self):
        native = owner()
        self.assertEqual(native.encode(["fixture"]).shape, (1, 2))
        self.assertEqual(native.encoder_calls, 1)

    def test_failed_second_chunk_returns_no_partial_feature(self):
        native = owner(fail_at=2)
        with self.assertRaises(RuntimeError):
            native.encode(["fixture"]*37)
        self.assertEqual(native.encoder_calls, 2)
        self.assertEqual([r["status"] for r in native.encoder_batches], ["succeeded", "failed"])
        self.assertEqual(len(native.encoder.model._forward_pre_hooks), 0)
        self.assertTrue(all("wall_ns" in r["cost"] for r in native.encoder_batches))

    def test_nonfinite_late_chunk_is_not_accepted(self):
        native = owner(bad_at=2)
        with self.assertRaises(c.Invalid):
            native.encode(["fixture"]*37)
        self.assertEqual(native.encoder_calls, 2)
        self.assertEqual(native.encoder_batches[-1]["status"], "failed")

    def test_deadline_between_chunks_retains_first_cost_and_does_not_retry(self):
        native = owner()
        with patch.object(g.time, "perf_counter", side_effect=[1.0, 2.0, 5.0]):
            with self.assertRaises(c.Invalid):
                native.encode(["fixture"]*37, deadline=4.0)
        self.assertEqual(native.encoder_calls, 1)
        self.assertEqual([len(b) for b in native.encoder.batches], [32])
        self.assertEqual(len(native.encoder_batches), 1)

    def test_closed_owner_and_invalid_inputs_make_no_forward(self):
        for texts in ([], ["fixture"]*38, [""], [3], "not a batch"):
            native = owner()
            with self.assertRaises(c.Invalid):
                native.encode(texts)
            self.assertEqual(native.encoder_calls, 0)
        native = owner(); native.closed = True
        with self.assertRaises(c.Invalid):
            native.encode(["fixture"])
        self.assertEqual(native.encoder_calls, 0)

    def test_expired_deadline_before_first_chunk(self):
        native = owner()
        with self.assertRaises(c.Invalid):
            native.encode(["fixture"], deadline=time.perf_counter()-1)
        self.assertEqual(native.encoder_calls, 0)

    def test_all_system2_controls_reach_reader_at_maximum_menu(self):
        for mode in c.ARMS["system2"]:
            native = owner(); events = []
            result = native.run(request(8), mode=mode, timeout=30, emit=events.append)
            self.assertEqual(result["reader_requests"], 3)
            self.assertEqual([len(b) for b in native.encoder.batches], [32, 5, 1, 1, 1])
            self.assertEqual(result["measured"]["encoder_forwards"], 5)
            self.assertEqual(result["measured"]["reader_forwards"], 6)
            self.assertEqual(result["answer"], "fixture unmodified answer")
            self.assertEqual(len(native.native.requests), 3)

    def test_group_failure_keeps_actual_encoder_cost(self):
        native = owner(fail_at=2); events = []
        with self.assertRaises(RuntimeError):
            native.run(request(8), mode="fixed_budget", timeout=30, emit=events.append)
        self.assertEqual(native.last_run_cost["encoder_forwards"], 2)
        self.assertEqual(native.last_run_cost["reader_requests_attempted"], 0)
        self.assertEqual(native.last_run_cost["reader_forwards"], 0)
        self.assertEqual(len(native.native.requests), 0)

    def test_unknown_reader_work_is_not_recorded_as_zero(self):
        native = owner(reader_fail=True); events = []
        with self.assertRaises(RuntimeError):
            native.run(request(8), mode="fixed_budget", timeout=30, emit=events.append)
        self.assertEqual(native.last_run_cost["encoder_forwards"], 2)
        self.assertEqual(native.last_run_cost["reader_requests_attempted"], 1)
        self.assertEqual(native.last_run_cost["reader_requests_failed"], 1)
        self.assertIsNone(native.last_run_cost["reader_forwards"])
        self.assertEqual(native.last_run_cost["reader_forwards_known_lower_bound"], 0)
        self.assertTrue(any(e["event"] == "reader_failed_or_unknown" for e in events))

    def test_returned_features_do_not_alias_backend_buffer(self):
        native = owner()
        buffer = torch.ones(2, 2)
        native.encoder.encode = lambda texts: buffer
        actual = native.encode(["one", "two"])
        buffer.fill_(999)
        self.assertTrue(torch.equal(actual, torch.ones(2, 2)))


if __name__ == "__main__":
    unittest.main()
