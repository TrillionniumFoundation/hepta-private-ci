"""Synthetic tampering tests: no pretrained model or held-out label authority."""
from copy import deepcopy
import unittest

from stem_oct13_bottleneck_gate import assess, ARMS, STAGES, PHASES, SOURCE


def fixture():
    qs = {"train": [f"train-{i}" for i in range(48)]}
    qs.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    plan = dict(
        source_commit=SOURCE,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        arms=list(ARMS), curriculum_attempted_examples=list(STAGES), questions=qs,
    )
    raw = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in qs[phase]:
                for arm in ARMS:
                    raw.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        status="succeeded", selected=0, family="family-"+qid,
                        cell="general", pool_digest="pool-"+qid, answer="same",
                        receipt=dict(generator_identity="reader", generator_profile="prompt",
                                     observable_query={"identity": qid},
                                     delivered_evidence=[{"label": "E1"}],
                                     production_accepted=False),
                    ))
    metrics = {f"{stage}/{phase}/{arm}":dict(
        attempted=8, succeeded=8, failed=0, emitted_citation_markers=0,
    ) for stage in STAGES for phase in PHASES for arm in ARMS}
    report = dict(logical_policy_attempts=576, metrics=metrics,
                  production_accepted=False, semantic_citation_precision=None)
    fit = dict(checkpoints=[dict(checkpoint=stage, arm=arm, cell=cell,
                                mean_weak_loss_delta=0.18 if cell=="general" else -0.15,
                                weak_source_top1_gains=0,
                                mean_positive_over_negative_candidate_margin_delta=0.02,
                                matched_training_rows=20, production_accepted=False)
                            for stage in STAGES for arm in ARMS[1:]
                            for cell in ("general", "temporal")])
    ceiling = dict(final_checkpoint=48, after_all_policy_answers=True,
                   production_accepted=False, phases={
        "test":dict(attempted=8,native_source_resolved=6,native_unanswerable=2,
                    native_unresolved_support=0,candidate_pool_missing=0,
                    support_available_within_pool=4,support_missing_from_pool=2,
                    frozen_correct_source_choices=3,frozen_missed_available_support=1),
        "transfer":dict(attempted=8,native_source_resolved=7,native_unanswerable=1,
                    native_unresolved_support=0,candidate_pool_missing=0,
                    support_available_within_pool=7,support_missing_from_pool=0,
                    frozen_correct_source_choices=6,frozen_missed_available_support=1)})
    paired = dict(matched_pairs=32, production_accepted=False, per_phase={
        phase: dict(attempted=8,paired_diagnostic_delta_mean=0.0,
                    all_planned_answer_delta_bounds=[-0.25, 0.25])
        for phase in PHASES})
    effective=dict(independent_question_ids_per_arm=16,
                   repeated_question_evaluations_per_arm=48,
                   source_family_sampling_independence_certified=False)
    return plan,raw,report,ceiling,fit,paired,effective


class SourceFirstGateTests(unittest.TestCase):
    def test_complete_strict_census_blocks_scaleout(self):
        o=assess(*fixture())
        self.assertEqual(o["unique_test_transfer_questions"],16)
        self.assertEqual(o["missing_from_candidate_pool"],2)
        self.assertEqual(o["inside_pool_but_wrong_frozen_top1"],2)
        self.assertEqual(o["already_selected_weak_native_support"],9)
        self.assertEqual(sum(x["changed_source_top1"] for x in o["learned_vs_frozen"].values()),0)
        self.assertFalse(o["additional_cells_or_production_scaleout_qualified"])
        self.assertIsNone(o["semantic_citation_precision"])

    def test_missing_or_duplicate_policy_never_shrinks_denominator(self):
        for edit in ("remove", "duplicate"):
            data=list(fixture());data[1]=deepcopy(data[1]);
            if edit=="remove":data[1].pop()
            else:data[1][-1]=deepcopy(data[1][0])
            with self.subTest(edit=edit),self.assertRaisesRegex(ValueError,"original.*(policy|strict)"):
                assess(*data)

    def test_changed_model_prompt_pool_or_source_bytes_fails_pair_binding(self):
        for change in ("model", "prompt", "pool", "evidence"):
            data=list(fixture());data[1]=deepcopy(data[1]);q=next(x for x in data[1]
                if x["stage"]==48 and x["phase"]=="test" and x["arm"]=="gated")
            if change=="model":q["receipt"]["generator_identity"]="other"
            if change=="prompt":q["receipt"]["generator_profile"]="other"
            if change=="pool":q["pool_digest"]="different"
            if change=="evidence":q["receipt"]["delivered_evidence"]=[]
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,"matched"):
                assess(*data)

    def test_changed_source_is_recorded_not_invented_superiority(self):
        data=list(fixture());data[1]=deepcopy(data[1]);q=next(x for x in data[1]
            if x["stage"]==48 and x["phase"]=="test" and x["arm"]=="gated")
        q["selected"]=1;q["answer"]="different"
        d=assess(*data)["learned_vs_frozen"]["gated"]
        self.assertEqual(d["changed_source_top1"],1)
        self.assertEqual(d["changed_answer_bytes"],1)
        self.assertFalse(d["independent_generalization_established"])

    def test_one_missing_head_fit_receipt_fails(self):
        data=list(fixture());data[4]=deepcopy(data[4]);data[4]["checkpoints"].pop()
        with self.assertRaisesRegex(ValueError,"five trainable"):
            assess(*data)

    def test_relabelled_missing_evidence_as_positive_fails(self):
        data=list(fixture());data[3]=deepcopy(data[3]);data[3]["phases"]["test"]["support_missing_from_pool"]=1
        with self.assertRaisesRegex(ValueError,"support accounting"):
            assess(*data)

    def test_checkpoint_replays_are_not_independent_examples(self):
        data=list(fixture());data[6]=deepcopy(data[6]);data[6]["independent_question_ids_per_arm"]=48
        with self.assertRaisesRegex(ValueError,"not 48 independent"):
            assess(*data)

    def test_no_citation_marker_does_not_prove_semantic_precision(self):
        data=list(fixture());data[2]=deepcopy(data[2]);data[2]["metrics"]["48/test/gated"]["emitted_citation_markers"]=1
        out=assess(*data)
        self.assertEqual(out["original_citation_markers"],1)
        self.assertIsNone(out["semantic_citation_precision"])
        self.assertFalse(out["production_accepted"])


if __name__ == '__main__':unittest.main()
