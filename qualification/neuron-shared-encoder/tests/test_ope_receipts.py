"""Contract tests for immutable X/P/Y/Z OPE receipts."""

from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.ope_receipts import (  # noqa: E402
    ContextReceiptV1,
    DelayedOutcomeReceiptV1,
    OPEBudgetV1,
    OPEReceiptError,
    OPEResourceReceiptV1,
    PolicyDecisionReceiptV1,
    REAL_SHADOW,
    SYNTHETIC_SMOKE,
    XYZEpisodeV1,
    canonical_candidate_set_digest,
    estimate_ope,
    validate_xyz_episode,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


STEM = digest("stem")
OBJECTIVE = digest("objective")
BUDGET = digest("budget")
COSTS = digest("costs")
POLICY = digest("policy")
SUPPORT = digest("support")
DELAY = digest("delay")
GIT_BLOB = "a" * 40


def budget() -> OPEBudgetV1:
    return OPEBudgetV1(BUDGET, COSTS, 8, 2048, 1000.0, 200.0, 50.0, 10.0)


def episode(
    index: int,
    *,
    target_propensity: float,
    logging_propensity: float,
    utility: float | None,
    terminality: str = "TERMINAL",
    evidence_class: str = REAL_SHADOW,
) -> XYZEpisodeV1:
    episode_id = f"episode-{index}"
    context = ContextReceiptV1(
        episode_id=episode_id,
        context_digest=digest(f"context:{index}"),
        source_digest=digest(f"source:{index}"),
        source_blob_digest=GIT_BLOB,
        request_digest=digest(f"request:{index}"),
        reader_manifest_digest=digest("reader"),
        source_split="future",
    )
    decision = PolicyDecisionReceiptV1(
        episode_id=episode_id,
        candidate_set_digest=canonical_candidate_set_digest(("target_policy", "baseline")),
        candidate_ids=("target_policy", "baseline"),
        selected_candidate_id="target_policy",
        target_policy_id="target_policy",
        logging_propensity=logging_propensity,
        target_propensity=target_propensity,
        support_digest=SUPPORT,
        budget_digest=BUDGET,
        policy_digest=POLICY,
        policy_principal_id="policy-principal",
    )
    outcome = DelayedOutcomeReceiptV1(
        episode_id=episode_id,
        outcome_id=f"outcome-{index}",
        observer_principal_id="independent-observer",
        observer_signing_key_digest=digest("observer-key"),
        observed_at_unix_ms=100 + index,
        latest_observable_at_unix_ms=120 + index,
        expected_delay_profile_digest=DELAY,
        terminality=terminality,
        utility=utility,
        support_digest=digest(f"outcome-support:{index}"),
        finalized_at_unix_ms=130 + index if terminality == "TERMINAL" else (140 + index if terminality == "CENSORED" else None),
        censoring_reason="timeout" if terminality == "CENSORED" else None,
    )
    resources = OPEResourceReceiptV1(
        episode_id=episode_id,
        budget_digest=BUDGET,
        evidence_class=evidence_class,
        forward_calls=4,
        input_tokens=100,
        flops=100.0,
        peak_memory_bytes=100.0,
        p95_latency_ms=10.0,
        energy_mj=1.0,
        resident_params=1000,
        active_params=100,
    )
    return XYZEpisodeV1(episode_id, context, decision, outcome, resources, evidence_class)


class OPEReceiptTests(unittest.TestCase):
    def test_xyz_receipts_are_separate_and_bound_by_episode_digest(self):
        item = episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0)
        self.assertNotEqual(item.context.receipt_digest, item.decision.receipt_digest)
        self.assertNotEqual(item.outcome.receipt_digest, item.resources.receipt_digest)
        self.assertEqual(len(item.episode_digest), 64)
        validate_xyz_episode(item, budget())

    def test_policy_and_outcome_principals_must_be_independent(self):
        item = episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0)
        bad_outcome = DelayedOutcomeReceiptV1(
            episode_id=item.episode_id,
            outcome_id="outcome-bad",
            observer_principal_id="policy-principal",
            observer_signing_key_digest=digest("observer-key"),
            observed_at_unix_ms=100,
            latest_observable_at_unix_ms=120,
            expected_delay_profile_digest=DELAY,
            terminality="TERMINAL",
            utility=1.0,
            support_digest=digest("other-support"),
            finalized_at_unix_ms=130,
        )
        with self.assertRaises(OPEReceiptError):
            XYZEpisodeV1(item.episode_id, item.context, item.decision, bad_outcome, item.resources, REAL_SHADOW)

    def test_resource_budget_is_fail_closed(self):
        item = episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0)
        too_small = OPEBudgetV1(BUDGET, COSTS, 3, 99, 10.0, 10.0, 1.0, 0.1)
        with self.assertRaises(OPEReceiptError):
            validate_xyz_episode(item, too_small)

    def test_pending_and_censored_outcomes_are_recorded_but_not_scored(self):
        terminal = episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0)
        censored = episode(2, target_propensity=0.5, logging_propensity=0.5, utility=None, terminality="CENSORED")
        pending = episode(3, target_propensity=1.0, logging_propensity=1.0, utility=None, terminality="PENDING")
        estimate = estimate_ope((terminal, censored, pending), target_policy_id="target_policy", budget=budget(), estimator="SNIPS")
        self.assertEqual(estimate.sample_count, 3)
        self.assertEqual(estimate.terminal_count, 1)
        self.assertEqual(estimate.censored_count, 2)
        self.assertEqual(estimate.estimate, 1.0)

    def test_ips_snips_and_dr_are_supported(self):
        items = (
            episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0),
            episode(2, target_propensity=0.5, logging_propensity=0.5, utility=0.5),
            episode(3, target_propensity=1.0, logging_propensity=1.0, utility=0.0),
        )
        ips = estimate_ope(items, target_policy_id="target_policy", budget=budget(), estimator="IPS")
        snips = estimate_ope(items, target_policy_id="target_policy", budget=budget(), estimator="SNIPS")
        dr = estimate_ope(
            items,
            target_policy_id="target_policy",
            budget=budget(),
            estimator="DR",
            reward_model={item.episode_id: (0.25, 0.5) for item in items},
        )
        self.assertAlmostEqual(ips.estimate, 2.5 / 3.0)
        self.assertAlmostEqual(snips.estimate, 2.5 / 4.0)
        self.assertAlmostEqual(dr.estimate, (2.0 + 0.75 + 0.25) / 3.0)
        self.assertEqual(ips.authority, "DENY_ALL")
        self.assertFalse(dr.model_efficacy_measured)

    def test_dr_requires_an_independent_reward_model(self):
        item = episode(1, target_propensity=1.0, logging_propensity=0.5, utility=1.0)
        with self.assertRaises(OPEReceiptError):
            estimate_ope((item,), target_policy_id="target_policy", budget=budget(), estimator="DR")

    def test_synthetic_evidence_cannot_be_called_real(self):
        item = episode(1, target_propensity=1.0, logging_propensity=1.0, utility=1.0, evidence_class=SYNTHETIC_SMOKE)
        with self.assertRaises(OPEReceiptError):
            estimate_ope((item,), target_policy_id="target_policy", budget=budget())
        estimate = estimate_ope((item,), target_policy_id="target_policy", budget=budget(), require_real_shadow=False)
        self.assertEqual(estimate.evidence_class, SYNTHETIC_SMOKE)
        self.assertFalse(estimate.model_efficacy_measured)

    def test_gold_and_zero_support_are_rejected(self):
        with self.assertRaises(OPEReceiptError):
            ContextReceiptV1(
                "episode-1", digest("context"), digest("source"), GIT_BLOB,
                digest("request"), digest("reader"), "future", True, True,
            )
        with self.assertRaises(OPEReceiptError):
            PolicyDecisionReceiptV1(
                "episode-1", canonical_candidate_set_digest(("target_policy",)), ("target_policy",), "target_policy",
                "target_policy", 0.0, 1.0, SUPPORT, BUDGET, POLICY,
                "policy-principal",
            )

    def test_candidate_set_and_incomplete_resource_are_rejected(self):
        with self.assertRaises(OPEReceiptError):
            PolicyDecisionReceiptV1(
                "episode-1", digest("not-the-support"), ("target_policy",), "target_policy",
                "target_policy", 1.0, 1.0, SUPPORT, BUDGET, POLICY,
                "policy-principal",
            )
        with self.assertRaises(OPEReceiptError):
            OPEResourceReceiptV1(
                "episode-1", BUDGET, "INCOMPLETE", 1, 1, 1.0, 1.0, 1.0, 1.0,
                10, 1,
            )

    def test_target_policy_must_be_inside_logged_support(self):
        with self.assertRaises(OPEReceiptError):
            PolicyDecisionReceiptV1(
                "episode-1",
                canonical_candidate_set_digest(("baseline",)),
                ("baseline",),
                "baseline",
                "missing-target-policy",
                1.0,
                1.0,
                SUPPORT,
                BUDGET,
                POLICY,
                "policy-principal",
            )


if __name__ == "__main__":
    unittest.main()
