"""Source-only seed-replicate fault tests; neither a model nor authority issuer."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from qualification.cell_meta_execution_af import physical_router_seed_independence as gate
from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_frozen_old as frozen
from qualification.cell_meta_execution_af import physical_router_audit as numeric


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def profiles(*, distinct=False):
    out = {}
    for seed in gate.SEEDS:
        out[seed] = {arm: (digest(arm + (str(seed) if distinct else "w")),
                           digest("pred:" + arm + (str(seed) if distinct else "p")))
                     for arm in gate.ARMS}
    return out


class SeedIndependenceTests(unittest.TestCase):
    def test_nominal_three_seeds_with_identical_weights_collapse_to_one_profile(self):
        r = gate.classify_signatures(profiles())
        self.assertEqual(r["outcome"], "IDENTICAL_NUMERIC_REPLICATES")
        self.assertEqual(r["minimum_unique_profiles"], 1)
        self.assertEqual(r["identical_seed_clusters"]["no_change"], [[41, 47, 53]])
        self.assertFalse(r["statistical_winner_certified"])
        self.assertFalse(r["different_seed_labels_prove_independent_training"])

    def test_distinct_weights_are_not_independent_outcome_evidence(self):
        r = gate.classify_signatures(profiles(distinct=True))
        self.assertEqual(r["outcome"], "NUMERIC_VARIATION_ONLY")
        self.assertEqual(r["minimum_unique_profiles"], 3)
        self.assertFalse(r["independent_outcome_samples_established"])
        self.assertFalse(r["ndu_selection_authorized"])

    def test_partial_repetition_is_reported_per_arm(self):
        p = profiles(distinct=True)
        p[47]["frozen_old_parent"] = p[41]["frozen_old_parent"]
        r = gate.classify_signatures(p)
        self.assertEqual(r["unique_complete_weight_prediction_profiles"]["frozen_old_parent"], 2)
        self.assertEqual(r["identical_seed_clusters"]["frozen_old_parent"], [[41, 47]])

    def test_missing_seed_arm_nonhex_and_digest_only_forgeries_fail(self):
        for patch in (
            lambda p: p.pop(47),
            lambda p: p[47].pop("fixed_router"),
            lambda p: p[41].update({"authority_granted": (digest("grant"), digest("fake"))}),
            lambda p: p[41].update({"adaptive_split": ("f" * 63, digest("pred"))}),
            lambda p: p[41].update({"adaptive_split": ("0" * 64, digest("pred"))}),
            lambda p: p[41].update({"adaptive_split": (digest("one"), "not-a-hash")}),
        ):
            with self.subTest(patch=str(patch)):
                sample = profiles()
                patch(sample)
                with self.assertRaises(numeric.AuditError):
                    gate.classify_signatures(sample)

    def test_rehashed_or_changed_seed_inputs_cannot_be_called_same_data(self):
        p = trial.synthetic_panel(seed=41, rule="conditional", rows=32)
        panels = {seed: copy.deepcopy(p) for seed in gate.SEEDS}
        for seed in gate.SEEDS:
            panels[seed]["source"]["seed"] = seed
        self.assertEqual(len(gate.shared_inputs(panels)), 64)
        for modification in (
            lambda panel: panel["partitions"]["old_train"][0]["features"].__setitem__(0, 1.234),
            lambda panel: panel["partitions"]["future_1"][0].__setitem__("label", 1 - panel["partitions"]["future_1"][0]["label"]),
            lambda panel: panel["source"].__setitem__("stem_sha256", digest("other-model")),
        ):
            changed = copy.deepcopy(panels)
            modification(changed[47])
            with self.assertRaises(numeric.AuditError):
                gate.shared_inputs(changed)

    def test_three_seed_audit_denies_wrong_shared_table_or_authority(self):
        p = trial.synthetic_panel(seed=41, rule="conditional", rows=32)
        panels = {seed: copy.deepcopy(p) for seed in gate.SEEDS}
        for seed in gate.SEEDS:
            panels[seed]["source"]["seed"] = seed
            panels[seed]["source"]["kind"] = "external_unverified"
            panels[seed]["source"]["rule"] = "external"
        reports = {}
        frozen_reports = {}
        bridges = {}
        common = digest("one-shared-feature-table")
        for seed in gate.SEEDS:
            reports[seed] = {
                "seed":seed, "future_window_prospective":False,
                "ndu_selection_authorized":False,
                "training_steps_each_stage":2,
                "results":[{"arm":name,"weights_sha256":digest(name),
                            "prediction_sha256":digest("pred"+name)} for name in gate.ARMS[:-1]]}
            frozen_reports[seed] = {
                "seed":seed, "future_window_prospective":False,
                "ndu_selection_authorized":False,
                "optimizer_steps_old_only":2,
                "weights_sha256":digest("old"),
                "prediction_sha256":digest("old-pred")}
            bridges[seed] = {
                "schema":"hepta.cell-meta-granite-retrospective-bind.v1",
                "panel_seed":seed,"meta_trial_panel_sha256":numeric.digest(panels[seed]),
                "real_encoder_feature_table_sha256":common,
                "future_window_prospective":False,"real_ood_verified":False,
                "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}
        negative = {
            "outcome":"FROZEN_OLD_PARENT_REPLAY_ONLY",
            "existing_v1_no_change_is_frozen":False,
            "training_budget_matched":False,
            "production_admission":"BLOCKED"}
        # This unit verifies ONLY the composed census contract; independent
        # full FP32 original auditors are run by the actual CI integration.
        with patch.object(gate.original_audit, "validate", return_value={"outcome":"NUMERIC_REPLAY_ONLY"}), \
             patch.object(gate.frozen_audit, "validate", return_value=negative):
            report = gate.audit(panels, reports, frozen_reports, bridges)
            self.assertEqual(report["outcome"], "IDENTICAL_NUMERIC_REPLICATES")
            self.assertEqual(report["original_shared_q24_table_digest_claim"], common)
            forged = copy.deepcopy(bridges)
            forged[53]["real_encoder_feature_table_sha256"] = digest("new-table")
            with self.assertRaises(numeric.AuditError):
                gate.audit(panels, reports, frozen_reports, forged)
            forged = copy.deepcopy(reports)
            forged[47]["ndu_selection_authorized"] = True
            with self.assertRaises(numeric.AuditError):
                gate.audit(panels, forged, frozen_reports, bridges)

    def test_actual_old_only_sgd_is_numerically_seed_invariant_on_same_rows(self):
        p = trial.synthetic_panel(seed=41, rule="conditional", rows=32)
        ids = []
        for seed in gate.SEEDS:
            panel = copy.deepcopy(p)
            panel["source"]["seed"] = seed
            model = frozen.run(panel, steps=2)
            ids.append((model["weights_sha256"], model["prediction_sha256"]))
        self.assertEqual(len(set(ids)), 1)


if __name__ == "__main__":
    unittest.main()
