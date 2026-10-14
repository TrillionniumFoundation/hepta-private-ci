"""Tamper controls and a separately pinned real archive integration."""

import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from system2_native_receipt import (
    ARMS,
    CONDITIONS,
    PHASES,
    analyze,
    audit,
    strict_json,
    verified_archive,
)


def fixture():
    plan = dict(
        arms=list(ARMS),
        checkpoints=[16, 32, 48],
        source_commit="fixture",
        question_ids={"train": ["train"], **{p: [p] for p in PHASES}},
        production_accepted=False,
        reasoning_superiority=False,
        reader_inventory="reader",
        reader_input_token_limit=4096,
        limits=dict(operations=100000, seconds=30.0, evidence=3, candidates=4),
    )
    rows, scores, controls = [], [], []
    for q in PHASES:
        rec = dict(
            reader_identity="reader",
            reader_profile="profile",
            query_digest=q,
            input_ids_digest=q + "input",
            generated_ids_digest=q + "output",
            token_limit=4096,
            input_tokens=100,
            generated_tokens=10,
            seconds=0.1,
            delivered_evidence=[],
            answer_postprocessed=False,
            trainable_parameters=0,
            production_accepted=False,
        )
        for c in CONDITIONS:
            controls.append(
                dict(
                    question_id=q,
                    condition=c,
                    status="succeeded",
                    answer="fixture",
                    receipt=copy.deepcopy(rec),
                )
            )
        for a in ARMS:
            for stage in plan["checkpoints"]:
                rows.append(
                    dict(
                        question_id=q,
                        arm=a,
                        checkpoint=stage,
                        family="one-family",
                        feature_digest=q,
                        status="succeeded",
                        selected=[],
                        answer="fixture",
                        reader=copy.deepcopy(rec),
                        policy=dict(solvers=[]),
                        cost=dict(
                            elapsed_seconds=0.2,
                            limits=copy.deepcopy(plan["limits"]),
                            attempted_operations=dict(reader_calls=1),
                        ),
                    )
                )
                scores.append(
                    dict(
                        question_id=q,
                        arm=a,
                        checkpoint=stage,
                        family="one-family",
                        failure=False,
                        diagnostic_f1=None if q == "test" else 0.0,
                    )
                )
    return plan, rows, scores, controls


class ReceiptTests(unittest.TestCase):
    def test_complete_no_evidence_collapse_is_rejected(self):
        report = analyze(*fixture())
        self.assertEqual(report["arms_collapsed_to_no_evidence"], list(ARMS[3:]))
        self.assertEqual(report["verdict"], "reject_current_policy_candidate")
        self.assertEqual(report["recorded_source_family_groups"], 1)
        self.assertEqual(report["unique_evaluation_questions"], 4)
        self.assertEqual(report["arms"]["48/rag"]["all_planned_f1_bounds"], [0.0, 0.25])
        self.assertEqual(report["new_reader_calls"], 0)

    def test_missing_duplicate_and_unknown_slot_refused(self):
        plan, rows, scores, controls = fixture()
        for bad in (
            rows[:-1],
            rows + rows[:1],
            [dict(rows[0], arm="renamed"), *rows[1:]],
        ):
            with self.assertRaises(ValueError):
                analyze(plan, bad, scores, controls)

    def test_family_feature_and_score_identity_drift(self):
        for field in ("family", "feature_digest"):
            data = fixture()
            data[1][0][field] = "other"
            with self.assertRaises(ValueError):
                analyze(*data)
        data = fixture()
        data[2][0]["diagnostic_f1"] = True
        with self.assertRaises(ValueError):
            analyze(*data)

    def test_same_prompt_changed_tokens_cannot_be_learning_gain(self):
        for key in ("generated_ids_digest", "reader_profile"):
            data = fixture()
            data[1][0]["reader"][key] = "changed"
            with self.assertRaises(ValueError):
                analyze(*data)

    def test_no_evidence_control_with_source_refused(self):
        data = fixture()
        data[3][0]["receipt"]["delivered_evidence"] = ["not-empty"]
        with self.assertRaises(ValueError):
            analyze(*data)

    def test_failed_execution_stays_in_full_denominator(self):
        data = fixture()
        data[1][0]["status"] = "failed"
        data[2][0]["failure"] = True
        result = analyze(*data)
        self.assertEqual(result["arms"]["16/rag"]["failed"], 1)
        self.assertEqual(result["arms"]["16/rag"]["planned"], 4)
        self.assertEqual(result["arms"]["16/rag"]["all_planned_f1_bounds"], [0.0, 0.25])

    def test_missing_human_control_is_not_fabricated(self):
        data = fixture()
        for row in data[3]:
            if row["condition"] in CONDITIONS[2:]:
                row["status"] = "unavailable"
                row.pop("receipt")
                row.pop("answer")
        report = analyze(*data)
        self.assertEqual(
            report["control_statuses"]["human_sufficient"], {"unavailable": 4}
        )
        self.assertFalse(report["reader_adequacy_established"])

    def test_nonfinite_counters_and_wrong_budget_rejected(self):
        for field, value in (("elapsed_seconds", float("nan")), ("limits", {})):
            data = fixture()
            data[1][0]["cost"][field] = value
            with self.assertRaises(ValueError):
                analyze(*data)

    def test_json_duplicate_and_nonfinite_refused(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_outer_inner_inventory_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.zip"
            content = b"source"
            sha = hashlib.sha256(content).hexdigest()
            for name, manifest in (
                ("file", f"{sha}  ./file\n"),
                ("../file", f"{sha}  ./../file\n"),
                ("file", f"{'0' * 64}  ./file\n"),
                ("file", ""),
            ):
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(name, content)
                    z.writestr("SHA256SUMS", manifest)
                pin = hashlib.sha256(path.read_bytes()).hexdigest()
                if name == "file" and manifest == f"{sha}  ./file\n":
                    self.assertEqual(verified_archive(path, pin)["file"], content)
                else:
                    with self.assertRaises(ValueError):
                        verified_archive(path, pin)
                with self.assertRaises(ValueError):
                    verified_archive(path, "0" * 64)

    @unittest.skipUnless(
        os.environ.get("HEPTA_SYSTEM2_ORIGINAL_ARCHIVE"),
        "pinned original archive not staged",
    )
    def test_actual_original_native_census_and_negative_control(self):
        result = audit(Path(os.environ["HEPTA_SYSTEM2_ORIGINAL_ARCHIVE"]))
        self.assertEqual(result["successful_policy_records"], 768)
        self.assertEqual(result["verified_manifest_files"], 51)
        self.assertEqual(result["source_family_counts"]["longmemeval:001be529"], 8)
        self.assertEqual(
            result["historical_sampler_schedule"]["questions_scheduled_only_empty"], 10
        )
        self.assertEqual(
            result["arms"]["48/fbsde_stochastic"][
                "same_request_and_output_as_no_evidence"
            ],
            32,
        )
        self.assertGreater(
            result["arms"]["48/wrong_stitch_control"]["nonconverged_path_solvers"], 0
        )


if __name__ == "__main__":
    unittest.main()
