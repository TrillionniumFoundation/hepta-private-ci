"""Synthetic guardrails for exact LoRA unique-question warm-start accounting."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_audit_adapter_warmstart import analyze_warmstart


def fixture():
    train = ["train-%d" % i for i in range(48)]
    routes = {q: ("general" if i % 2 == 0 else "temporal") for i, q in enumerate(train)}
    skipped = {train[i] for i in (1, 3, 19, 23, 34, 35, 40, 47)}
    warm = set(train[:16]) - skipped
    # Four pair-ineligible admitted warm examples, among both routes.
    omissions = {train[i] for i in (2, 4, 5, 6)}
    prepared = warm - omissions
    plan = dict(
        questions=dict(train=train),
        arms=[
            "frozen_rerank",
            "prototype",
            "linear",
            "gated",
            "lineage_lora_gated",
            "independent_lora_gated",
        ],
        cells=["general", "temporal"],
        curriculum_attempted_examples=[16, 32, 48],
        adapter_initialization_examples=16,
        encoder_adapters_frozen_after_initialization=True,
        routes=routes,
        question_families={q: "family-" + str(i % 5) for i, q in enumerate(train)},
    )
    disp = dict(
        skipped_training=[
            dict(question_id=q, reason="unresolved_or_missing_positive_not_abstention")
            for q in sorted(skipped)
        ],
        unannotated_candidates_are_weak_distractors=True,
        missing_support_used_as_null=False,
        supervision_level="native-document-support-not-window-entailment",
    )
    keys = ("lineage", "independent-general", "independent-temporal")
    receipts = {}
    for key in keys:
        route = key.removeprefix("independent-")
        pos = (
            prepared
            if key == "lineage"
            else {q for q in prepared if routes[q] == route}
        )
        neg = (
            omissions
            if key == "lineage"
            else {q for q in omissions if routes[q] == route}
        )
        names = sorted(pos)
        repeats = (names * 3)[: 24 if key == "lineage" else 12]
        receipts[key] = dict(
            prepared_questions=names,
            ineligible_pair_questions=sorted(neg),
            consumed_questions=repeats,
            steps=len(repeats),
            status="succeeded",
            base_unchanged=True,
            artifact_only_reload_parity=True,
            weak_unannotated_negatives=True,
            adapter_delta_squared_norm=0.005,
            production_accepted=False,
            tokens=123,
            trainable_parameters=36864,
        )
    adapters = dict(receipts=receipts, failures={})
    arms = plan["arms"]
    cells = plan["cells"]
    learning = [
        dict(arm=arm, cell=cell, stage=stage, status="succeeded")
        for arm in arms
        for cell in cells
        for stage in (16, 32, 48)
    ]
    return plan, disp, adapters, dict(learning=learning)


class WarmStartAuditTests(unittest.TestCase):
    def test_unique_question_count_distinct_from_optimizer_steps(self):
        args = fixture()
        result = analyze_warmstart(*args)
        self.assertEqual(result["actually_admitted_weak_source_questions"], 40)
        self.assertEqual(result["warm_admitted_head_questions"], 14)
        self.assertEqual(result["lineage_unique_pair_trainable_questions"], 10)
        self.assertEqual(result["lineage_pair_ineligible_questions"], 4)
        self.assertFalse(result["actual_task_gain_demonstrated"])
        self.assertFalse(result["production_accepted"])

    def test_duplicate_or_heldout_training_question_fails_closed(self):
        for mode in ("duplicate", "heldout"):
            p, d, a, h = deepcopy(fixture())
            names = a["receipts"]["lineage"]["prepared_questions"]
            names[0] = names[1] if mode == "duplicate" else "test-leak"
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                analyze_warmstart(p, d, a, h)

    def test_optimizer_steps_not_substitute_for_unique_examples(self):
        p, d, a, h = fixture()
        a["receipts"]["lineage"]["consumed_questions"][0] = "invented-qid"
        with self.assertRaisesRegex(AuditError, "optimizer-step"):
            analyze_warmstart(p, d, a, h)

    def test_base_mutation_or_failed_adapter_reload_rejected(self):
        for name in ("base_unchanged", "artifact_only_reload_parity"):
            p, d, a, h = fixture()
            a["receipts"]["lineage"][name] = False
            with self.subTest(name=name), self.assertRaises(AuditError):
                analyze_warmstart(p, d, a, h)

    def test_cross_cell_pair_or_omitted_example_rejected(self):
        p, d, a, h = fixture()
        general = a["receipts"]["independent-general"]
        general["prepared_questions"].append(
            a["receipts"]["independent-temporal"]["prepared_questions"][0]
        )
        with self.assertRaises(AuditError):
            analyze_warmstart(p, d, a, h)

    def test_training_skips_cannot_be_promoted_to_null_or_entailment(self):
        for field, new in (
            ("missing_support_used_as_null", True),
            ("supervision_level", "independently_adjudicated"),
            ("unannotated_candidates_are_weak_distractors", False),
        ):
            p, d, a, h = fixture()
            d[field] = new
            with self.subTest(field=field), self.assertRaises(AuditError):
                analyze_warmstart(p, d, a, h)

    def test_missing_one_head_checkpoint_rejected(self):
        p, d, a, h = fixture()
        h["learning"].pop()
        with self.assertRaisesRegex(AuditError, "Head checkpoints"):
            analyze_warmstart(p, d, a, h)


if __name__ == "__main__":
    unittest.main()
