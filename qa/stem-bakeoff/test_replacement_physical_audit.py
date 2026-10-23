"""Synthetic structural tests; fixtures never count as observed checkpoints."""
import copy
import json
from pathlib import Path
import unittest

from replacement_gate import EXPECTED, SPLITS, score_rows
from replacement_physical_audit import assess, audit_arm

REGISTRY = json.loads(Path(__file__).with_name("replacement_models.json").read_text())
H = "a" * 64


def fake_scale():
    from replacement_head_scale import SCHEMA, SCALES
    rows = []
    for count in SCALES:
        rows.append(dict(logical_cells=count, head_calls_per_batch=count,
                         simultaneously_executing_heads=1,
                         private_head_instances=count,
                         unique_parameter_storages=2 * count,
                         actual_private_head_tensor_bytes=count * 1024,
                         source_feature_sha256=H,
                         raw_full_fanout_latency_ms=[1.0] * 100,
                         full_batch_p50_ms=1.0, full_batch_p95_ms=1.0,
                         full_batch_p99_ms=1.0,
                         head_outputs_per_second=count * 1000.0,
                         observed_rss_after_allocation_bytes=1000000,
                         observed_rss_after_execution_bytes=1000000,
                         process_high_water_rss_bytes=2000000))
    return dict(schema=SCHEMA, source_feature_sha256=H, measurements=rows,
                model_encoder_forwards_within_probe=0, source_events=1,
                independent_input_event_scaling_measured=False,
                target_device_qualified=False, gpu_observed=False,
                power_energy_observed=False, mode="SHADOW_ONLY",
                authority="DENY_ALL", production_activation_allowed=False)


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
    required = (("rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json")
                if name.startswith("laya_") else ("config.json", "tokenizer.json"))
    compat = (dict(isolation="private_tokenizer_copy_original_weight_symlink",
                   original_tokenizer_inventory_sha256=H,
                   effective_tokenizer_inventory_sha256=H,
                   original_tokenizer_config_sha256=H,
                   effective_tokenizer_config_sha256=H,
                   registered_config_rewrite=False,
                   original_weight_sha256=spec["weight_sha256"],
                   no_original_snapshot_mutation_observed=True)
              if name.startswith("laya_") else None)
    return dict(schema="hepta.neuron.replacement-physical-shadow.v1",
                candidate=name, checkpoint=dict(
                    repository=spec["repository"], revision=spec["revision"],
                    loaded_weight_sha256=spec["weight_sha256"], weight_bytes=200000000,
                    component_sha256={part: H for part in required}),
                loaded_parameter_count=270000000,
                execution_kind="full_policy" if name.startswith("laya_") else "encoder_plus_new_task_head",
                observed_forward_calls=40, source_archive_sha256=H,
                frozen_selected_rows_sha256=H, per_split_limit=8,
                scores=data, head_training=task_head,
                performance=dict(device="cpu", forward_count=40,
                    original_forward_latency_ms=[1.0] * 40,
                    load_ms=200., forward_latency_p50_ms=1.,
                    raw_forward_throughput_per_second=1.0,
                    laya_tokenizer_compat=compat,
                    physical_private_head_scale=(None if name.startswith("laya_")
                                                 else fake_scale())),
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

    def test_missing_physical_tokenizer_digest_is_not_model_identity(self):
        cases = samples()
        del cases["laya_typed_421m"]["checkpoint"]["component_sha256"]["tokenizer/tokenizer.json"]
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")

    def test_publisher_weight_must_match_private_laya_view(self):
        case = fake("laya_english_421m")
        case["performance"]["laya_tokenizer_compat"]["original_weight_sha256"] = H
        errors = audit_arm("laya_english_421m", case,
                           REGISTRY["models"]["laya_english_421m"])
        self.assertTrue(any("original-weight" in x for x in errors))

    def test_missing_or_forged_laya_compatibility_receipt_denied(self):
        case = fake("laya_multi_322m")
        del case["performance"]["laya_tokenizer_compat"]
        errors = audit_arm("laya_multi_322m", case,
                           REGISTRY["models"]["laya_multi_322m"])
        self.assertTrue(any("isolated Laya" in x for x in errors))
        case = fake("laya_typed_421m")
        case["performance"]["laya_tokenizer_compat"]["registered_config_rewrite"] = True
        errors = audit_arm("laya_typed_421m", case,
                           REGISTRY["models"]["laya_typed_421m"])
        self.assertTrue(any("inconsistent tokenizer" in x for x in errors))

    def test_tok_config_and_inventory_rewrite_must_agree(self):
        case = fake("laya_english_421m")
        case["performance"]["laya_tokenizer_compat"]["effective_tokenizer_config_sha256"] = None
        errors = audit_arm("laya_english_421m", case,
                           REGISTRY["models"]["laya_english_421m"])
        self.assertTrue(any("inconsistent tokenizer" in x for x in errors))
        case = fake("laya_multi_322m")
        case["performance"]["laya_tokenizer_compat"]["effective_tokenizer_config_sha256"] = "b" * 64
        case["performance"]["laya_tokenizer_compat"]["registered_config_rewrite"] = True
        errors = audit_arm("laya_multi_322m", case, REGISTRY["models"]["laya_multi_322m"])
        self.assertTrue(any("inconsistent tokenizer" in x for x in errors))

    def test_must_have_four_real_head_scale_receipts_for_encoder_arms(self):
        cases = samples()
        cases["harrier_270m"]["performance"]["physical_private_head_scale"] = None
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")
        cases = samples()
        cases["arctic_305m"]["performance"]["physical_private_head_scale"]["measurements"].pop()
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")

    def test_head_scale_under_sampled_forged_p99_and_storage_alias_denied(self):
        for corrupt in ("sample", "p99", "alias"):
            cases = samples()
            row = cases["harrier_270m"]["performance"]["physical_private_head_scale"]["measurements"][3]
            if corrupt == "sample":
                row["raw_full_fanout_latency_ms"].pop()
            elif corrupt == "p99":
                row["full_batch_p99_ms"] = 0.1
            else:
                row["unique_parameter_storages"] = row["private_head_instances"]
            self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")

    def test_scale_authority_or_parallelism_smuggling_denied(self):
        cases = samples()
        cases["arctic_305m"]["performance"]["physical_private_head_scale"][
            "target_device_qualified"] = True
        self.assertEqual(assess(REGISTRY, cases)["raw_shadow_preflight"], "BLOCKED")
        cases = samples()
        cases["harrier_270m"]["performance"]["physical_private_head_scale"][
            "measurements"][0]["simultaneously_executing_heads"] = 64
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
