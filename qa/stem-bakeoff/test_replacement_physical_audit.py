"""Synthetic structural tests; fixtures never count as observed checkpoints."""
import copy
import json
from pathlib import Path
import unittest

from replacement_gate import EXPECTED, SPLITS, score_rows
from replacement_physical_audit import assess, audit_arm

REGISTRY = json.loads(Path(__file__).with_name("replacement_models.json").read_text())
H = "a" * 64


def fake(name):
    spec = REGISTRY["models"][name]
    data = {}
    for split in SPLITS:
        rows = [dict(source_id=f"{split}-{i}", source_group_id=f"{split}-group-{i}",
                     label=i % 4, probabilities=[.7 if k == i % 4 else .1 for k in range(4)],
                     is_ood=split == "ood", language="en") for i in range(8)]
        data[split] = dict(rows=rows, metrics=score_rows(rows))
    task_head = None if name.startswith("laya_") else dict(
        head_initial_sha256="a" * 64, head_trained_sha256="b" * 64,
        head_parameters=512, optimizer="AdamW", seed=7, steps=200,
        learning_rate=.05, calibration_temperature=1.0,
        calibration_nll_grid={"1.0": .3})
    return dict(schema="hepta.neuron.replacement-physical-shadow.v1",
                candidate=name, checkpoint=dict(
                    repository=spec["repository"], revision=spec["revision"],
                    loaded_weight_sha256=spec["weight_sha256"], weight_bytes=200000000),
                loaded_parameter_count=270000000,
                execution_kind="full_policy" if name.startswith("laya_") else "encoder_plus_new_task_head",
                observed_forward_calls=40, source_archive_sha256=H,
                frozen_selected_rows_sha256=H, per_split_limit=8,
                scores=data, head_training=task_head,
                performance=dict(device="cpu", forward_count=40,
                    original_forward_latency_ms=[1.0] * 40,
                    load_ms=200., forward_latency_p50_ms=1.,
                    raw_forward_throughput_per_second=1.0),
                limits=dict(historical_2014_dataset=True, target_device_qualified=False,
                    prospective_holdout=False, independent_observer_attested=False,
                    retrieval_quality_measured=False, multilingual_quality_measured=False),
                mode="SHADOW_ONLY", authority="DENY_ALL",
                production_activation_allowed=False)


def samples():
    return {name: fake(name) for name in EXPECTED}


class PhysicalAuditTests(unittest.TestCase):
    def test_synthetic_complete_is_still_review_only(self):
        report = assess(REGISTRY, samples())
        self.assertEqual(report["raw_shadow_preflight"], "REVIEW_REQUIRED")
        self.assertFalse(report["production_activation_allowed"])
        self.assertFalse(report["all_six_production_blockers_closed"])
        self.assertEqual(report["authority"], "DENY_ALL")

    def test_metric_forgery_rejected(self):
        cases = samples()
        cases[EXPECTED[0]]["scores"]["future_1"]["metrics"]["accuracy"] = .01
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")

    def test_swapped_row_identity_across_models_rejected(self):
        cases = samples()
        cases[EXPECTED[-1]]["scores"]["future_1"]["rows"][0]["source_id"] = "forged"
        cases[EXPECTED[-1]]["scores"]["future_1"]["metrics"] = score_rows(
            cases[EXPECTED[-1]]["scores"]["future_1"]["rows"])
        self.assertTrue(any("samples differ" in e for e in assess(REGISTRY, cases)["blockers"]))

    def test_encoder_only_cannot_replace_laya_policy(self):
        case = fake(EXPECTED[0])
        case["execution_kind"] = "encoder_plus_new_task_head"
        errors = audit_arm(EXPECTED[0], case, REGISTRY["models"][EXPECTED[0]])
        self.assertTrue(any("encoder-only" in x for x in errors))

    def test_incomplete_pool_and_authorizing_result_rejected(self):
        cases = samples()
        del cases[EXPECTED[2]]
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")
        cases = samples()
        cases[EXPECTED[0]]["production_activation_allowed"] = True
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")

    def test_training_budget_or_token_row_drift_rejected(self):
        cases = samples()
        cases["harrier_270m"]["head_training"]["steps"] = 10
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")
        cases = samples()
        cases["arctic_305m"]["scores"]["future_2"]["rows"][0]["probabilities"] = [1.,1.,0.,0.]
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
