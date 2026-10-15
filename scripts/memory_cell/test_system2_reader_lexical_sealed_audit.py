"""No-model-call adversarial controls for the completed lexical-factorial audit."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native import digest as native_digest
from system2_multihop_trial import ABSTAIN, evidence
from system2_reader_lexical_factorial import (
    ARMS,
    CALLS,
    MODEL_ID,
    MODEL_REV,
    POSITIVE,
    PROFILES,
    SCHEMA,
    base_cases,
    delivery,
    score,
)
from system2_reader_lexical_sealed_audit import (
    ARCHIVE_SHA,
    REFERENCE_SHA,
    SOURCE_COMMIT,
    SOURCE_TREE,
    STRONG_READER_ID,
    authenticate,
    paired_summary,
    run,
    verify_census,
)

PIN = "f" * 64


def json_bytes(item):
    return json.dumps(item, sort_keys=True, allow_nan=False).encode()


def fixture():
    """Small in-memory archived response simulator; no neural inference."""
    cases = base_cases()
    starts, rows, scored, summary = [], [], [], []
    for case in cases:
        for arm in ARMS:
            for profile in PROFILES:
                variant, docs = delivery(case, arm, profile)
                bundle, originals, frontier = evidence(
                    variant, docs, "lexical:" + profile + ":" + arm
                )
                bundle.validate(
                    variant.question, originals, frontier=frontier, revoked=set()
                )
                key = dict(qid=case.question.identity, arm=arm, profile=profile)
                starts.append(key | dict(status="started"))
                rec = dict(
                    reader_identity=STRONG_READER_ID,
                    reader_profile="unchanged-profile",
                    model_id=MODEL_ID,
                    revision=MODEL_REV,
                    trainable_parameters=0,
                    answer_postprocessed=False,
                    production_accepted=False,
                    input_ids_digest="a" * 64,
                    generated_ids_digest="b" * 64,
                    input_tokens=80,
                    generated_tokens=8,
                    cpu_time_ns=1000,
                    query_digest=native_digest(asdict(variant.question)),
                    delivered_evidence=bundle.delivered(),
                    bundle_digest=bundle.seal(),
                )
                rows.append(
                    key
                    | dict(
                        status="succeeded",
                        answer=ABSTAIN,
                        selected=[d.identity for d in docs],
                        reader=rec,
                    )
                )
                scored.append(key | score(case, arm, profile, ABSTAIN))
    for profile in PROFILES:
        for arm in ARMS:
            is_positive = arm in POSITIVE
            summary.append(
                dict(
                    profile=profile,
                    arm=arm,
                    questions=20,
                    exact_answers=0,
                    refusal_outputs=20,
                    appropriate_refusals=0 if is_positive else 20,
                    over_refusals=20 if is_positive else 0,
                    strict_successes=0 if is_positive else 20,
                    unsupported_token_copies=0,
                    input_tokens=1600,
                    output_tokens=160,
                    decoder_cpu_ns=20000,
                )
            )
    raw = b"".join(json_bytes(r) + b"\n" for r in rows)
    files = dict(
        **{
            "tested-commit.txt": SOURCE_COMMIT.encode(),
            "tested-tree.txt": SOURCE_TREE.encode(),
            "reader-inventory.json": json_bytes(
                dict(
                    model=MODEL_ID,
                    revision=MODEL_REV,
                    files={"model.safetensors": {"sha256": "test"}},
                )
            ),
            "trial/raw-answers.jsonl": raw,
            "trial/starts.jsonl": b"".join(json_bytes(x) + b"\n" for x in starts),
            "trial/raw-seal.json": json_bytes(
                dict(
                    sha256=hashlib.sha256(raw).hexdigest(),
                    rows=CALLS,
                    scoring_started=False,
                )
            ),
            "trial/plan.json": json_bytes(
                dict(
                    schema=SCHEMA,
                    source_commit=SOURCE_COMMIT,
                    reader_identity=STRONG_READER_ID,
                    original_archive_sha256=REFERENCE_SHA,
                    questions=[c.question.identity for c in cases],
                    profiles=list(PROFILES),
                    arms=list(ARMS),
                    expected_model_calls=CALLS,
                    new_task_range=[60, 80],
                    learned_updates=0,
                    online_gold_labels=False,
                    actual_compute_matched=False,
                    same_model_weight_and_tokenizer=True,
                    production_accepted=False,
                )
            ),
            "trial/scored.json": json_bytes(scored),
            "trial/summary.json": json_bytes(
                dict(
                    source_commit=SOURCE_COMMIT,
                    raw_answer_sha256=hashlib.sha256(raw).hexdigest(),
                    completed=CALLS,
                    model_calls=CALLS,
                    failures=0,
                    production_accepted=False,
                    disposition="lexical_factorial_not_qualified",
                    results=summary,
                )
            ),
        }
    )
    old_files = {
        "reference-inventory.json": json_bytes(
            dict(
                model_snapshot_inventory={"model.safetensors": {"sha256": "test"}},
                model_id=MODEL_ID,
                revision=MODEL_REV,
            )
        )
    }
    old_plan = dict(reference_reader_identity=STRONG_READER_ID)
    old = dict((str(i), i) for i in range(160))
    return files, (old_files, old_plan, old), cases


class SealedFactorialAuditTests(unittest.TestCase):
    def test_fixed_factorial_registration(self):
        self.assertEqual((CALLS, len(PROFILES), len(ARMS)), (320, 4, 4))
        self.assertEqual(len(base_cases()), 20)
        self.assertEqual(
            ARCHIVE_SHA,
            "0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19",
        )

    def test_exact_four_profile_pair_census(self):
        cases = base_cases()
        labels = [
            dict(qid=c.question.identity, arm=a, profile=p)
            for c in cases
            for a in ARMS
            for p in PROFILES
        ]
        self.assertEqual(len(verify_census(labels, cases, field="proof")), CALLS)
        with self.assertRaises(ValueError):
            verify_census(labels[:-1], cases, field="proof")
        with self.assertRaises(ValueError):
            verify_census(labels + labels[:1], cases, field="proof")

    def test_paired_interaction_uses_same_question_block(self):
        cases = base_cases()
        known = {}
        for index, c in enumerate(cases):
            for arm in ARMS:
                for profile in PROFILES:
                    val = (
                        index == 0
                        and arm == "single_fact"
                        and profile == "inventory_tag"
                    )
                    known[c.question.identity, arm, profile] = dict(
                        score=dict(
                            (m, val)
                            for m in (
                                "exact_answer",
                                "exact_refusal",
                                "over_refusal",
                                "unsupported_token_copy",
                                "task_success",
                            )
                        ),
                        input_tokens=80,
                        output_tokens=8,
                        cpu_time_ns=100,
                    )
        out = paired_summary(known, cases)
        single = next(x for x in out if x["arm"] == "single_fact")
        m = single["metrics"]["exact_answer"]
        self.assertEqual(m["inventory_tag_successes"], 1)
        self.assertEqual(m["descriptive_interaction"], 1)
        self.assertEqual(m["inventory_gain_at_tag"], 1)
        self.assertEqual(
            single["cost_by_profile"]["inventory_tag"]["input_tokens"], 1600
        )
        self.assertEqual(single["distinct_questions"], 20)

    def test_archive_pin_must_be_external_complete_sha(self):
        with self.assertRaises(ValueError):
            authenticate("not-a-file", "not-a-parent", expected_digest="pending")

    def test_no_inference_full_archived_provenance_roundtrip(self):
        files, parent, cases = fixture()
        with (
            patch(
                "system2_reader_lexical_sealed_audit.verified_archive",
                return_value=files,
            ),
            patch(
                "system2_reader_lexical_sealed_audit.open_strong", return_value=parent
            ),
        ):
            actual, got, seal, member_count = authenticate(
                "synthetic.zip", "parent.zip", expected_digest=PIN
            )
            self.assertEqual((len(actual), len(got)), (320, 20))
            self.assertEqual(
                seal, hashlib.sha256(files["trial/raw-answers.jsonl"]).hexdigest()
            )
            self.assertEqual(member_count, len(files) - 1)
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "summary.json"
                result = run("synthetic.zip", "parent.zip", path, expected_digest=PIN)
                self.assertEqual(result["new_neural_calls"], 0)
                self.assertEqual(result["question_count"], 20)
                self.assertEqual(len(result["grouped_effects"]), 4)
                self.assertTrue(path.is_file())

    def test_tampered_score_not_silent(self):
        files, parent, _ = fixture()
        bad = json.loads(files["trial/scored.json"])
        bad[0]["task_success"] = not bad[0]["task_success"]
        files["trial/scored.json"] = json_bytes(bad)
        with (
            patch(
                "system2_reader_lexical_sealed_audit.verified_archive",
                return_value=files,
            ),
            patch(
                "system2_reader_lexical_sealed_audit.open_strong", return_value=parent
            ),
        ):
            with self.assertRaisesRegex(ValueError, "grading"):
                authenticate("synthetic.zip", "parent.zip", expected_digest=PIN)

    def test_tampered_model_input_hash_rejected(self):
        files, parent, _ = fixture()
        entries = [json.loads(x) for x in files["trial/raw-answers.jsonl"].splitlines()]
        entries[0]["reader"]["input_ids_digest"] = "zzzzz"
        raw = b"".join(json_bytes(r) + b"\n" for r in entries)
        files["trial/raw-answers.jsonl"] = raw
        files["trial/raw-seal.json"] = json_bytes(
            dict(
                sha256=hashlib.sha256(raw).hexdigest(),
                rows=CALLS,
                scoring_started=False,
            )
        )
        files["trial/summary.json"] = json_bytes(
            dict(
                json.loads(files["trial/summary.json"]),
                raw_answer_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
        with (
            patch(
                "system2_reader_lexical_sealed_audit.verified_archive",
                return_value=files,
            ),
            patch(
                "system2_reader_lexical_sealed_audit.open_strong", return_value=parent
            ),
        ):
            with self.assertRaisesRegex(ValueError, "compute receipt"):
                authenticate("synthetic.zip", "parent.zip", expected_digest=PIN)

    def test_broken_original_source_denominator_rejected(self):
        files, parent, _ = fixture()
        starts = files["trial/starts.jsonl"].splitlines()
        files["trial/starts.jsonl"] = b"\n".join(starts[:-1]) + b"\n"
        with (
            patch(
                "system2_reader_lexical_sealed_audit.verified_archive",
                return_value=files,
            ),
            patch(
                "system2_reader_lexical_sealed_audit.open_strong", return_value=parent
            ),
        ):
            with self.assertRaisesRegex(ValueError, "census"):
                authenticate("synthetic.zip", "parent.zip", expected_digest=PIN)


if __name__ == "__main__":
    unittest.main()
