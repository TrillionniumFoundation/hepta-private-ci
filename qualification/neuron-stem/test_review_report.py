"""Offline report construction tests use fabricated schema fixtures only."""
import json
from pathlib import Path
import tempfile
import unittest

from review_report import (
    make_quality_summary, make_resource_summary, markdown_report, review_report,
)


MODEL = "jina-v5-text-nano"
REVISION = "a" * 40


def quality():
    return {
        "schema": "hepta.neuron-stem-paired-statistical-gate.v1",
        "candidate_model": MODEL, "candidate_revision": REVISION,
        "offline_quality_gate_passed": True, "cell_learning_gate_passed": True,
        "matched_frozen_head_present": True,
        "production_promotion_permitted": False,
        "ndu_independent_signature_verified": False,
        "task_regressions": [], "frozen_head_regressions": [],
        "evaluation": {
            "future": {"independent_groups": 40, "paired_group_bootstrap": {
                "accuracy_gain": {"estimate": .1, "ci_95": [.02, .15]},
                "brier_delta": {"estimate": -.15, "ci_95": [-.20, -.02]},
            }},
        },
    }


def resource(cells=4096):
    return {
        "schema": "hepta.neuron-research-paired-resource-gate.v1",
        "candidate_model": MODEL, "candidate_revision": REVISION,
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "production_microbatch_qualified": False,
        "production_recovery_qualified": False,
        "research_resource_gate_passed": True,
        "scale": {
            "logical_cells": cells, "active_heads": 256,
            "distinct_ticked_cells": 256,
            "measured_active_cell_coverage": True,
        },
        "metrics": {
            "candidate_rss_bytes": 750000000,
            "candidate_max_stage_p99_ms": 35.,
            "candidate_throughput_rps": 125.,
        },
    }


def registry():
    return json.loads(Path(__file__).with_name("models.json").read_text(encoding="utf-8"))


class ReviewTests(unittest.TestCase):
    def test_empty_manifest_retains_no_change_and_explicit_missing_data(self):
        out = review_report(
            registry(), {"schema": "hepta.neuron-stem-review-input.v1", "candidates": []},
            Path("."))
        self.assertEqual(out["rows"][0]["model_id"], "no-change")
        self.assertEqual(out["rows"][0]["decision"], "保留")
        self.assertFalse(out["production_promotion_permitted"])
        self.assertTrue(all(r["decision"] == "未判定" for r in out["rows"][1:]))
        self.assertIn("待测", markdown_report(out))
        self.assertIn("4096逻辑Cell", markdown_report(out))

    def test_complete_offline_evidence_remains_shadow_and_ndu_unproven(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quality.json").write_text(json.dumps(quality()), encoding="utf-8")
            (root / "resource.json").write_text(json.dumps(resource()), encoding="utf-8")
            manifest = {
                "schema": "hepta.neuron-stem-review-input.v1",
                "candidates": [{
                    "model_id": MODEL,
                    "quality_receipt": "quality.json",
                    "resource_receipt": "resource.json",
                }],
            }
            result = review_report(registry(), manifest, root)
        row = next(r for r in result["rows"] if r["model_id"] == MODEL)
        self.assertTrue(row["cell_learning_gate_passed"])
        self.assertTrue(row["research_resource_gate_passed"])
        self.assertEqual(row["future_ndu_gain"], "待独立因果证据")
        self.assertEqual(row["research_4096_throughput_rps"], 125.)
        self.assertEqual(row["decision"], "Shadow研究通过；NDU与生产待证")
        self.assertEqual(row["resource_active_heads"], 256)
        self.assertIn("活跃256", markdown_report(result))
        self.assertFalse(row["production_promotion_permitted"])
        self.assertFalse(result["evaluator_signatures_verified"])

    def test_earlier_scale_does_not_invent_4096_throughput(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quality.json").write_text(json.dumps(quality()), encoding="utf-8")
            (root / "resource.json").write_text(json.dumps(resource(256)), encoding="utf-8")
            result = review_report(registry(), {
                "schema": "hepta.neuron-stem-review-input.v1",
                "candidates": [{
                    "model_id": MODEL, "quality_receipt": "quality.json",
                    "resource_receipt": "resource.json",
                }],
            }, root)
        row = next(r for r in result["rows"] if r["model_id"] == MODEL)
        self.assertIsNone(row["research_4096_throughput_rps"])
        self.assertEqual(row["resource_scale"], 256)
        self.assertEqual(row["decision"], "待4096 Cell实测")

    def test_mismatched_revision_or_claimed_authority_rejected(self):
        result = quality()
        result["production_promotion_permitted"] = True
        with self.assertRaisesRegex(ValueError, "production/NDU"):
            make_quality_summary(MODEL, result)
        result = quality()
        result["candidate_revision"] = "floating-main"
        with self.assertRaisesRegex(ValueError, "unpinned"):
            make_quality_summary(MODEL, result)
        r = resource()
        r["candidate_revision"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "revision differs"):
            make_resource_summary(MODEL, REVISION, r)
        r = resource()
        r["scale"]["distinct_ticked_cells"] = 128
        with self.assertRaisesRegex(ValueError, "complete active-set"):
            make_resource_summary(MODEL, REVISION, r)

    def test_manifest_receipt_cannot_escape_approved_evidence_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = {
                "schema": "hepta.neuron-stem-review-input.v1",
                "candidates": [{
                    "model_id": MODEL, "quality_receipt": "../unapproved.json",
                }],
            }
            with self.assertRaisesRegex(ValueError, "escapes"):
                review_report(registry(), manifest, root)

    def test_manifests_cannot_inject_unknown_models_or_duplicate_inputs(self):
        with self.assertRaisesRegex(ValueError, "unknown candidate"):
            review_report(registry(), {
                "schema": "hepta.neuron-stem-review-input.v1",
                "candidates": [{"model_id": "unregistered"}],
            }, Path("."))
        with self.assertRaisesRegex(ValueError, "duplicate candidate"):
            review_report(registry(), {
                "schema": "hepta.neuron-stem-review-input.v1",
                "candidates": [{"model_id": MODEL}, {"model_id": MODEL}],
            }, Path("."))


if __name__ == "__main__":
    unittest.main()
