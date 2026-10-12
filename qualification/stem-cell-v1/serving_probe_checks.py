"""Actual trained Head arithmetic, explicit synthetic Encoder, no model claims."""
from dataclasses import replace
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

import torch

from development_serving_probe import probe_trained_head
from development_study_data import canonical, write_once
from development_study_replay import replay
from shared_encoder_batch import FrozenFeature
import public_structural_checks as public_checks
from test_shared_encoder_eviction import ToyBackend, request


class TensorFeatureBackend(ToyBackend):
    """Synthetic public-text-hash features passed through real Torch arithmetic."""
    def encode_many(self, texts, representation):
        self.calls.append(tuple(texts))
        x = torch.tensor([[b / 255 for b in hashlib.sha256(t.encode()).digest()[:4]]
                          for t in texts], dtype=torch.float32)
        x = x @ torch.eye(4)
        return [FrozenFeature.from_values(v.tolist(), 1, representation) for v in x]


class ServingProbeChecks(unittest.TestCase):
    setUp = public_checks.ReplayChecks.setUp
    modify_record = public_checks.ReplayChecks.modify_record

    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def run_probe(self, backend=None, requests=None):
        backend = backend or TensorFeatureBackend()
        requests = requests or tuple(request(f"source {i}", str(i)) for i in range(8))
        return probe_trained_head(self.output, self.sealed, requests, backend, self.config)

    def test_three_paths_measure_same_trained_outputs_and_actual_calls(self):
        backend = TensorFeatureBackend()
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.iterdir()}
        result = self.run_probe(backend)
        self.assertEqual(len(result["trials"]), 9)
        self.assertEqual(result["argmax_reversals"], 0)
        for trial in result["trials"]:
            calls, rows = {"serial_no_cache": (32, 32), "serial_reuse": (4, 4),
                           "batch_reuse": (1, 4)}[trial["path"]]
            self.assertEqual((trial["backend_calls"], trial["encoded_rows"]), (calls, rows))
            self.assertEqual(trial["head_evaluated_rows"], 32)
            self.assertGreaterEqual(trial["wall_ns"], sum(b["wall_ns"] for b in trial["batches"]))
        self.assertEqual(len(backend.calls), 111)
        self.assertTrue(result["simulated_encoder"])
        self.assertFalse(result["quality_or_resource_superiority_established"])
        self.assertEqual(hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.iterdir()})

    def test_balanced_position_and_fresh_cache_each_trial(self):
        trials = self.run_probe()["trials"]
        for position in range(3):
            self.assertEqual({trials[3*i+position]["path"] for i in range(3)},
                             {"serial_no_cache", "serial_reuse", "batch_reuse"})
        self.assertEqual([t["encoded_rows"] for t in trials if t["path"] == "batch_reuse"], [4, 4, 4])

    def test_request_outside_probe_slice_is_preflighted(self):
        backend = TensorFeatureBackend()
        items = tuple(request("x", str(i)) for i in range(8))
        items = items[:-1] + (replace(items[-1], scope_digest="8"*64),)
        with self.assertRaisesRegex(ValueError, "mixed serving"):
            self.run_probe(backend, items)
        self.assertEqual(backend.calls, [])

    def test_duplicate_request_is_rejected_before_encoder(self):
        backend = TensorFeatureBackend()
        with self.assertRaisesRegex(ValueError, "duplicate serving"):
            self.run_probe(backend, (request("x", "a"), request("y", "a")))
        self.assertEqual(backend.calls, [])

    def test_changed_checkpoint_is_rejected_before_encoder(self):
        backend = TensorFeatureBackend()
        selected = json.loads((self.output / "selection.json").read_text())["selected_arm"]
        path = self.output / f"{selected}.safetensors"
        path.write_bytes(path.read_bytes() + b"broken")
        with self.assertRaisesRegex(ValueError, "checkpoint bytes"):
            self.run_probe(backend)
        self.assertEqual(backend.calls, [])

    def test_changed_backend_is_rejected_before_encoder(self):
        backend = TensorFeatureBackend()
        backend.encoder_digest = "9"*64
        with self.assertRaisesRegex(ValueError, "backend/version"):
            self.run_probe(backend)
        self.assertEqual(backend.calls, [])

    def test_width_mismatch_is_not_truncated(self):
        with self.assertRaisesRegex(ValueError, "feature/Head width"):
            self.run_probe(ToyBackend())

    def test_batch_dependent_features_cannot_claim_output_parity(self):
        class DriftingBackend(TensorFeatureBackend):
            def encode_many(self, texts, representation):
                result = super().encode_many(texts, representation)
                if len(texts) > 1:
                    return [FrozenFeature.from_values([v + 100 for v in x.values], 1, representation) for x in result]
                return result
        with self.assertRaisesRegex(ValueError, "output parity"):
            self.run_probe(DriftingBackend())

    def attach_v3_probe(self):
        probe = self.run_probe()
        sha = write_once(self.output / "serving-probe.json", probe)
        self.modify_record("run.json", lambda r: r.update(schema="hepta.stem.structural-run.v3",
            snapshot_sha256="1"*64, serving_probe_sha256=sha, real_weights_executed=False))
        return probe

    def test_v3_run_binds_saved_trained_probe(self):
        self.attach_v3_probe()
        result = replay(self.output, self.dataset)["serving_probe"]
        self.assertEqual(result["logical_requests_per_trial"], 32)
        self.assertFalse(result["physical_measurements_attested"])

    def test_rehashed_probe_count_forgery_is_rejected(self):
        self.attach_v3_probe()
        sha = self.modify_record("serving-probe.json", lambda r: r["trials"][0].update(encoded_rows=0))
        self.modify_record("run.json", lambda r: r.update(serving_probe_sha256=sha))
        with self.assertRaisesRegex(ValueError, "totals differ"):
            replay(self.output, self.dataset)

    def test_rehashed_parity_failure_cannot_become_success(self):
        self.attach_v3_probe()
        sha = self.modify_record("serving-probe.json", lambda r: r.update(max_abs_logit_error=2.0))
        self.modify_record("run.json", lambda r: r.update(serving_probe_sha256=sha))
        with self.assertRaisesRegex(ValueError, "parity error"):
            replay(self.output, self.dataset)

    def test_v3_run_without_probe_is_rejected(self):
        self.modify_record("run.json", lambda r: r.update(schema="hepta.stem.structural-run.v3", snapshot_sha256="1"*64))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_scorer_rejects_forged_selected_arm_before_writing_scores(self):
        def changed(r):
            r["selected_arm"] = next(n for n in r["checkpoints"] if n != r["selected_arm"])
        sha = self.modify_record("selection.json", changed)
        self.modify_record("run.json", lambda r: r["sealed"].update(selection_sha256=sha))
        from development_study_review import main
        output = self.root / "scores.json"
        with patch.object(sys, "argv", ["review", "--run", str(self.output), "--dataset", str(self.dataset), "--output", str(output)]):
            with self.assertRaisesRegex(ValueError, "selection does not reproduce"):
                main()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
