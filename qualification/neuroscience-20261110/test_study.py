import unittest
from dataclasses import replace
from hashlib import sha256

from study import (
    ARMS, ContractError, Eligibility, Feedback, MemoryRecord, TrialRow,
    UpdateOpportunity, cadence_gate, paired_evidence, select_replay,
    time_aligned_credit,
)


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def actions():
    return [
        Eligibility("action:1", digest("s1"), 1, (1.0, 0.0)),
        Eligibility("action:2", digest("s2"), 2, (0.0, 1.0)),
    ]


def outcomes():
    return [
        Feedback(digest("o1"), "action:1", 4, (1.0, 0.0)),
        Feedback(digest("o2"), "action:2", 5, (0.0, 1.0)),
    ]


def credit(arm="routed", action_list=None, feedback_list=None, **kwargs):
    return time_aligned_credit(
        actions() if action_list is None else action_list,
        outcomes() if feedback_list is None else feedback_list,
        arm=arm, cutoff_sequence=kwargs.pop("cutoff_sequence", 5),
        decay=kwargs.pop("decay", 1.0),
        max_lag=kwargs.pop("max_lag", 8),
        **kwargs,
    )


def row(arm, episode_id="ep1", **kwargs):
    base = TrialRow(
        episode_id=episode_id, seed=1, family="sparse_delayed_ACT",
        arm=arm, workload_digest=digest("task:" + episode_id),
        ability_digest=digest("ability"), evaluator_digest=digest("frozen-evaluator"),
        feedback_budget_bits=128, query_budget=6, training_budget=10,
        compute_budget_us=500000, gross_value=1.0, full_cost=0.2,
        retention_value=0.8, evaluator_independent=True,
        outcome_receipt_digest=digest("receipt:" + episode_id + arm),
    )
    return replace(base, **kwargs)


class CreditTests(unittest.TestCase):
    def test_information_matched_routing_ablation_separates_on_known_fixture(self):
        routed = credit("routed")
        shuffled = credit("shuffled")
        scalar = credit("scalar")
        none = credit("no_eligibility")
        self.assertEqual(routed.deltas, (0.5, 0.5))
        self.assertEqual(shuffled.deltas, (0.0, 0.0))
        self.assertEqual(scalar.deltas, (0.5, 0.5))
        self.assertEqual(none.deltas, (0.0, 0.0))
        self.assertEqual(routed.matched, 2)
        self.assertEqual(routed.authority, "DENY_ALL")

    def test_delayed_evidence_decays_and_expires(self):
        a = [actions()[0]]
        f = [outcomes()[0]]
        self.assertAlmostEqual(
            credit(action_list=a, feedback_list=f, decay=0.5).deltas[0],
            0.125,
        )
        expired = credit(action_list=a, feedback_list=f, decay=0.5, max_lag=2)
        self.assertEqual(expired.expired, 1)
        self.assertEqual(expired.deltas, (0.0, 0.0))

    def test_future_feedback_must_not_train_the_past(self):
        receipt = credit(cutoff_sequence=2)
        self.assertEqual(receipt.future_withheld, 2)
        self.assertEqual(receipt.matched, 0)
        self.assertEqual(receipt.deltas, (0.0, 0.0))

    def test_action_order_does_not_change_identity_or_result(self):
        a = credit()
        b = credit(action_list=list(reversed(actions())),
                   feedback_list=list(reversed(outcomes())))
        self.assertEqual(a.transcript_digest, b.transcript_digest)
        self.assertEqual(a.deltas, b.deltas)

    def test_duplicate_or_forged_feedback_is_rejected(self):
        f = outcomes()
        with self.assertRaises(ContractError):
            credit(feedback_list=[f[0], f[0]])
        with self.assertRaises(ContractError):
            credit(feedback_list=[replace(f[0], action_id="absent")])
        with self.assertRaises(ContractError):
            credit(feedback_list=[replace(f[0], available_sequence=0)])
        with self.assertRaises(ContractError):
            credit(action_list=[replace(actions()[0], source_digest="bad")])

    def test_eval_split_and_overweight_eligibility_rejected(self):
        with self.assertRaises(ContractError):
            credit(action_list=[replace(actions()[0], split="heldout")])
        with self.assertRaises(ContractError):
            credit(action_list=[replace(actions()[0], values=(1.1, 0.0))])
        with self.assertRaises(ContractError):
            credit("shuffled", action_list=[
                Eligibility("a", digest("s"), 1, (1.0,))],
                feedback_list=[Feedback(digest("r"), "a", 2, (1.0,))])

    def test_projected_updates_honor_both_trust_bounds(self):
        receipt = credit(per_group_limit=0.1, global_l1_limit=0.15)
        self.assertTrue(all(abs(x) <= 0.1 for x in receipt.deltas))
        self.assertLessEqual(sum(map(abs, receipt.deltas)), 0.150000001)

    def test_all_arms_present(self):
        self.assertEqual(set(ARMS),
                         {"routed", "shuffled", "scalar", "no_eligibility"})


class CadenceTests(unittest.TestCase):
    def gaps(self):
        return {"PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
                "VERIFY": 8, "ACT": 16, "LEARN": 16}

    def test_clock_and_independent_eval_both_gate_approval(self):
        events = [
            UpdateOpportunity("PERC", 1, 2, True, True),
            UpdateOpportunity("PERC", 2, 2, True, True),
            UpdateOpportunity("MEM", 1, 3, False, True),
            UpdateOpportunity("MEM", 2, 3, True, True),
            UpdateOpportunity("PERC", 17, 2, True, False),
        ]
        results = cadence_gate(events, self.gaps())
        self.assertEqual([x["status"] for x in results],
                         ["REVIEW_CANDIDATE", "NO_UPDATE", "NO_UPDATE",
                          "REVIEW_CANDIDATE", "NO_UPDATE"])
        self.assertTrue(all(x["authority"] == "DENY_ALL" for x in results))

    def test_must_declare_all_clocks_and_reject_time_regression(self):
        with self.assertRaises(ContractError):
            cadence_gate([], {"MEM": 1})
        with self.assertRaises(ContractError):
            cadence_gate([UpdateOpportunity("PERC", 4, 2, True, True),
                          UpdateOpportunity("PERC", 3, 2, True, True)],
                         self.gaps())


class ReplayTests(unittest.TestCase):
    def memories(self):
        return [
            MemoryRecord("fact-old", "fact", "key", digest("src-f1"), 1),
            MemoryRecord("fact-deleted", "fact", "key", digest("src-f2"), 3,
                         tombstoned=True),
            MemoryRecord("episode-old", "episode", "key", digest("src-e"), 2),
            MemoryRecord("skill-new", "skill", "other", digest("src-s"), 3),
            MemoryRecord("recovery-revoked", "recovery", "key", digest("src-r"), 4,
                         rights_revoked=True),
            MemoryRecord("future", "recovery", "key", digest("src-new"), 100),
        ]

    def test_deletion_and_future_cutoff_cover_all_replay_policies(self):
        for policy in ("exact", "uniform", "stratified"):
            ids = select_replay(self.memories(), policy=policy, query_key="key",
                                now_sequence=5, max_items=10, seed="seed")
            self.assertNotIn("fact-deleted", ids)
            self.assertNotIn("recovery-revoked", ids)
            self.assertNotIn("future", ids)
        self.assertEqual(
            select_replay(self.memories(), policy="exact", query_key="key",
                          now_sequence=5, max_items=10, seed="seed"),
            ("episode-old", "fact-old"),
        )

    def test_stratified_replay_gives_old_episode_coverage(self):
        ids = select_replay(self.memories(), policy="stratified", query_key="key",
                            now_sequence=5, max_items=3, seed="seed")
        self.assertIn("fact-old", ids)
        self.assertIn("episode-old", ids)
        self.assertIn("skill-new", ids)

    def test_corrected_logical_revision_never_replays_prior_version(self):
        records = [
            MemoryRecord("a1", "fact", "K", digest("a1"), 1, logical_id="a"),
            MemoryRecord("a2", "fact", "K", digest("a2"), 2, logical_id="a"),
            MemoryRecord("b1", "episode", "K", digest("b1"), 1, logical_id="b"),
        ]
        for policy in ("exact", "uniform", "stratified"):
            with self.subTest(policy=policy):
                got = select_replay(records, policy=policy, query_key="K",
                                    now_sequence=3, max_items=10, seed="fixed")
                self.assertEqual(set(got), {"a2", "b1"})

    def test_tombstone_blocks_old_and_later_versions_without_owner_regrant(self):
        records = [
            MemoryRecord("a1", "fact", "K", digest("a1"), 1, logical_id="a"),
            MemoryRecord("a-deleted", "fact", "K", digest("delete"), 3,
                         tombstoned=True, logical_id="a"),
            MemoryRecord("a-forged", "fact", "K", digest("forged"), 4,
                         logical_id="a"),
            MemoryRecord("b1", "episode", "K", digest("b1"), 2,
                         logical_id="b"),
        ]
        for policy in ("exact", "uniform", "stratified"):
            with self.subTest(policy=policy):
                before = select_replay(records, policy=policy, query_key="K",
                                       now_sequence=2, max_items=10, seed="fixed")
                after = select_replay(records, policy=policy, query_key="K",
                                      now_sequence=5, max_items=10, seed="fixed")
                self.assertEqual(set(before), {"a1", "b1"})
                self.assertEqual(after, ("b1",))

    def test_revocation_is_sticky_and_ambiguous_revision_is_rejected(self):
        a = MemoryRecord("a1", "fact", "K", digest("a1"), 1, logical_id="a")
        revoked = MemoryRecord("a2", "fact", "K", digest("a2"), 2,
                               rights_revoked=True, logical_id="a")
        later = MemoryRecord("a3", "fact", "K", digest("a3"), 3,
                             logical_id="a")
        self.assertEqual(
            select_replay([a, revoked, later], policy="exact", query_key="K",
                          now_sequence=3, max_items=3, seed="s"), ())
        invalid = [
            replace(later, key="moved"),
            replace(later, kind="skill"),
            replace(later, observed_sequence=2),
            replace(later, logical_id=""),
            replace(later, tombstoned="false"),
            replace(later, rights_revoked=1),
        ]
        for variant in invalid:
            with self.subTest(variant=variant), self.assertRaises(ContractError):
                select_replay([a, revoked, variant], policy="exact", query_key="K",
                              now_sequence=5, max_items=3, seed="s")


class PairedEvidenceTests(unittest.TestCase):
    def rows(self, count=3):
        return [
            row(arm, episode_id=f"ep{i}", seed=i,
                gross_value=2.0 if arm == "routed" else 1.0,
                full_cost=0.2 if arm == "routed" else 0.1)
            for i in range(count) for arm in ARMS
        ]

    def test_paired_net_calculation_and_no_production_claim(self):
        report = paired_evidence(self.rows())
        self.assertEqual(report["blocks"], 3)
        self.assertAlmostEqual(report["mean_net_difference"], 0.9)
        self.assertAlmostEqual(report["mean_cost_difference"], 0.1)
        self.assertEqual(report["one_sided_exact_signflip_p"], 0.125)
        self.assertEqual(report["research_posture"], "HOLD_NO_PRODUCTION_AUTHORITY")

    def test_missing_arm_is_not_zero_or_success(self):
        with self.assertRaises(ContractError):
            paired_evidence(self.rows()[:-1])

    def test_capability_feedback_and_budget_mismatch_fail_closed(self):
        for variant in (
            {"ability_digest": digest("stronger-baseline")},
            {"feedback_budget_bits": 256},
            {"query_budget": 9},
            {"compute_budget_us": 500001},
            {"evaluator_digest": digest("other-evaluator")},
            {"workload_digest": digest("easier-task")},
        ):
            rows = self.rows(1)
            rows[0] = replace(rows[0], **variant)
            with self.subTest(variant=variant), self.assertRaises(ContractError):
                paired_evidence(rows)

    def test_claims_cannot_be_certified_by_a_flag(self):
        rows = self.rows(1)
        rows[0] = replace(rows[0], evaluator_independent=False,
                          retention_value=None)
        report = paired_evidence(rows)
        self.assertFalse(report["evaluation_claimed_independent"])
        self.assertIsNone(report["mean_retention_difference"])
        self.assertEqual(report["qualification"], "RECEIPTS_NOT_EXTERNALLY_ATTESTED")

    def test_negative_cost_rejected(self):
        rows = self.rows(1)
        rows[0] = replace(rows[0], full_cost=-1)
        with self.assertRaises(ContractError):
            paired_evidence(rows)

    def test_reused_seed_is_one_independent_cluster(self):
        rows = self.rows(2)
        rows = [replace(r, seed=0) for r in rows]
        report = paired_evidence(rows)
        self.assertEqual(report["blocks"], 2)
        self.assertEqual(report["seed_clusters"], 1)
        self.assertEqual(report["one_sided_exact_signflip_p"], 0.5)

    def test_reused_outcome_receipt_is_rejected(self):
        rows = self.rows(1)
        rows[1] = replace(rows[1], outcome_receipt_digest=rows[0].outcome_receipt_digest)
        with self.assertRaises(ContractError):
            paired_evidence(rows)


if __name__ == "__main__":
    unittest.main()
