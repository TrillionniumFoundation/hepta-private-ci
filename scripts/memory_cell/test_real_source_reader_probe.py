"""Fail-closed real Git snapshot/Reader protocol tests; no pretrained calls."""

import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from real_source_reader_probe import (
    CONDITIONS,
    EVALUATION,
    FROZEN_PLAN_SHA256,
    TIERS,
    build_plan,
    canonical,
    digest,
    locked_plan,
    plan_from_archives,
    score_outputs,
    verify_zip,
    write_once,
)


def pretend_corpus():
    """Small invented source bytes strictly for deterministic negative tests."""
    paths, blobs = [], {}
    for repo in EVALUATION:
        ext = ".rs" if repo == "denoland/deno" else ".py"
        for index in range(3):
            path = f"lib/mod{index}{ext}"
            declarations = [
                (f"fn precise_function_{index}_{j}() {{ }}" if ext == ".rs"
                 else f"def precise_function_{index}_{j}():\n    return {index + j}")
                for j in range(4)
            ]
            raw = ("\n".join(declarations) + "\n").encode()
            sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            paths.append(dict(repo=repo, partition="evaluation", path=path,
                              blob_sha=sha, bytes=len(raw), sha256=digest(raw)))
            blobs[(repo, path)] = raw
    return paths, blobs


def fake_journals(plan, *, deliberate_wrong=False):
    """Self-labelled synthetic rows, NEVER genuine model inference."""
    output = {}
    for tier in TIERS:
        rows = []
        for c in plan["cases"]:
            expected = c["conditions"]["mechanical_support"][0]["marker"]
            for condition in CONDITIONS:
                answer = expected + " [E1]" if not deliberate_wrong else "F99 [E9]"
                identity = digest(tier.encode())
                profile = digest((tier + ":profile").encode())
                receipt = dict(reader_identity=identity, reader_profile=profile,
                               input_tokens=100, generated_tokens=7, seconds=1.0,
                               trainable_parameters=0, answer_postprocessed=False,
                               production_accepted=False)
                rows.append(dict(case_id=c["id"], condition=condition, tier=tier,
                                 question_sha256=digest(c["question"].encode()),
                                 evidence_sha256=digest(canonical(c["conditions"][condition])),
                                 reader_identity=identity, reader_profile=profile,
                                 answer=answer, status="succeeded", receipt=receipt))
        output[tier] = rows
    return output


class RealSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.sources = pretend_corpus()
        self.plan = build_plan(*self.sources)

    def test_balanced_controls_and_masked_declaration(self):
        self.assertEqual(len(self.plan["cases"]), 9)
        self.assertEqual({c["root"] for c in self.plan["cases"]}, set(EVALUATION))
        self.assertEqual({c["root"]: sum(q["root"] == c["root"] for q in self.plan["cases"])
                          for c in self.plan["cases"]}, {c: 3 for c in EVALUATION})
        for c in self.plan["cases"]:
            self.assertEqual(set(c["conditions"]), set(CONDITIONS))
            self.assertFalse(c["conditions"]["none"])
            support = c["conditions"]["mechanical_support"][0]["text"]
            removed = c["conditions"]["removed_declaration"][0]["text"]
            self.assertIn(c["symbol"], support)
            self.assertNotIn(c["symbol"], removed)
            self.assertTrue(c["prerequisite_is_machine_checked_not_human"])
        self.assertFalse(self.plan["independently_human_certified_sufficient_evidence"])
        self.assertFalse(self.plan["production_qualified"])

    def test_machine_score_does_not_become_human_review(self):
        report = score_outputs(self.plan, self.sources, fake_journals(self.plan))
        self.assertEqual(report["original_question_count"], 9)
        self.assertEqual(report["original_real_model_calls"], 72)  # synthetic fixture only
        self.assertEqual(report["reader_conditions"]["smol-135m"]["mechanical_support"]["strict_correct"], 9)
        self.assertFalse(report["independent_human_sufficiency_review"])
        self.assertFalse(report["independently_authenticated_model_calls"])
        self.assertIsNone(report["complete_lifecycle_tco"])

    def test_untrusted_reader_wrong_answers_not_accepted(self):
        result = score_outputs(self.plan, self.sources, fake_journals(self.plan, deliberate_wrong=True))
        self.assertEqual(result["reader_conditions"]["smol-1.7b"]["mechanical_support"]["strict_correct"], 0)
        self.assertEqual(result["reader_conditions"]["smol-1.7b"]["mechanical_support"]["invalid_citation_labels"], 9)

    def test_reference_evidence_drift_is_refused(self):
        records = fake_journals(self.plan)
        records["smol-135m"][0]["evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "detached from frozen source"):
            score_outputs(self.plan, self.sources, records)

    def test_duplicate_attempt_and_reader_identity_forgeries_reject(self):
        records = fake_journals(self.plan)
        records["smol-135m"][1] = records["smol-135m"][0]
        with self.assertRaisesRegex(ValueError, "duplicate original model"):
            score_outputs(self.plan, self.sources, records)
        records = fake_journals(self.plan)
        records["smol-1.7b"][1]["receipt"]["reader_identity"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Reader receipts differ"):
            score_outputs(self.plan, self.sources, records)

    def test_missing_real_attempts_fail_without_silent_denominator_change(self):
        records = fake_journals(self.plan)
        records["smol-1.7b"].pop()
        with self.assertRaisesRegex(ValueError, "missing original model answers"):
            score_outputs(self.plan, self.sources, records)

    def test_plan_mutation_refused_against_source_archive(self):
        changed = copy.deepcopy(self.plan)
        changed["cases"][0]["symbol"] = "not_the_original"
        with self.assertRaisesRegex(ValueError, "regenerated"):
            score_outputs(changed, self.sources, fake_journals(changed))

    def test_external_byte_pin_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "plan.json"
            write_once(target, canonical(self.plan) + b"\n")
            restored = locked_plan(target, digest(target.read_bytes()))
            self.assertEqual(restored, self.plan)
            with self.assertRaisesRegex(ValueError, "changed"):
                locked_plan(target, "0" * 64)
            with self.assertRaisesRegex(ValueError, "must not exist"):
                write_once(target, canonical(self.plan))
            payload = target.read_bytes()
            target.write_bytes(payload.replace(b'"token_limit":1024', b'"token_limit":8192'))
            with self.assertRaisesRegex(ValueError, "plan census drift"):
                locked_plan(target, digest(target.read_bytes()))

    def test_published_real_source_if_available(self):
        source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopen = os.environ.get("MEMORY_REOPEN_ZIP")
        if not (source and reopen):
            self.skipTest("exact historical archives not present in standalone unit job")
        actual = plan_from_archives(Path(source), Path(reopen))
        self.assertEqual(digest(canonical(actual) + b"\n"), FROZEN_PLAN_SHA256)
        self.assertEqual(len(actual["cases"]), 9)
        self.assertEqual(sum(len(c["conditions"]["hybrid_k4"]) for c in actual["cases"]), 27)
        self.assertEqual(actual["source_inventory_sha256"], "5ede9326e2234331f8f7f268a96257089a6703a74e7354206833db1d18f1beb0")

    def test_reject_bogus_git_zip_digest(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bad.zip"
            target.write_bytes(b"not a GitHub archive")
            with self.assertRaisesRegex(ValueError, "whole ZIP digest"):
                verify_zip(target, "0" * 64, 40)


if __name__ == "__main__":
    unittest.main()
