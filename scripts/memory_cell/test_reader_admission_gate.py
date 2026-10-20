"""Fail-closed source-pinned research disposition regression tests."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import reader_admission_gate as gate


def synthetic():
    cal = {
        f"k{k}": {"strict_success": n, "input_tokens": 100 * k, "planned": 8}
        for k, n in ((1, 4), (2, 4), (3, 4), (4, 4), (6, 2))
    }
    evaluation = {
        arm: {"strict_success": correct, "input_tokens": tokens, "planned": 8}
        for arm, correct, tokens in (
            ("selected_k", 5, 3961),
            ("hybrid_k4", 3, 10806),
            ("hybrid_k6", 2, 15463),
            ("hybrid_k4_reversed", 3, 10806),
            ("single_hop", 4, 4575),
            ("entity_time", 8, 5752),
            ("organized", 8, 5179),
            ("program_support", 8, 5179),
            ("empty", 0, 1630),
        )
    }
    loo = {
        "planned_calibration_questions": 8,
        "folds": [dict(omitted=str(k)) for k in range(8)],
        "stable_to_one_calibration_case_removal": False,
        "distinct_choices": 2,
    }
    citations = {
        "planned_attempts": 72,
        "planned_questions": 8,
        "by_arm": {
            arm: dict(
                attempted=8,
                strict_task_success=row["strict_success"],
                correct_with_full_program_declared_citations=(
                    4
                    if arm in ("entity_time", "organized", "program_support")
                    else min(3, row["strict_success"])
                ),
            )
            for arm, row in evaluation.items()
        },
    }
    replay = dict(generating_commit=gate.GENERATION_COMMIT, production_accepted=False)
    policy = dict(selected_k=1, production_accepted=False)
    return dict(
        cal=cal,
        evaluation=evaluation,
        frozen_k=1,
        loo=loo,
        citation=citations,
        replay=replay,
        policy=policy,
        source=gate.GENERATION_COMMIT,
    )


class ExactResearchGateTests(unittest.TestCase):
    def test_aggregate_summary_does_not_certify_original_sample_census(self):
        report = gate.assess_reproduced(**synthetic())
        self.assertIsNone(report["complete_calibration"])
        self.assertIsNone(report["complete_evaluation"])
        self.assertIsNone(report["authored_question_scope_count"])
        self.assertEqual(report["reported_calibration_attempts"], 40)
        self.assertEqual(report["reported_evaluation_attempts"], 72)
        self.assertFalse(report["census_verified"])
        self.assertFalse(report["independent_readonly_replay_complete"])
        self.assertEqual(report["incremental_graph_task_success"], 0)
        self.assertEqual(report["incremental_graph_complete_citations"], 0)
        self.assertEqual(report["organized_input_tokens_saved"], 573)
        self.assertEqual(report["organized_input_tokens_saved_per_question"], 71.625)
        self.assertFalse(report["calibration_leave_one_out_stable"])
        self.assertFalse(report["graph_task_gain_qualified"])
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["independent_semantic_citation_precision"])

    def test_missing_or_unregistered_summary_arms_fail(self):
        for phase, arm in (("cal", "k6"), ("evaluation", "empty")):
            for mutation in ("missing", "extra"):
                with self.subTest(phase=phase, mutation=mutation):
                    fixture = synthetic()
                    if mutation == "missing":
                        del fixture[phase][arm]
                    else:
                        extra = "k8" if phase == "cal" else "unregistered"
                        fixture[phase][extra] = dict(fixture[phase][arm])
                    with self.assertRaisesRegex(ValueError, "arm census"):
                        gate.assess_reproduced(**fixture)

    def test_summary_counts_are_bounded_integers(self):
        for phase, arm in (("cal", "k6"), ("evaluation", "entity_time")):
            for field, value in (
                ("planned", 8.0),
                ("strict_success", -1),
                ("strict_success", 9),
                ("strict_success", True),
                ("input_tokens", -1),
                ("input_tokens", True),
            ):
                with self.subTest(phase=phase, field=field, value=value):
                    fixture = synthetic()
                    fixture[phase][arm][field] = value
                    if phase == "evaluation" and field == "strict_success":
                        fixture["citation"]["by_arm"][arm]["strict_task_success"] = (
                            value
                        )
                    with self.assertRaises(ValueError):
                        gate.assess_reproduced(**fixture)

    def test_boolean_calibration_choice_is_not_an_integer_policy(self):
        fixture = synthetic()
        fixture["frozen_k"] = True
        with self.assertRaisesRegex(ValueError, "different frozen experiment"):
            gate.assess_reproduced(**fixture)

    def test_wrong_calibration_policy_fails(self):
        fixture = synthetic()
        fixture["frozen_k"] = 2
        with self.assertRaisesRegex(ValueError, "top-k freeze"):
            gate.assess_reproduced(**fixture)

    def test_missing_citation_evaluation_arm_fails(self):
        fixture = synthetic()
        del fixture["citation"]["by_arm"]["entity_time"]
        with self.assertRaisesRegex(ValueError, "citation-arm"):
            gate.assess_reproduced(**fixture)

    def test_forged_formal_citation_success_fails(self):
        fixture = synthetic()
        fixture["citation"]["by_arm"]["organized"][
            "correct_with_full_program_declared_citations"
        ] = 9
        with self.assertRaisesRegex(ValueError, "contradictory"):
            gate.assess_reproduced(**fixture)

    def test_forged_admission_or_reader_id_fails(self):
        fixture = synthetic()
        fixture["replay"]["production_accepted"] = True
        with self.assertRaises(ValueError):
            gate.assess_reproduced(**fixture)
        fixture = synthetic()
        fixture["policy"]["production_accepted"] = True
        with self.assertRaises(ValueError):
            gate.assess_reproduced(**fixture)

    def test_incomplete_scope_census_fails(self):
        fixture = synthetic()
        fixture["evaluation"]["organized"]["planned"] = 7
        with self.assertRaisesRegex(ValueError, "incomplete"):
            gate.assess_reproduced(**fixture)

    def test_different_source_commit_fails(self):
        fixture = synthetic()
        fixture["source"] = "a" * 40
        with self.assertRaisesRegex(ValueError, "different"):
            gate.assess_reproduced(**fixture)

    def test_json_duplicate_and_nan_reject(self):
        for payload in (b'{"one":1,"one":2}', b'{"one":NaN}'):
            with self.assertRaises(ValueError):
                gate.strict_json(payload)

    def test_missing_and_rewritten_raw_rows_fail(self):
        one = dict(
            question_id="q0",
            arm="a",
            status="succeeded",
            answer="site_00000000",
            receipt=dict(
                reader_identity=gate.MODEL_ID,
                input_tokens=10,
                generated_tokens=5,
            ),
        )
        rows = [one | {"question_id": f"q{i}"} for i in range(8)]
        scored = [
            row
            | {
                "strict_task_success": True,
                "required_sources_covered": True,
            }
            for row in rows
        ]
        container = {
            "phase/raw-answers.jsonl": (
                "\n".join(json.dumps(row) for row in rows) + "\n"
            ).encode(),
            "phase/scored-answers.json": json.dumps(scored).encode(),
        }
        a, b, ids = gate._rows(container, "phase", ("a",))
        self.assertEqual(len(ids), 8)
        altered = dict(container)
        altered["phase/raw-answers.jsonl"] = (
            "\n".join(json.dumps(row) for row in rows[:-1]) + "\n"
        ).encode()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            gate._rows(altered, "phase", ("a",))
        changed = deepcopy(scored)
        changed[0]["answer"] = "site_forged"
        altered["phase/raw-answers.jsonl"] = container["phase/raw-answers.jsonl"]
        altered["phase/scored-answers.json"] = json.dumps(changed).encode()
        with self.assertRaisesRegex(ValueError, "rewritten"):
            gate._rows(altered, "phase", ("a",))

    def test_full_archive_sha_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "test.zip"
            payload = b"original-plan"
            manifest = (
                hashlib.sha256(payload).hexdigest() + "  ./plan.json\n"
            ).encode()
            with zipfile.ZipFile(file, "w") as z:
                z.writestr("plan.json", payload)
                z.writestr("SHA256SUMS", manifest)
            pin = hashlib.sha256(file.read_bytes()).hexdigest()
            with patch.dict(gate.PINS, {"original": (pin, 1)}):
                self.assertEqual(
                    gate.verified_zip(file, kind="original")["plan.json"], payload
                )
                file.write_bytes(file.read_bytes() + b"mutation")
                with self.assertRaisesRegex(ValueError, "archive digest"):
                    gate.verified_zip(file, kind="original")

    def test_each_registered_arm_requires_each_unique_question_and_success(self):
        rows = [
            dict(
                question_id=f"q{i}",
                arm=arm,
                status="succeeded",
                answer="synthetic fixture only",
                receipt=dict(reader_identity=gate.MODEL_ID, input_tokens=10),
            )
            for arm in gate.TEST_ARMS
            for i in range(8)
        ]

        def container(raw):
            scored = [
                row | dict(strict_task_success=True, required_sources_covered=True)
                for row in raw
            ]
            return {
                "evaluation/raw-answers.jsonl": (
                    "\n".join(json.dumps(row) for row in raw) + "\n"
                ).encode(),
                "evaluation/scored-answers.json": json.dumps(scored).encode(),
            }

        received, _, ids = gate._rows(container(rows), "evaluation", gate.TEST_ARMS)
        self.assertEqual(len(received), 72)
        self.assertEqual(len(ids), 8)
        for mutation in ("missing_row", "missing_arm", "duplicate", "arm", "failed"):
            with self.subTest(mutation=mutation):
                changed = deepcopy(rows)
                if mutation == "missing_row":
                    changed.pop()
                elif mutation == "missing_arm":
                    changed = [row for row in changed if row["arm"] != "empty"]
                elif mutation == "duplicate":
                    changed[-1]["question_id"] = changed[-2]["question_id"]
                elif mutation == "arm":
                    changed[-1]["arm"] = "unregistered"
                else:
                    changed[-1]["status"] = "failed"
                with self.assertRaises(ValueError):
                    gate._rows(container(changed), "evaluation", gate.TEST_ARMS)

    @unittest.skipUnless(
        os.environ.get("HEPTA_REAL_STRONG_RAG_ARTIFACTS"),
        "real archived GitHub artifacts not mounted",
    )
    def test_exact_real_archives_if_available(self):
        directory = Path(os.environ["HEPTA_REAL_STRONG_RAG_ARTIFACTS"])
        value = gate.audit(
            directory / "memorycell-real-11669174727.zip",
            directory / "memorycell-real-11696514149.zip",
            directory / "memorycell-real-11696898778.zip",
        )
        self.assertEqual(value["complete_calibration"], 40)
        self.assertEqual(value["complete_evaluation"], 72)
        self.assertEqual(value["authored_question_scope_count"], 8)
        self.assertTrue(value["census_verified"])
        self.assertTrue(value["independent_readonly_replay_complete"])
        self.assertEqual(value["incremental_graph_task_success"], 0)
        self.assertFalse(value["production_accepted"])


if __name__ == "__main__":
    unittest.main()
