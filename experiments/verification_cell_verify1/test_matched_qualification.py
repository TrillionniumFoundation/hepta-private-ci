"""Counterexamples for prospective VERIFY paired selection qualification."""

from copy import deepcopy
import hashlib
import hmac
import json
import unittest

from .matched_qualification import analyze_matched


def sha(key):
    return hashlib.sha256(key.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def design_receipt(manifest):
    """Controlled authentication fixture; no independent field authority."""
    receipt = {
        "schema": "hepta.verify.cluster-randomization.v1",
        "manifest_sha256": sha(canonical(manifest)),
        "assignment_sha256": sha(
            canonical(sorted(manifest["pairs"], key=lambda p: p["pair_id"]))
        ),
        "method": "independent_fair_cluster_coin",
        "authority_id": "fixture-study-registrar",
        "frozen_ns": manifest["freeze_ns"],
        "evidence_sha256": sha("original-fixture-allocation"),
    }
    receipt["attestation"] = hmac.new(
        b"public-engineering-test-key", canonical(receipt).encode(), hashlib.sha256
    ).hexdigest()
    return receipt


def verify_fixture_design(manifest, receipt):
    payload = {key: value for key, value in receipt.items() if key != "attestation"}
    expected = hmac.new(
        b"public-engineering-test-key", canonical(payload).encode(), hashlib.sha256
    ).hexdigest()
    return receipt["authority_id"] == "fixture-study-registrar" and hmac.compare_digest(
        receipt["attestation"], expected
    )


def example(n=8, clusters=None):
    base, candidate = "fixed", "voi"
    manifest = {
        "schema": "hepta.verify.matched-qualification.v1",
        "source_sha256": sha("source"),
        "target_sha256": sha("fixed-horizon-policy"),
        "continuation_policy_sha256": sha("no-interrupt-until-horizon"),
        "horizon_end": 3,
        "risk_model_sha256": sha("risk"),
        "checker_model_sha256": sha("checker"),
        "scheduler_sha256": sha("scheduler"),
        "evaluator_id": "external-readback",
        "evaluator_version_sha256": sha("evaluator"),
        "baseline": base,
        "candidate": candidate,
        "pairs": [
            {
                "pair_id": f"case{i}",
                "cluster_id": f"cluster{clusters[i] if clusters else i}",
                "first_arm": base
                if (clusters[i] if clusters else i) % 2
                else candidate,
                "environment_a": f"env{i}a",
                "environment_b": f"env{i}b",
            }
            for i in range(n)
        ],
        "losses": {
            "accept": {"correct": 0.0, "error": 1.0},
            "reject": {"correct": 1.0, "error": 0.0},
            "interrupted": {"correct": 0.7, "error": 0.7},
            "unknown": {"correct": 0.6, "error": 0.6},
        },
        "criteria": {
            "max_error_increase_per_task": 0.0,
            "min_candidate_coverage": 0.5,
            "max_coverage_drop": 0.05,
            "min_terminal_error_reduction_per_task": 0.1,
            "min_mean_gain": 0.5,
            "max_one_sided_p": 0.05,
        },
        "freeze_ns": 100,
        "cost_unit": "frozen-utility",
    }
    rows = []
    for p in manifest["pairs"]:
        for arm, err in ((base, True), (candidate, False)):
            env = p["environment_a"] if arm == p["first_arm"] else p["environment_b"]
            rows.append(
                {
                    "pair_id": p["pair_id"],
                    "arm": arm,
                    "environment_id": env,
                    "disposition": "accept",
                    "terminal_error": err,
                    "label_evidence_sha256": sha(p["pair_id"] + arm + "label"),
                    "label_issued_ns": 120,
                    "label_observed_step": 3,
                    "decision_issued_ns": 110,
                    "evaluator_id": "external-readback",
                    "label_attestation": "signed-receipt-stub-do-not-use-in-production",
                    "cost_units": 0.1 if arm == candidate else 0,
                    "cost_roster_sha256": sha(p["pair_id"] + arm + "roster"),
                    "cost_receipt_sha256": sha(p["pair_id"] + arm + "cost"),
                    "source_sha256": sha("source"),
                }
            )
    return manifest, rows


class MatchedQualificationTests(unittest.TestCase):
    def analyze(self, manifest, rows, **kwargs):
        arguments = dict(
            verify_label=lambda m, row: True,
            verify_cost=lambda m, row: True,
            design=design_receipt(manifest),
            verify_design=verify_fixture_design,
        )
        arguments.update(kwargs)
        return analyze_matched(manifest, rows, **arguments)

    def test_positive_paired_signal_is_only_reviewable_not_promoted(self):
        m, rows = example()
        result = self.analyze(m, rows)
        self.assertAlmostEqual(result["paired_mean_loss_improvement"], 0.9)
        self.assertEqual(result["paired_group_signflip_one_sided_p"], 1 / 256)
        self.assertTrue(result["gates"]["independent_randomized_design_authenticated"])
        self.assertTrue(result["gates"]["externally_reviewable"])
        self.assertEqual(result["scientific_admission"], "HOLD")
        self.assertEqual(result["production_authority"], "NONE")
        self.assertFalse(result["independent_custody_established_by_this_code"])

    def test_label_and_cost_authentication_do_not_prove_randomization(self):
        m, rows = example()
        result = analyze_matched(
            m, rows, verify_label=lambda *args: True, verify_cost=lambda *args: True
        )
        self.assertFalse(result["gates"]["externally_reviewable"])
        self.assertFalse(result["gates"]["paired_statistical_threshold"])
        self.assertIsNone(result["paired_group_signflip_one_sided_p"])
        self.assertEqual(result["conditional_group_signflip_one_sided_p"], 1 / 256)
        self.assertFalse(result["conditional_signflip_is_inferential_evidence"])

    def test_design_requires_bound_receipt_and_literal_authentication(self):
        m, rows = example()

        def unavailable(*args):
            raise RuntimeError("independent registrar unavailable")

        for callback in (
            None,
            lambda *args: False,
            lambda *args: 1,
            lambda *args: "True",
            unavailable,
        ):
            with self.subTest(callback=callback):
                result = self.analyze(m, rows, verify_design=callback)
                self.assertFalse(
                    result["gates"]["independent_randomized_design_authenticated"]
                )
                self.assertFalse(result["gates"]["externally_reviewable"])
                self.assertIsNone(result["paired_group_signflip_one_sided_p"])
        result = self.analyze(m, rows, design=None, verify_design=lambda *args: True)
        self.assertFalse(result["gates"]["frozen_design_receipt_bound"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_design_rejects_changed_criteria_assignment_issuer_or_signature(self):
        m, rows = example()
        receipt = design_receipt(m)
        changes = [
            {"manifest_sha256": sha("another-study")},
            {"assignment_sha256": sha("another-allocation")},
            {"method": "selected_after_outcomes"},
            {"frozen_ns": m["freeze_ns"] + 1},
            {"authority_id": "checked-component"},
            {"attestation": "self-attested"},
            {"evidence_sha256": sha("substituted-evidence")},
            {"independent": True},
        ]
        for change in changes:
            with self.subTest(change=change):
                result = self.analyze(m, rows, design={**receipt, **change})
                self.assertFalse(result["gates"]["externally_reviewable"])
        m["criteria"]["max_one_sided_p"] = 1
        result = self.analyze(m, rows, design=receipt)
        self.assertFalse(result["gates"]["frozen_design_receipt_bound"])

    def test_whole_cluster_test_refuses_pairwise_mixed_assignments(self):
        m, rows = example(16, clusters=[i // 2 for i in range(16)])
        for index, pair in enumerate(m["pairs"]):
            if index % 2:
                pair["first_arm"] = "voi" if pair["first_arm"] == "fixed" else "fixed"
                for row in rows[2 * index : 2 * index + 2]:
                    row["environment_id"] = (
                        pair["environment_a"]
                        if row["arm"] == pair["first_arm"]
                        else pair["environment_b"]
                    )
        result = self.analyze(m, rows)
        self.assertEqual(result["conditional_group_signflip_one_sided_p"], 1 / 256)
        self.assertFalse(result["gates"]["whole_cluster_assignment_consistent"])
        self.assertFalse(result["gates"]["paired_statistical_threshold"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_authentication_cannot_change_frozen_inputs(self):
        m, rows = example()

        def mutate_manifest(manifest, receipt):
            manifest["criteria"]["max_one_sided_p"] = 1
            return True

        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.analyze(m, rows, verify_design=mutate_manifest)
        m, rows = example()

        def mutate_receipt(manifest, receipt):
            receipt["authority_id"] = "different-authority"
            return True

        with self.assertRaisesRegex(ValueError, "design changed"):
            self.analyze(m, rows, verify_design=mutate_receipt)
        m, rows = example()

        def mutate_observation(manifest, row):
            row["cost_units"] = 0.123
            return True

        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.analyze(m, rows, verify_label=mutate_observation)

    def test_zero_net_benefit_does_not_qualify_with_zero_frozen_minimum(self):
        m, rows = example()
        m["criteria"].update(min_mean_gain=0, max_one_sided_p=1)
        for row in rows:
            row["cost_units"] = 1 if row["arm"] == "voi" else 0
        result = self.analyze(m, rows)
        self.assertEqual(result["paired_mean_loss_improvement"], 0)
        self.assertTrue(result["gates"]["terminal_error_reduction"])
        self.assertTrue(result["gates"]["paired_statistical_threshold"])
        self.assertFalse(result["gates"]["mean_total_loss_improvement"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_clean_blocked_diagnostics_retain_missing_and_unobserved_tasks(self):
        m, rows = example(4)
        rows[3]["disposition"] = "reject"
        rows[5].update(
            disposition="interrupted",
            terminal_error=None,
            label_evidence_sha256=None,
            label_issued_ns=None,
            label_observed_step=None,
            label_attestation=None,
            evaluator_id=None,
        )
        rows.pop()
        arm = self.analyze(m, rows)["arms"]["voi"]
        self.assertEqual(
            (arm["planned"], arm["observed"], arm["unobserved"]), (4, 3, 1)
        )
        self.assertEqual(
            arm["by_disposition"],
            {
                "accept": {
                    "observed": 1,
                    "known_clean": 1,
                    "known_errors": 0,
                    "missing_labels": 0,
                },
                "reject": {
                    "observed": 1,
                    "known_clean": 1,
                    "known_errors": 0,
                    "missing_labels": 0,
                },
                "interrupted": {
                    "observed": 1,
                    "known_clean": 0,
                    "known_errors": 0,
                    "missing_labels": 1,
                },
                "unknown": {
                    "observed": 0,
                    "known_clean": 0,
                    "known_errors": 0,
                    "missing_labels": 0,
                },
            },
        )
        self.assertEqual(arm["clean_blocked_count_known"], 1)
        self.assertEqual(arm["clean_blocked_per_planned_bounds"], [0.25, 0.75])
        self.assertEqual(arm["clean_blocked_rate_among_known_clean"], 0.5)
        self.assertIsNone(arm["causal_false_interruption_rate"])
        self.assertIsNone(
            self.analyze(m, rows)["arms"]["fixed"][
                "clean_blocked_rate_among_known_clean"
            ]
        )

    def test_no_terminal_error_reduction_never_qualifies(self):
        m, rows = example()
        for row in rows:
            if row["arm"] == "voi":
                row["terminal_error"] = True
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["terminal_error_reduction"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_zero_reduction_threshold_does_not_turn_cost_savings_into_error_reduction(
        self,
    ):
        m, rows = example()
        m["criteria"]["min_terminal_error_reduction_per_task"] = 0.0
        for row in rows:
            row["terminal_error"] = True
            row["cost_units"] = 1.0 if row["arm"] == "fixed" else 0.0
        result = self.analyze(m, rows)
        self.assertEqual(result["terminal_error_rate_reduction"], 0)
        self.assertEqual(result["paired_mean_loss_improvement"], 1)
        self.assertTrue(result["gates"]["paired_statistical_threshold"])
        self.assertFalse(result["gates"]["terminal_error_reduction"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_unequal_clusters_test_the_same_pair_weighted_gain_as_reported(self):
        m, rows = example(101, clusters=list(range(5)) + [5] * 96)
        m["criteria"]["min_terminal_error_reduction_per_task"] = 0.01
        m["criteria"]["min_mean_gain"] = 0.001
        for index, pair in enumerate(m["pairs"]):
            for row in rows[2 * index : 2 * index + 2]:
                row["cost_units"] = 0
                if index >= 5:
                    row["terminal_error"] = False
                    row["cost_units"] = 0.05 if row["arm"] == "voi" else 0
        result = self.analyze(m, rows)
        self.assertAlmostEqual(result["paired_mean_loss_improvement"], 0.2 / 101)
        self.assertEqual(result["paired_group_signflip_one_sided_p"], 0.5)
        self.assertEqual(
            result["signflip_statistic"], "whole_cluster_contributions_to_paired_mean"
        )
        self.assertTrue(result["gates"]["mean_total_loss_improvement"])
        self.assertFalse(result["gates"]["paired_statistical_threshold"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_refuse_reject_everything_even_when_wrong_accepts_fall(self):
        m, rows = example()
        for r in rows:
            if r["arm"] == "voi":
                r["disposition"] = "reject"
                r["terminal_error"] = True
        result = self.analyze(m, rows)
        self.assertEqual(result["arms"]["voi"]["acceptance_coverage"], 0)
        self.assertIsNone(result["arms"]["voi"]["accepted_error_rate_bounds"])
        self.assertFalse(result["gates"]["coverage"])
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_missing_horizon_not_replaced_by_interrupted_disposition(self):
        m, rows = example()
        r = rows[1]
        r.update(
            disposition="interrupted",
            terminal_error=None,
            label_evidence_sha256=None,
            label_issued_ns=None,
            label_observed_step=None,
            label_attestation=None,
            evaluator_id=None,
        )
        result = self.analyze(m, rows)
        self.assertEqual(result["arms"]["voi"]["missing_terminal_labels"], 1)
        self.assertIsNone(result["paired_mean_loss_improvement"])
        self.assertIsNone(result["paired_group_signflip_one_sided_p"])
        self.assertFalse(result["gates"]["horizon_labels_complete"])

    def test_missing_cost_and_not_run_preserved_in_denominator(self):
        m, rows = example()
        rows[0].update(
            cost_units=None, cost_roster_sha256=None, cost_receipt_sha256=None
        )
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["physical_costs_complete_claim_verified"])
        self.assertIsNone(result["paired_mean_loss_improvement"])
        rows.pop()
        result = self.analyze(m, rows)
        self.assertFalse(result["gates"]["roster_complete"])
        self.assertEqual(result["arms"]["voi"]["unobserved"], 1)
        self.assertEqual(result["arms"]["voi"]["planned"], 8)
        self.assertIsNone(result["arms"]["voi"]["acceptance_coverage"])
        self.assertEqual(
            result["arms"]["voi"]["acceptance_coverage_bounds"], [7 / 8, 1]
        )
        self.assertEqual(
            result["arms"]["voi"]["accepted_errors_per_planned_bounds"], [0, 1 / 8]
        )

    def test_callback_missing_or_truthy_string_does_not_verify(self):
        m, rows = example()
        self.assertFalse(analyze_matched(m, rows)["gates"]["externally_reviewable"])
        result = analyze_matched(
            m, rows, verify_label=lambda *args: "True", verify_cost=lambda *args: True
        )
        self.assertFalse(result["gates"]["independent_labels_receipt_authenticated"])

        def raise_error(*args):
            raise RuntimeError("external unavailable")

        result = analyze_matched(
            m, rows, verify_label=raise_error, verify_cost=lambda *args: True
        )
        self.assertFalse(result["gates"]["externally_reviewable"])

    def test_multiple_cases_from_same_template_are_one_stat_group(self):
        m, rows = example(clusters=[0] * 8)
        result = self.analyze(m, rows)
        self.assertEqual(result["cluster_count"], 1)
        self.assertEqual(result["paired_group_signflip_one_sided_p"], 0.5)
        self.assertFalse(result["gates"]["paired_statistical_threshold"])

    def test_forged_or_late_records_fail_closed(self):
        m, rows = example()
        mutations = [
            (0, {"environment_id": "other"}),
            (0, {"source_sha256": sha("other")}),
            (0, {"label_issued_ns": 109}),
            (0, {"label_observed_step": 2}),
            (0, {"decision_issued_ns": 99}),
            (0, {"terminal_error": 1}),
            (0, {"cost_units": True}),
            (0, {"label_evidence_sha256": "missing"}),
            (0, {"disposition": "success"}),
        ]
        for index, patch in mutations:
            with self.subTest(patch=patch):
                broken = deepcopy(rows)
                broken[index].update(patch)
                with self.assertRaises(ValueError):
                    self.analyze(m, broken)
        with self.assertRaises(ValueError):
            self.analyze(m, rows + [deepcopy(rows[0])])
        broken = deepcopy(m)
        broken["pairs"][0]["environment_b"] = broken["pairs"][0]["environment_a"]
        with self.assertRaises(ValueError):
            self.analyze(broken, rows)
        broken = deepcopy(m)
        broken["pairs"][1]["environment_b"] = broken["pairs"][0]["environment_a"]
        with self.assertRaises(ValueError):
            self.analyze(broken, rows)

    def test_unknown_accepted_truth_has_explicit_worst_case(self):
        m, rows = example()
        # A missing terminal label cannot be silently converted into a clean accept.
        rows[1].update(
            terminal_error=None,
            label_evidence_sha256=None,
            label_issued_ns=None,
            label_observed_step=None,
            label_attestation=None,
            evaluator_id=None,
        )
        result = self.analyze(m, rows)
        self.assertEqual(
            result["arms"]["voi"]["accepted_error_rate_bounds"], [0.0, 1 / 8]
        )
        self.assertEqual(
            result["arms"]["voi"]["accepted_errors_per_planned_bounds"], [0, 1 / 8]
        )


if __name__ == "__main__":
    unittest.main()
