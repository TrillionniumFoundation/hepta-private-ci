"""Adversarial/source-only tests. All model and answer material is synthetic."""
import copy
import hashlib
import unittest

from stem_selection_v7 import (
    ARM_SLOTS, SLOTS, RECEIPT_SCHEMA, audit_source_first_receipts, build_plan,
    cache_identity, group_reuse, validate_plan, weight_budget,
)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def material():
    return {slot: dict(repo="fixtures/" + slot, revision=h(slot)[:40],
                       weights_sha256=h(slot + "-weights"), tokenizer_sha256=h(slot + "-tok"),
                       preprocess_sha256=h(slot + "-prep")) for slot in SLOTS}


def cases():
    return [dict(case_id="c1", family_id="independent-family-1", source_sha256=h("source1"),
                 question_sha256=h("q1"), modalities=["image", "text"]),
            dict(case_id="c2", family_id="independent-family-2", source_sha256=h("source2"),
                 question_sha256=h("q2"), modalities=["audio", "text"])]


def fixture():
    plan = build_plan(models=material(), cases=cases(), reader_sha256=h("reader"))
    runs = {}
    for arm, slot in ARM_SLOTS.items():
        runs[arm] = {
            "model_slot": slot, "material": copy.deepcopy(plan["models"][slot]),
            "head_parameters": 10_000,
            "optimizer_steps": 100 if arm == "multimodal_learned" else 0,
            "head_sha256": h("common-head") if arm in ("shared_421", "replicated_421") else h(arm + "-head"),
            "cases": [dict(case_id=c["case_id"], source_sha256=c["source_sha256"],
                           question_sha256=c["question_sha256"],
                           answer_sha256=h(("legacy-answer" if arm in ("shared_421", "replicated_421") else arm) + c["case_id"]), input_sha256=h(("native-input" if arm in ("multimodal_frozen", "multimodal_learned") else
                                                   "legacy-input" if arm in ("shared_421", "replicated_421") else
                                                   "input" + arm) + c["case_id"]),
                           reader_input_tokens=100, reader_output_tokens=10) for c in plan["cases"]],
            "cost": dict(cpu_seconds=1.5, wall_seconds=1.0, peak_rss_bytes=100000,
                         stem_forwards=2, head_forwards=2, energy_joules=None),
        }
    return plan, {"schema": RECEIPT_SCHEMA, "plan_id": plan["plan_id"],
                  "mode": "synthetic_fixture", "arms": runs}


def cache(**updates):
    r = dict(principal="alpha", purpose="medical", generation=1, authority_epoch=10,
             model_revision=h("rev")[:40], weights_sha256=h("weights"),
             tokenizer_sha256=h("tok"), preprocess_sha256=h("prep"),
             modality="text", input_sha256=h("source"))
    r.update(updates)
    return r


class PlanTests(unittest.TestCase):
    def test_plan_is_source_only_and_non_promoting(self):
        plan, _ = fixture()
        validate_plan(plan)
        self.assertFalse(plan["authority"]["production_authorized"])
        self.assertEqual(plan["independent_families"], 2)
        self.assertEqual(plan["control"]["min_independent_groups_for_superiority"], 200)

    def test_plan_tampered_id_fails(self):
        p, _ = fixture()
        p["per_cell_head_cap"] += 1
        with self.assertRaises(ValueError): validate_plan(p)

    def test_plan_rehashed_unapproved_schema_fails(self):
        p, _ = fixture()
        p["authority"]["production_authorized"] = True
        from stem_selection_v7 import _hash
        p["plan_id"] = _hash({k: v for k, v in p.items() if k != "plan_id"})
        with self.assertRaises(ValueError): validate_plan(p)

    def test_label_in_case_denied(self):
        c = cases()
        c[0]["gold"] = "answer"
        with self.assertRaises(ValueError): build_plan(models=material(), cases=c, reader_sha256=h("reader"))

    def test_duplicate_case_denied(self):
        c = cases() + [cases()[0]]
        with self.assertRaises(ValueError): build_plan(models=material(), cases=c, reader_sha256=h("reader"))

    def test_unpinned_backbone_denied(self):
        m = material()
        m["legacy421"]["revision"] = "some-tag"
        with self.assertRaises(ValueError): build_plan(models=m, cases=cases(), reader_sha256=h("reader"))

    def test_bool_head_budget_denied(self):
        with self.assertRaises(ValueError): build_plan(models=material(), cases=cases(), reader_sha256=h("reader"), head_cap=True)


class CacheTests(unittest.TestCase):
    def test_deduplicates_exact_shared_request(self):
        r = cache()
        self.assertEqual(group_reuse([r, dict(r), r]), dict(logical_cell_uses=3, unique_encoder_inputs=1, max_reuse=3, reuses=2))

    def test_denies_cross_principal_reuse(self):
        self.assertNotEqual(cache_identity(cache()), cache_identity(cache(principal="beta")))

    def test_denies_cross_purpose_reuse(self):
        self.assertNotEqual(cache_identity(cache()), cache_identity(cache(purpose="finance")))

    def test_denies_generation_epoch_or_modality_reuse(self):
        for kw in [dict(generation=2), dict(authority_epoch=11), dict(modality="image"),
                   dict(input_sha256=h("changed")), dict(preprocess_sha256=h("changed"))]:
            self.assertNotEqual(cache_identity(cache()), cache_identity(cache(**kw)))

    def test_denies_omitted_tokenizer_identity(self):
        r = cache()
        del r["tokenizer_sha256"]
        with self.assertRaises(ValueError): cache_identity(r)

    def test_no_empty_batch(self):
        with self.assertRaises(ValueError): group_reuse([])


class BudgetTests(unittest.TestCase):
    def test_4096_head_bytes_not_a_physical_rss_claim(self):
        r = weight_budget(backbone_params=97_441_152, cells=4096, head_params=10000,
                          active_train_heads=32, bridge_params=4096)
        self.assertEqual(r["backbone_weight_bytes"], 194_882_304)
        self.assertEqual(r["head_weight_bytes"], 81_920_000)
        self.assertEqual(r["active_head_training_state_upper_example_bytes"], 5_120_000)
        self.assertIsNone(r["observed_rss"])

    def test_allocation_rejects_more_training_heads_than_cells(self):
        with self.assertRaises(ValueError): weight_budget(backbone_params=10, cells=2, head_params=20, active_train_heads=3)

    def test_parameter_estimate_not_fictitious_latency(self):
        r = weight_budget(backbone_params=421_000_000, cells=4096, head_params=10000, copies=4096)
        self.assertIsNone(r["observed_latency"])
        self.assertEqual(r["backbone_weight_bytes"], 3_448_832_000_000)


class AuditTests(unittest.TestCase):
    def test_complete_receipt_is_still_a_scientific_no_go(self):
        p, b = fixture()
        o = audit_source_first_receipts(p, b)
        self.assertEqual(o["arms_counted"], len(ARM_SLOTS))
        self.assertEqual(o["questions_per_arm"], 2)
        self.assertEqual(o["costs"]["granite_head"]["reader_input_tokens"], 200)
        self.assertFalse(o["authenticated_original_model_host"])
        self.assertFalse(o["stem_winner_verified"])

    def test_missing_arm_denied(self):
        p, b = fixture()
        del b["arms"]["multimodal_shuffled"]
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_source_or_question_changed_denied(self):
        for key in ("source_sha256", "question_sha256"):
            p, b = fixture()
            b["arms"]["text_only"]["cases"][0][key] = h("different")
            with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_material_swap_denied(self):
        p, b = fixture()
        b["arms"]["gemma_text_head"]["material"] = b["arms"]["granite_head"]["material"]
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_gold_smuggling_denied(self):
        p, b = fixture()
        b["arms"]["text_only"]["cases"][0]["gold"] = "secret"
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_duplicate_original_answer_denied(self):
        p, b = fixture()
        b["arms"]["text_only"]["cases"][1] = b["arms"]["text_only"]["cases"][0]
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_no_fake_frozen_training(self):
        p, b = fixture()
        b["arms"]["multimodal_frozen"]["optimizer_steps"] = 2
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_no_fake_trained_without_steps(self):
        p, b = fixture()
        b["arms"]["multimodal_learned"]["optimizer_steps"] = 0
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_nan_and_negative_metrics_denied(self):
        for k, v in (("cpu_seconds", float("nan")), ("wall_seconds", -1), ("stem_forwards", -1), ("peak_rss_bytes", True)):
            p, b = fixture()
            b["arms"]["text_only"]["cost"][k] = v
            with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_unattested_mode_denied(self):
        p, b = fixture()
        b["mode"] = "physically_verified_production"
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_replication_head_drift_denied(self):
        p, b = fixture()
        b["arms"]["replicated_421"]["head_sha256"] = h("different")
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_replication_input_or_output_drift_denied(self):
        for k in ("input_sha256", "answer_sha256"):
            p, b = fixture()
            b["arms"]["replicated_421"]["cases"][0][k] = h("different")
            with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_modality_head_training_does_not_change_encoder_input(self):
        p, b = fixture()
        b["arms"]["multimodal_learned"]["cases"][0]["input_sha256"] = h("different")
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_modality_lesion_cannot_be_unchanged_input(self):
        p, b = fixture()
        b["arms"]["multimodal_lesion"]["cases"][0]["input_sha256"] = b["arms"]["multimodal_learned"]["cases"][0]["input_sha256"]
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_stem_heads_are_physically_parameter_matched(self):
        p, b = fixture()
        b["arms"]["mmbert_head"]["head_parameters"] -= 1
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_head_budget_denied(self):
        p, b = fixture()
        b["arms"]["granite_head"]["head_parameters"] = 10_001
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_reader_tokens_cannot_be_boolean(self):
        p, b = fixture()
        b["arms"]["gemma_text_head"]["cases"][0]["reader_input_tokens"] = True
        with self.assertRaises(ValueError): audit_source_first_receipts(p, b)

    def test_synthetic_bundles_do_not_claim_real_model(self):
        p, b = fixture()
        b["mode"] = "original_physical_unverified"
        self.assertFalse(audit_source_first_receipts(p, b)["stem_winner_verified"])


if __name__ == "__main__":
    unittest.main()
