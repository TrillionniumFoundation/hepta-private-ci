"""Source-cut to complete Reader execution binding: fail-closed, no model calls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from paired_source_cut import audit, bind_contract, canonical_sha, read_pinned

EMPTY_SHA = hashlib.sha256(b"").hexdigest()
KINDS = ("new_fact", "updated_fact", "composition", "program")
ARMS = (
    "base:none",
    "base:retrieved",
    "base:sufficient",
    "base:lesion",
    "reference:none",
    "reference:retrieved",
    "reference:sufficient",
    "reference:lesion",
    "base:organized",
    "base:learned_policy",
    "base:knowledge",
    "base:knowledge_only",
)


def fixture():
    cut = dict(
        schema="hepta.memory.prospective-source-cut.v1",
        contains_answers=False,
        publisher_answer_oracle=False,
        registered_at="2026-10-12T00:00:00Z",
        frozen_at="2026-10-14T00:00:00Z",
        policy_snapshot_sha256="6" * 64,
        knowledge_snapshot_sha256="7" * 64,
        sources=[
            dict(
                id="training",
                family="training-root",
                partition="train",
                kind="new_fact",
                source_digest="1" * 64,
                source_at="2026-10-13T00:00:00Z",
                exposed_at="2026-10-13T00:00:00Z",
            ),
            dict(
                id="selection",
                family="selection-root",
                partition="select",
                kind="updated_fact",
                source_digest="2" * 64,
                source_at="2026-10-13T00:00:00Z",
                exposed_at="2026-10-13T00:00:00Z",
            ),
        ],
    )
    for i, kind in enumerate(KINDS):
        cut["sources"].append(
            dict(
                id=f"case-{i}",
                family=f"test-family-{i}",
                partition="test",
                kind=kind,
                source_digest=str(i + 3) * 64,
                question_sha256="d" * 64,
                candidate_pool_sha256="e" * 64,
                source_at="2026-10-13T02:00:00Z",
                exposed_at="2026-10-15T00:00:00Z",
            )
        )
    cut_sha = canonical_sha(cut)
    cases = []
    rows = []
    for i, kind in enumerate(KINDS):
        src = cut["sources"][i + 2]
        cases.append(
            dict(
                id=src["id"],
                family=src["family"],
                kind=kind,
                question_sha256=src["question_sha256"],
                snapshot_frozen_at=cut["frozen_at"],
                revealed_at=src["exposed_at"],
                candidate_pool_sha256=src["candidate_pool_sha256"],
                policy_snapshot_sha256=cut["policy_snapshot_sha256"],
                knowledge_snapshot_sha256=cut["knowledge_snapshot_sha256"],
            )
        )
        for arm in ARMS:
            rows.append(
                dict(
                    task_id=src["id"],
                    arm=arm,
                    source_cut_sha256=cut_sha,
                    original_source_sha256=src["source_digest"],
                    status="succeeded",
                    reader_sha256="f" * 64
                    if arm.startswith("reference:")
                    else "b" * 64,
                    prompt_template_sha256="a" * 64,
                    tools_sha256="c" * 64,
                    candidate_pool_sha256=src["candidate_pool_sha256"],
                    evidence_sha256=EMPTY_SHA
                    if arm in ("base:none", "reference:none", "base:knowledge_only")
                    else "5" * 64,
                    specialization_sha256=(
                        "6" * 64
                        if arm == "base:learned_policy"
                        else "7" * 64
                        if arm in ("base:knowledge", "base:knowledge_only")
                        else EMPTY_SHA
                    ),
                    input_budget=2048,
                    output_budget=64,
                    input_tokens=32,
                    output_tokens=8,
                    strict_task_success=False,
                    complete_citation_chain=False,
                )
            )
    plan = dict(
        schema="hepta.memory.four-stage-prospective-plan.v1",
        arms=list(ARMS),
        cases=cases,
        contains_gold_answers=False,
        answer_space_oracle=False,
        source_cut_sha256=cut_sha,
        frozen_execution=dict(
            base_reader_sha256="b" * 64,
            reference_reader_sha256="f" * 64,
            prompt_template_sha256="a" * 64,
            tools_sha256="c" * 64,
            input_budget=2048,
            output_budget=64,
        ),
    )
    return cut, plan, rows


class PairedSourceContractTests(unittest.TestCase):
    def test_complete_four_strata_twelve_arm_source_pairing(self):
        cut, plan, rows = fixture()
        result = bind_contract(cut, plan, rows)
        self.assertEqual(result["bound_task_count"], 4)
        self.assertEqual(result["test_families"], 4)

    def test_source_cut_must_be_bound_to_evaluation_plan(self):
        cut, plan, rows = fixture()
        plan["source_cut_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "different source cut"):
            bind_contract(cut, plan, rows)

    def test_source_cut_cannot_change_after_freeze(self):
        cut, plan, rows = fixture()
        cut["sources"][0]["source_digest"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "different source cut"):
            bind_contract(cut, plan, rows)

    def test_wrong_test_root_or_stratum_is_rejected(self):
        for key, new, message in (
            ("family", "another-root", "source-family"),
            ("kind", "program", "task-stratum"),
        ):
            cut, plan, rows = fixture()
            plan["cases"][0][key] = new
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    bind_contract(cut, plan, rows)

    def test_unchanged_ids_cannot_swap_question_or_answer_space(self):
        for key, message in (
            ("question_sha256", "question identity"),
            ("candidate_pool_sha256", "candidate pool"),
        ):
            cut, plan, rows = fixture()
            plan["cases"][1][key] = "9" * 64
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    bind_contract(cut, plan, rows)

    def test_absent_question_commitment_does_not_pass_with_null(self):
        cut, plan, rows = fixture()
        cut["sources"][2].pop("question_sha256")
        plan["source_cut_sha256"] = canonical_sha(cut)
        rows = [dict(row, source_cut_sha256=plan["source_cut_sha256"]) for row in rows]
        with self.assertRaisesRegex(ValueError, "question identity|precommitted"):
            bind_contract(cut, plan, rows)

    def test_test_census_cannot_drop_or_insert_source(self):
        cut, plan, rows = fixture()
        plan["cases"].pop()
        with self.assertRaisesRegex(ValueError, "test source census mismatch"):
            bind_contract(cut, plan, rows)
        cut, plan, rows = fixture()
        plan["cases"].append(copy.deepcopy(plan["cases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate evaluation task identity"):
            bind_contract(cut, plan, rows)

    def test_sealed_snapshot_and_reveal_must_match_source_cut(self):
        for key, message in (
            ("snapshot_frozen_at", "snapshot epoch"),
            ("revealed_at", "task reveal time"),
            ("policy_snapshot_sha256", "policy was not frozen"),
            ("knowledge_snapshot_sha256", "knowledge was not frozen"),
        ):
            cut, plan, rows = fixture()
            plan["cases"][1][key] = "wrong-value"
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    bind_contract(cut, plan, rows)

    def test_every_attempt_binds_to_correct_original_source(self):
        for key, new, message in (
            ("source_cut_sha256", "9" * 64, "different source cut"),
            ("original_source_sha256", "9" * 64, "original evidence bytes"),
            ("task_id", "extra-task", "unregistered evaluation"),
        ):
            cut, plan, rows = fixture()
            rows[2][key] = new
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    bind_contract(cut, plan, rows)

    def test_no_disappearing_failed_attempts(self):
        cut, plan, rows = fixture()
        with self.assertRaisesRegex(ValueError, "full attempted"):
            bind_contract(cut, plan, rows[:-1])
        rows[5]["status"] = "failed"
        result = bind_contract(cut, plan, rows)
        self.assertEqual(result["bound_task_count"], 4)

    def test_source_partition_leakage_denied_by_registered_cut(self):
        cut, plan, rows = fixture()
        cut["sources"][2]["family"] = "training-root"
        with self.assertRaisesRegex(ValueError, "family crosses"):
            bind_contract(cut, plan, rows)
        cut, plan, rows = fixture()
        cut["sources"][4]["source_digest"] = cut["sources"][1]["source_digest"]
        with self.assertRaisesRegex(ValueError, "source bytes cross partition"):
            bind_contract(cut, plan, rows)

    def test_revealed_before_freeze_is_denied(self):
        cut, plan, rows = fixture()
        cut["sources"][2]["exposed_at"] = "2026-10-13T01:00:00Z"
        with self.assertRaisesRegex(ValueError, "chronology"):
            bind_contract(cut, plan, rows)

    def test_source_capture_signed_by_no_one_is_not_authenticated(self):
        try:
            import four_stage_evidence  # noqa: F401
        except ModuleNotFoundError:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                raise
            self.skipTest("Full source checkout needed; hosted CI MUST execute")
        cut, plan, rows = fixture()
        result = audit(cut, plan, rows)
        self.assertEqual(result["paired_attempts"], 48)
        self.assertEqual(result["decision"], "DENY_ALL")
        self.assertFalse(result["original_model_inference_verification"])
        self.assertFalse(result["production_accepted"])

    def test_unhashable_or_duplicate_task_id_rejected_without_exception_leak(self):
        cut, plan, rows = fixture()
        plan["cases"][0]["id"] = []
        with self.assertRaisesRegex(ValueError, "typed task identity"):
            bind_contract(cut, plan, rows)
        cut, plan, rows = fixture()
        rows[0]["task_id"] = []
        with self.assertRaisesRegex(ValueError, "unregistered evaluation"):
            bind_contract(cut, plan, rows)

    def test_strict_file_sha_no_json_duplicate_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{"x": 1, "x": 2}')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                read_pinned(path, sha, 1024)
            path.write_text('{"x": NaN}')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "nonfinite JSON"):
                read_pinned(path, sha, 1024)
            path.write_text('{"a": true}')
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                read_pinned(path, sha, 1024)
            symlink = Path(directory) / "linked.json"
            symlink.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "regular JSON input"):
                read_pinned(
                    symlink, hashlib.sha256(path.read_bytes()).hexdigest(), 1024
                )


if __name__ == "__main__":
    unittest.main()
