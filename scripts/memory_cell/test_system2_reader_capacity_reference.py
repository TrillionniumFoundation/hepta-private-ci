"""Frozen reference-Reader admission: no oracle or online target leakage."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_evidence import parse_relation
from system2_multihop_trial import ABSTAIN, evidence
from system2_reader_capacity_reference import (
    ARMS,
    CASE_COUNT,
    COHORTS,
    LABEL_RAW_SHA,
    MODEL_ID,
    MODEL_REV,
    MODEL_FILES,
    PLAN_SIZE,
    TOKEN_LIMIT,
    cohorts,
    fixed_new_cases,
    load_baseline_archives,
    outcome,
    run,
    score,
    selected,
    study_plan,
)


class ReferenceFake:
    """A transparent symbolic READER TEST DOUBLE, not neural-model evidence."""

    identity = "fake-model-sha"
    profile = "fake-prompt"
    inventory = {"model.safetensors": {"sha256": "fake"}}
    param_count = 3
    frozen_calls = 0
    total = 0

    def answer(self, case, docs, arm):
        self.total += 1
        target = case.question.content.split("device ")[1].rstrip("?")
        candidates = []
        for doc in docs:
            edge = parse_relation(doc)
            if (
                edge
                and edge[0] == "device"
                and edge[1] == target
                and edge[2] == "token"
            ):
                candidates.append(edge[3])
        answer = candidates[0] if len(set(candidates)) == 1 and candidates else ABSTAIN
        bundle, _, _ = evidence(case, docs, arm)
        return answer, dict(
            reader_identity=self.identity,
            reader_profile=self.profile,
            bundle_digest=bundle.seal(),
            delivered_evidence=bundle.delivered(),
            trainable_parameters=0,
            answer_postprocessed=False,
            token_limit=TOKEN_LIMIT,
            cpu_time_ns=150,
            wall_time_ns=260,
            generated_tokens=4,
            input_tokens=50,
        )

    def verify_frozen(self):
        self.frozen_calls += 1


class CapacityReferenceTests(unittest.TestCase):
    def test_cohort_fixed_and_disjoint(self):
        c = cohorts()
        self.assertEqual(set(c), set(COHORTS))
        self.assertEqual([len(c[k]) for k in COHORTS], [CASE_COUNT, CASE_COUNT])
        self.assertEqual(len(fixed_new_cases()), CASE_COUNT)
        self.assertEqual(PLAN_SIZE, 160)
        self.assertFalse(
            set(x.question.identity for x in c["exposed_20"])
            & set(x.question.identity for x in c["fixed_new_20"])
        )

    def test_selectors_receive_no_target_answer_and_keep_exact_source(self):
        c = cohorts()
        for group in c.values():
            for case in group:
                changed = replace(case, answer="TOK-0000000")
                for arm in ARMS:
                    docs = selected(case, arm)
                    self.assertEqual(docs, selected(changed, arm))
                    self.assertEqual(
                        case.required_id in {d.identity for d in docs}, arm in ARMS[:2]
                    )
                    self.assertTrue(all(d.scope == case.question.scope for d in docs))

    def test_fixed_reference_revision_and_model_accounting(self):
        self.assertEqual(MODEL_ID, "Qwen/Qwen2.5-0.5B-Instruct")
        self.assertEqual(MODEL_REV, "a338b55dd21219a5f4da42bc11a9313d1a27d4cc")
        self.assertIn("model.safetensors", MODEL_FILES)
        self.assertIn("config.json", MODEL_FILES)
        groups = cohorts()
        p = study_plan(groups, "a" * 40, LABEL_RAW_SHA)
        self.assertTrue(p["tokenizer_and_model_differ"])
        self.assertFalse(p["compute_and_tokenizer_matched"])
        self.assertFalse(p["production_accepted"])
        self.assertEqual(p["planned"], 160)
        with self.assertRaises(ValueError):
            study_plan(groups, "unknown", LABEL_RAW_SHA)

    def test_negative_token_copy_and_untrusted_labels_not_accepted(self):
        sample = cohorts()["exposed_20"][0]
        for arm in ARMS[:2]:
            self.assertTrue(outcome(sample, arm, sample.answer)["conditional_success"])
            self.assertFalse(
                outcome(sample, arm, sample.answer + " [E1]")["conditional_success"]
            )
        for arm in ARMS[2:]:
            self.assertTrue(outcome(sample, arm, ABSTAIN)["conditional_success"])
            r = outcome(sample, arm, sample.answer)
            self.assertTrue(r["unsupported_token_copy"])
            self.assertFalse(r["conditional_success"])
        self.assertFalse(outcome(sample, "single_fact", "E1")["conditional_success"])
        with self.assertRaises(ValueError):
            outcome(sample, "bad-arm", "E1")

    def test_score_complete_census_and_missing_response_is_unknown(self):
        groups = {
            "exposed_20": cohorts()["exposed_20"][:1],
            "fixed_new_20": cohorts()["fixed_new_20"][:1],
        }
        rows = []
        for group, cases_ in groups.items():
            for case in cases_:
                for arm in ARMS:
                    rows.append(
                        dict(
                            cohort=group,
                            qid=case.question.identity,
                            arm=arm,
                            selected=[d.identity for d in selected(case, arm)],
                            status="succeeded",
                            answer=case.answer if arm in ARMS[:2] else ABSTAIN,
                        )
                    )
        scores, summary = score(rows, groups)
        self.assertEqual(len(scores), 8)
        self.assertTrue(all(x["conditional_success"] == 1 for x in summary))
        with self.assertRaises(ValueError):
            score(rows[:-1], groups)
        with self.assertRaises(ValueError):
            score(rows + rows[:1], groups)
        rows[0]["status"] = "failed"
        rows[0].pop("answer")
        scored, summary = score(rows, groups)
        self.assertIsNone(scored[0]["conditional_success"])
        self.assertEqual(sum(x["failed"] for x in summary), 1)

    def test_runner_seals_outputs_before_scoring_and_counts_original(self):
        groups = {
            "exposed_20": cohorts()["exposed_20"][:1],
            "fixed_new_20": cohorts()["fixed_new_20"][:1],
        }
        fake = ReferenceFake()
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "test-run"
            parent = {"by_key": {}, "raw_sha256": LABEL_RAW_SHA}
            for case in groups["exposed_20"]:
                for arm in ARMS:
                    mode = "unlabeled" if arm == "no_evidence" else "labeled"
                    parent["by_key"][case.question.identity, arm, mode] = dict(
                        status="succeeded", answer=ABSTAIN
                    )
            with patch(
                "system2_reader_capacity_reference.load_baseline_archives",
                return_value=parent,
            ):
                result = run(
                    output,
                    fake,
                    cardinality_archive="fake-card.zip",
                    label_archive="fake-label.zip",
                    source_commit="b" * 40,
                    groups=groups,
                )
            self.assertEqual(
                (result["planned"], result["recorded"], result["failed"]), (8, 8, 0)
            )
            self.assertEqual(fake.frozen_calls, 1)
            self.assertEqual(fake.total, 8)
            seal = json.loads((output / "raw-seal.json").read_text())
            self.assertEqual(seal["rows"], 8)
            self.assertFalse(seal["scoring_started"])
            self.assertEqual(
                seal["sha256"],
                hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest(),
            )
            self.assertEqual(len((output / "starts.jsonl").read_text().splitlines()), 8)
            self.assertEqual(result["full_model_inference_cpu_ns"], 8 * 150)
            self.assertFalse(result["production_accepted"])

    def test_failed_generation_retains_partial_result_without_false_label(self):
        groups = {
            "exposed_20": cohorts()["exposed_20"][:1],
            "fixed_new_20": cohorts()["fixed_new_20"][:1],
        }

        class Broken(ReferenceFake):
            def answer(self, *args, **kwargs):
                raise RuntimeError("injected")

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken"
            with patch(
                "system2_reader_capacity_reference.load_baseline_archives",
                return_value={"by_key": {}, "raw_sha256": LABEL_RAW_SHA},
            ):
                with self.assertRaises(RuntimeError):
                    run(
                        p,
                        Broken(),
                        cardinality_archive="fake",
                        label_archive="fake",
                        source_commit="c" * 40,
                        groups=groups,
                    )
            failed = json.loads((p / "run-failure.json").read_text())
            self.assertEqual(failed["planned"], 8)
            self.assertEqual(failed["completed"], 0)
            self.assertTrue(failed["unrecorded_work_not_free"])
            self.assertEqual(len((p / "raw-answers.jsonl").read_text().splitlines()), 1)
            self.assertFalse((p / "raw-seal.json").exists())

    def test_wrong_identity_or_proof_bundle_fails_closed(self):
        groups = {
            "exposed_20": cohorts()["exposed_20"][:1],
            "fixed_new_20": cohorts()["fixed_new_20"][:1],
        }

        class Corrupt(ReferenceFake):
            def answer(self, case, docs, arm):
                answer, rec = super().answer(case, docs, arm)
                rec["bundle_digest"] = "tampered"
                return answer, rec

        with tempfile.TemporaryDirectory() as d:
            with patch(
                "system2_reader_capacity_reference.load_baseline_archives",
                return_value={"by_key": {}, "raw_sha256": LABEL_RAW_SHA},
            ):
                with self.assertRaises(ValueError):
                    run(
                        Path(d) / "corrupt",
                        Corrupt(),
                        cardinality_archive="fake",
                        label_archive="fake",
                        source_commit="d" * 40,
                        groups=groups,
                    )

    @unittest.skipUnless(
        os.getenv("HEPTA_CARDINALITY_ARCHIVE") and os.getenv("HEPTA_LABEL_ARCHIVE"),
        "pinned hosted baseline archives not staged",
    )
    def test_real_140_output_archive_fully_authenticated(self):
        receipt = load_baseline_archives(
            os.environ["HEPTA_CARDINALITY_ARCHIVE"], os.environ["HEPTA_LABEL_ARCHIVE"]
        )
        self.assertEqual((receipt["verified_files"], len(receipt["by_key"])), (25, 140))
        self.assertEqual(receipt["raw_sha256"], LABEL_RAW_SHA)


if __name__ == "__main__":
    unittest.main()
