"""Source-bound rank-order robustness tests. All model outputs are synthetic."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from real_git_order_v4 import (
    ARMS,
    ORDER_PLAN_SHA256,
    build_order_plan,
    locked_order_plan,
    pinned_journal,
    plan_from_sources,
    score,
)
from real_source_reader_probe import (
    TIERS,
    canonical,
    digest,
    expected_reader_delivery,
    plan_from_archives,
    real_source,
)


def fixture_journals(plan, original_v3):
    target = {
        x["id"]: x["conditions"]["mechanical_support"][0]["marker"]
        for x in original_v3["cases"]
    }
    result = {}
    for tier in TIERS:
        rows = []
        reader = digest(tier.encode())
        profile = digest((tier + ":fixed-research-only").encode())
        for case in plan["cases"]:
            for arm in ARMS:
                evidence = case["conditions"][arm]
                place = next(
                    i
                    for i, e in enumerate(evidence, 1)
                    if e["marker"] == target[case["id"]]
                )
                receipt = dict(
                    expected_reader_delivery(case, arm),
                    reader_identity=reader,
                    reader_profile=profile,
                    input_ids_digest=digest(
                        (tier + ":input:" + case["id"] + arm).encode()
                    ),
                    generated_ids_digest=digest(
                        (tier + ":generation:" + case["id"] + arm).encode()
                    ),
                    token_limit=1024,
                    input_tokens=144,
                    generated_tokens=8,
                    seconds=1.0,
                    trainable_parameters=0,
                    answer_postprocessed=False,
                    production_accepted=False,
                )
                rows.append(
                    dict(
                        case_id=case["id"],
                        arm=arm,
                        tier=tier,
                        question_sha256=digest(case["question"].encode()),
                        evidence_sha256=digest(canonical(evidence)),
                        reader_identity=reader,
                        reader_profile=profile,
                        status="succeeded",
                        answer=f"{target[case['id']]} [E{place}]",
                        receipt=receipt,
                    )
                )
        result[tier] = rows
    return result


class GitOrderV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopened = os.environ.get("MEMORY_REOPEN_ZIP")
        if not source or not reopened:
            raise unittest.SkipTest("exact original Git ZIP inputs required")
        cls.source_zip = Path(source)
        cls.reopen_zip = Path(reopened)
        cls.v3 = plan_from_archives(cls.source_zip, cls.reopen_zip)
        cls.sources = real_source(cls.source_zip, cls.reopen_zip)
        cls.plan = plan_from_sources(cls.source_zip, cls.reopen_zip)

    def original(self):
        return fixture_journals(self.plan, self.v3)

    def test_frozen_plan_and_same_unordered_source_bytes(self):
        self.assertEqual(digest(canonical(self.plan) + b"\n"), ORDER_PLAN_SHA256)
        self.assertEqual(len(self.plan["cases"]), 9)
        self.assertFalse(self.plan["production_qualified"])
        self.assertFalse(self.plan["oracle_or_target_in_reader_plan"])
        for case in self.plan["cases"]:
            a, b = [case["conditions"][arm] for arm in ARMS]
            self.assertEqual(b, list(reversed(a)))
            self.assertEqual({e["marker"] for e in a}, {e["marker"] for e in b})
            self.assertNotIn("mechanical_support", case["conditions"])

    def test_original_rank_and_reverse_no_model_baselines(self):
        report = score(self.plan, self.sources, self.original())
        self.assertEqual(report["attempted_reader_calls"], 36)
        self.assertEqual(report["mechanical_null_rank1_original"], 7)
        self.assertEqual(report["mechanical_null_rank1_reversed"], 1)
        self.assertEqual(report["reader_executions_total"], 36)  # fixtures only
        for tier in TIERS:
            self.assertEqual(
                report["result"][tier]["lexical_order"]["reader_correct"], 9
            )
            self.assertEqual(
                report["result"][tier]["reverse_order"]["reader_correct"], 9
            )
            self.assertEqual(report["result"][tier]["lexical_order"]["reader_wins"], 2)
            self.assertEqual(report["result"][tier]["reverse_order"]["reader_wins"], 8)
            self.assertEqual(
                report["result"][tier]["source_order_sensitivity"]["equal_outcomes"], 9
            )
        self.assertFalse(report["learned_parameter_gain_established"])
        self.assertFalse(report["independent_semantic_judgement"])
        self.assertFalse(report["production_qualified"])

    def test_reject_duplicate_attempt(self):
        rows = self.original()
        rows[TIERS[0]][1] = deepcopy(rows[TIERS[0]][0])
        with self.assertRaisesRegex(ValueError, "duplicate original Reader"):
            score(self.plan, self.sources, rows)

    def test_reject_model_receipt_evidence_forgery(self):
        rows = self.original()
        rows[TIERS[0]][0]["receipt"]["delivered_evidence"][0]["excerpt"] = "fabricated"
        with self.assertRaisesRegex(ValueError, "delivered source"):
            score(self.plan, self.sources, rows)

    def test_changed_question_or_source_refused(self):
        rows = self.original()
        rows[TIERS[0]][0]["question_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "original question/evidence"):
            score(self.plan, self.sources, rows)

    def test_reject_version_mix_or_target_oracle_leak(self):
        other = deepcopy(self.plan)
        other["cases"][0]["conditions"]["mechanical_support"] = []
        with self.assertRaisesRegex(ValueError, "post-run ranking"):
            score(other, self.sources, self.original())

    def test_failed_answer_not_promoted(self):
        rows = self.original()
        for tier in TIERS:
            row = rows[tier][0]
            row.update(status="failed", answer=None, receipt=None)
        result = score(self.plan, self.sources, rows)
        self.assertEqual(result["reader_executions_total"], 34)
        self.assertFalse(result["production_qualified"])

    def test_incomplete_or_mixed_model_census_refused(self):
        rows = self.original()
        rows[TIERS[0]].pop()
        with self.assertRaisesRegex(ValueError, "complete original model"):
            score(self.plan, self.sources, rows)
        rows = self.original()
        rows[TIERS[1]][1]["reader_identity"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "delivered source"):
            score(self.plan, self.sources, rows)

    def test_reject_same_model_relabelled_as_stronger_reference(self):
        rows = self.original()
        fake = rows[TIERS[0]][0]
        for row in rows[TIERS[1]]:
            row["reader_identity"] = fake["reader_identity"]
            row["receipt"]["reader_identity"] = fake["reader_identity"]
        with self.assertRaisesRegex(ValueError, "distinct model identity"):
            score(self.plan, self.sources, rows)

    def test_cli_roundtrip_and_external_original_pins(self):
        rows = self.original()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan.json"
            plan.write_bytes(canonical(self.plan) + b"\n")
            self.assertEqual(locked_order_plan(plan, ORDER_PLAN_SHA256), self.plan)
            with self.assertRaisesRegex(ValueError, "precommitted plan SHA"):
                locked_order_plan(plan, "0" * 64)
            cmd = [
                sys.executable,
                str(Path(__file__).with_name("real_git_order_v4.py")),
                "score",
                "--source-zip",
                str(self.source_zip),
                "--reopen-zip",
                str(self.reopen_zip),
                "--plan",
                str(plan),
                "--plan-sha256",
                ORDER_PLAN_SHA256,
            ]
            for tier in TIERS:
                journal = root / (tier + ".jsonl")
                raw = b"".join(canonical(x) + b"\n" for x in rows[tier])
                journal.write_bytes(raw)
                cmd += ["--" + tier, str(journal), "--" + tier + "-sha256", digest(raw)]
                self.assertEqual(len(pinned_journal(journal, digest(raw))), 18)
                with self.assertRaisesRegex(ValueError, "independently pinned"):
                    pinned_journal(journal, "0" * 64)
            output = root / "report.json"
            cmd += ["--output", str(output)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                json.loads(output.read_bytes())["reader_executions_total"], 36
            )
            rerun = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(
                rerun.returncode, 0, "do not overwrite immutable report"
            )

    def test_frozen_v4_plan_source_regenerated(self):
        self.assertEqual(build_order_plan(self.v3), self.plan)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "prepared.json"
            cmd = [
                sys.executable,
                str(Path(__file__).with_name("real_git_order_v4.py")),
                "prepare",
                "--source-zip",
                str(self.source_zip),
                "--reopen-zip",
                str(self.reopen_zip),
                "--plan",
                str(target),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(digest(target.read_bytes()), ORDER_PLAN_SHA256)


if __name__ == "__main__":
    unittest.main()
