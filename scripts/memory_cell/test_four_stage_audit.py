"""Adversarial structural tests; fixtures are NOT model capability evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from four_stage_audit import CONDITIONS, COST_PARTS, EXTRA, SCHEMA, audit, strict_file


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture():
    readers = {
        name: dict(
            weights=h(name),
            prompt=h("fixed prompt"),
            tool_acl=h("same tools"),
            input_limit=2048,
            output_limit=64,
        )
        for name in ("baseline", "reference")
    }
    tasks = [
        dict(
            id=f"task_{i}",
            family=f"family_{i}",
            kind=kind,
            source_cut=100,
            write_frozen_at=101,
            task_exposed_at=102,
            pool_sha256=h(f"pool{i}"),
            frontier_sha256=h(f"frontier{i}"),
            critical_evidence_id=f"source_{i}",
        )
        for i, kind in enumerate(
            ("new_fact", "updated_fact", "cross_experience", "program")
        )
    ]
    plan = dict(
        schema=SCHEMA,
        source_commit="a" * 40,
        frozen_plan_sha256=h("fixed plan"),
        readers=readers,
        tasks=tasks,
    )
    rows = []
    for task in tasks:
        for reader in ("baseline", "reference"):
            for condition in CONDITIONS + (EXTRA if reader == "baseline" else ()):
                ids = (
                    []
                    if condition in ("none", "module_only")
                    else ["other"]
                    if condition == "ablated"
                    else [task["critical_evidence_id"], "other"]
                    if condition == "reviewed"
                    else ["common"]
                    if condition in ("organized", "knowledge")
                    else ["other"]
                )
                succeeded = condition not in ("none", "ablated")
                good = succeeded and (reader == "reference" or condition != "retrieved")
                if reader == "baseline" and condition in (
                    "learned_policy",
                    "knowledge",
                ):
                    good = True
                rows.append(
                    dict(
                        id=task["id"],
                        reader=reader,
                        condition=condition,
                        generating_commit=plan["source_commit"],
                        frozen_plan_sha256=plan["frozen_plan_sha256"],
                        reader_weights=readers[reader]["weights"],
                        prompt=readers[reader]["prompt"],
                        tool_acl=readers[reader]["tool_acl"],
                        input_limit=2048,
                        output_limit=64,
                        pool_sha256=task["pool_sha256"],
                        frontier_sha256=task["frontier_sha256"],
                        evidence_ids=ids,
                        evidence_sha256=h("-".join(ids)),
                        answer_sha256=h("original-answer") if succeeded else None,
                        status="succeeded" if succeeded else "failed",
                        task_success=good if succeeded else None,
                        program_trace_sha256=h("worker-trace")
                        if succeeded and task["kind"] == "program"
                        else None,
                        program_verified=good
                        if succeeded and task["kind"] == "program"
                        else None,
                        diagnostic_calls=1,
                        input_tokens=512 if succeeded else 0,
                        cost_usd=None,
                        write_sha256=h(
                            "knowledge" if condition == "module_only" else condition
                        )
                        if condition in ("learned_policy", "knowledge", "module_only")
                        else None,
                    )
                )
    ledger = dict(
        unit="usd",
        queries_reused=20,
        arms={
            arm: {
                **{phase: None for phase in COST_PARTS},
                "retained_raw_evidence_bytes": 1200,
                "retained_index_bytes": 300,
                "storage_included_in_maintenance": False,
            }
            for arm in (
                "retrieved",
                "organized",
                "learned_policy",
                "knowledge",
                "module_only",
            )
        },
    )
    return plan, rows, ledger


class FourStageAuditTest(unittest.TestCase):
    def test_complete_development_matrix_does_not_promote(self):
        result = audit(*fixture())
        self.assertEqual(result["planned_model_calls"], 56)
        self.assertEqual(result["actual_successful_calls"], 40)
        self.assertEqual(
            result["capacity_diagnoses"]["retrieval_or_evidence_packaging_bottleneck"],
            4,
        )
        self.assertEqual(
            result["learning_disposition"]["knowledge"],
            "reject_no_independent_task_gain",
        )
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["lifecycle_cost"]["organized"]["total_lifecycle_usd"])

    def test_reader_identity_and_entitlement_cannot_drift(self):
        for field, value in (
            ("reader_weights", h("different")),
            ("prompt", h("different")),
            ("tool_acl", h("different")),
            ("input_limit", 4096),
        ):
            with self.subTest(field=field):
                p, rows, costs = fixture()
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    audit(p, rows, costs)

    def test_reference_cannot_receive_better_evidence_by_accident(self):
        p, rows, c = fixture()
        row = next(
            r
            for r in rows
            if r["id"] == "task_0"
            and r["reader"] == "reference"
            and r["condition"] == "retrieved"
        )
        row["evidence_ids"] = ["extra"]
        row["evidence_sha256"] = h("extra")
        with self.assertRaisesRegex(ValueError, "different evidence"):
            audit(p, rows, c)

    def test_ablated_condition_must_remove_registered_premise(self):
        p, rows, c = fixture()
        row = next(r for r in rows if r["condition"] == "ablated")
        for match in rows:
            if match["id"] == row["id"] and match["condition"] == "ablated":
                match["evidence_ids"] = ["other", "extra"]
        with self.assertRaisesRegex(ValueError, "exactly the registered premise"):
            audit(p, rows, c)

    def test_parameter_only_cannot_smuggle_raw_evidence(self):
        p, rows, c = fixture()
        row = next(r for r in rows if r["condition"] == "module_only")
        row["evidence_ids"] = ["leaked"]
        with self.assertRaisesRegex(ValueError, "no-evidence"):
            audit(p, rows, c)

    def test_learned_head_same_evidence_is_mandatory(self):
        p, rows, c = fixture()
        row = next(r for r in rows if r["condition"] == "knowledge")
        row["evidence_sha256"] = h("changed")
        with self.assertRaisesRegex(ValueError, "identical"):
            audit(p, rows, c)

    def test_source_task_exposure_leakage_denied(self):
        p, rows, c = fixture()
        p["tasks"][0]["write_frozen_at"] = 102
        with self.assertRaisesRegex(ValueError, "before task"):
            audit(p, rows, c)

    def test_no_missing_attempts_or_duplication(self):
        p, rows, c = fixture()
        with self.assertRaises(ValueError):
            audit(p, rows[:-1], c)
        rows[0] = deepcopy(rows[1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit(p, rows, c)

    def test_unavailable_evidence_cannot_be_called_a_successful_qa(self):
        p, rows, c = fixture()
        row = next(
            r
            for r in rows
            if r["condition"] == "reviewed" and r["reader"] == "baseline"
        )
        row.update(status="unavailable", task_success=None, answer_sha256=None)
        # An ablation for an unavailable reviewed context is forbidden.
        with self.assertRaisesRegex(ValueError, "ablation requires"):
            audit(p, rows, c)

    def test_program_task_requires_original_execution_trace(self):
        p, rows, c = fixture()
        row = next(
            r for r in rows if r["id"] == "task_3" and r["status"] == "succeeded"
        )
        row["program_trace_sha256"] = None
        with self.assertRaisesRegex(ValueError, "sha256"):
            audit(p, rows, c)

    def test_footprint_storage_and_unknown_cost_preserved(self):
        p, rows, c = fixture()
        for arm in c["arms"]:
            c["arms"][arm].update({phase: 0.5 for phase in COST_PARTS})
        report = audit(p, rows, c)["lifecycle_cost"]["organized"]
        self.assertIsNone(report["total_lifecycle_usd"])
        c["arms"]["organized"]["storage_included_in_maintenance"] = True
        report = audit(p, rows, c)["lifecycle_cost"]["organized"]
        self.assertEqual(report["total_lifecycle_usd"], 13.0)
        self.assertEqual(report["retained_raw_evidence_bytes"], 1200)

    def test_research_positive_is_still_not_qualified(self):
        p, rows, c = fixture()
        for row in rows:
            if (
                row["reader"] == "baseline"
                and row["condition"] == "organized"
                and row["id"] == "task_0"
            ):
                row["task_success"] = False
                row["program_verified"] = None
        result = audit(p, rows, c)
        self.assertEqual(
            result["learning_disposition"]["knowledge"],
            "new_prospective_evaluation_required",
        )
        self.assertFalse(result["allow_parametric_promotion"])

    def test_sha_pinned_files_reject_mutation_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "original.json"
            value = b'{"x": 1}\n'
            path.write_bytes(value)
            self.assertEqual(
                strict_file(path, hashlib.sha256(value).hexdigest()), {"x": 1}
            )
            path.write_bytes(b'{"x": 2}\n')
            with self.assertRaisesRegex(ValueError, "pin mismatch"):
                strict_file(path, hashlib.sha256(value).hexdigest())
            path.write_bytes(b'{"x": 1, "x": 2}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                strict_file(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
