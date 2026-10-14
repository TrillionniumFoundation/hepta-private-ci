"""Fake Encoder/source inputs test replay contract; not real model accuracy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from agnews_paired_shadow import check_panel
import public_agnews_confirmatory as confirm
from public_agnews_panel import select_rows
from sealed_cell_checkpoint import CheckpointError, _canonical, _sha, seal_checkpoint
from sealed_cell_replay import ReplayError, evaluate
from test_sealed_cell_checkpoint import FakeDynamicCell, fake_cell, fixture_args
from embeddinggemma2_shadow import rust_feature_digest_q24


class DummyRunner:
    _verified_local_weights = True  # synthetic test double, not model evidence
    manifest = {"revision": "c"*40, "dimension": 256, "profile": "text"}
    profile_digest = "a"*64

    def __init__(self, sabotage=None):
        self.sabotage = sabotage

    def encode_cells(self, requests):
        rows = []
        for request in requests:
            digest = hashlib.sha256(request["input"]["value"].encode()).digest()
            data = [int(digest[i % 32] - 128) * 9000 for i in range(256)]
            rows.append({
                "cell_id": request["cell_id"],
                "input_digest": request["input"]["sha256"],
                "feature_digest": rust_feature_digest_q24(data),
                "features_q24": data, "pipeline_digest": self.profile_digest,
                "authority": "DENY_ALL", "modality": "text", "role": "classification",
                "requires_new_neuron_profile": False,
                **{k:request[k] for k in ("scope_id", "principal_id", "purpose_id",
                                          "generation", "authority_epoch")},
            })
        if self.sabotage == "swap":
            rows.reverse()
        elif self.sabotage == "wrong_hash":
            rows[0]["feature_digest"] = "0"*64
        elif self.sabotage == "cross_scope":
            rows[0]["scope_id"] = "other"
        return {"evidence_type": "local_weight_execution_unverified_origin",
                "physical_local_model_execution": True,
                "production_promotion": "DENY_ALL",
                "model_revision": self.manifest["revision"],
                "feature_dimension": 256, "cell_requests": len(requests),
                "sentence_transformer_encode_calls": 1, "rows": rows}


def fixtures():
    old = select_rows(
        [{"text": f"old.train.{i}", "label": i%2} for i in range(160)],
        [{"text": f"old.holdout.{i}", "label": i%2} for i in range(160)])
    rows = [{"text": f"new.holdout.{i}", "label": i%2} for i in range(200)]
    digest, _ = check_panel(old)
    with patch.object(confirm, "SOURCE_PANEL_SHA256", digest):
        new = confirm.create_panel(old, rows)
    return old, new, digest


class SealedReplayContract(unittest.TestCase):
    def setUp(self):
        self.mock = patch.dict(sys.modules, {
            "cell_learning": types.SimpleNamespace(
                DynamicCell=FakeDynamicCell,
                rust_candidate_digest=lambda value:_sha(_canonical(value)),
            ),
        })
        self.mock.start()

    def tearDown(self):
        self.mock.stop()

    def run_case(self, *, sabotage=None, original=None, new=None):
        old, holdout, digest = fixtures()
        if original is not None:
            old = original
        if new is not None:
            holdout = new
        with tempfile.TemporaryDirectory() as root, \
             patch.object(confirm, "SOURCE_PANEL_SHA256", digest):
            path = Path(root)/"candidate.json"
            args = dict(fixture_args(), source_panel_digest=digest)
            seal_checkpoint(path, fake_cell(), fake_cell(.002), **args)
            return evaluate(original_panel=old, val2_panel=holdout,
                            runner=DummyRunner(sabotage), bundle_path=path)

    def test_checked_replay_is_new_snapshot_not_historical(self):
        output = self.run_case()
        self.assertEqual(output["case_count"],128)
        self.assertEqual(output["head_optimizer_steps_during_val2_evaluation"],0)
        self.assertTrue(output["full_float64_head_bytes_unchanged_during_replay"])
        self.assertEqual(output["production_promotion"],"DENY_ALL")
        self.assertFalse(output["historical_20261014_head_byte_identity_claimed"])
        self.assertFalse(output["three_chronological_future_windows"])
        self.assertEqual(set(output["arms"]), {
            "gemma2_frozen_head", "gemma2_trained_head",
            "gemma2_trained_head_scaled_1024"})
        self.assertEqual(output["arms"]["gemma2_trained_head"]["metrics"]["cases"],128)

    def test_swapped_cross_scope_or_hash_tamper_rejected(self):
        for sabotage in ("swap","wrong_hash","cross_scope"):
            with self.subTest(sabotage=sabotage), self.assertRaises(ReplayError):
                self.run_case(sabotage=sabotage)

    def test_untrusted_or_cross_source_panel_refused(self):
        old, new, _ = fixtures()
        corrupt = json.loads(json.dumps(new))
        corrupt["cases"][0]["label"] = 1-corrupt["cases"][0]["label"]
        with self.assertRaises((ReplayError, confirm.ConfirmatoryError)):
            self.run_case(new=corrupt)
        corrupt = json.loads(json.dumps(old))
        corrupt["cases"][0]["source_digest"] = "f"*64
        with self.assertRaises((ReplayError, ValueError)):
            self.run_case(original=corrupt)

    def test_fake_model_execution_flag_is_not_sufficient_for_promotion(self):
        output = self.run_case()
        self.assertFalse(output["independent_model_origin_authenticated"])
        self.assertFalse(output["equal_full_lifecycle_cost_authenticated"])
        self.assertIsNone(output["physical_transformer_forward_calls"])


if __name__=="__main__":
    unittest.main()
