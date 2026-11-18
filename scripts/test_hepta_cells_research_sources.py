"""Behavioral coverage for source metadata isolation; all rows are fixtures."""

import copy
import hashlib
import unittest

from hepta_cells.research_sources import audit_source_manifest


def row(task_id, split):
    return {
        "task_id": task_id,
        "origin_repository": "example/repo",
        "origin_id": "issue:" + task_id,
        "origin_commit": "a" * 40,
        "root_cause_group": "reviewed-root:" + task_id,
        "parent_task_ids": [],
        "transformation_provenance": [],
        "split": split,
        "origin_kind": "real_source",
        "exposure": "sealed",
        "task_sha256": hashlib.sha256(task_id.encode()).hexdigest(),
        "oracle_sha256": "b" * 64,
        "generator_sha256": "c" * 64,
        "source_receipt_sha256": "d" * 64,
        "generation_seed": 0,
        "origin_time": "2026-01-01T00:00:00Z",
        "available_at": "2026-01-02T00:00:00Z",
        "admission_time": "2026-01-03T00:00:00Z",
        "authorization": {
            "training_allowed": True,
            "evaluation_allowed": True,
            "rights_basis": "test fixture",
            "receipt_sha256": "e" * 64,
        },
    }


class SourceAuditTests(unittest.TestCase):
    def test_same_repository_and_generator_do_not_merge_different_origins(self):
        rows = [row("one", "A"), row("two", "B")]
        original = copy.deepcopy(rows)
        report = audit_source_manifest(rows)
        self.assertEqual(report["status"], "METADATA_VALID")
        self.assertEqual(report["counts"]["declared_dependency_components"], 2)
        self.assertEqual(rows, original)
        self.assertFalse(report["research_execution_authorized"])
        self.assertIsNone(report["authenticated_independent_source_groups"])

    def test_origin_root_template_and_identical_bytes_each_prevent_split_leakage(self):
        for field in (
            "origin_id",
            "root_cause_group",
            "source_template_id",
            "task_sha256",
        ):
            with self.subTest(field=field):
                rows = [row("one", "A"), row("two", "C")]
                rows[1]["origin_repository"] = "Example/Repo"
                rows[0][field] = rows[1][field] = rows[0].get(
                    field, "reviewed-template"
                )
                report = audit_source_manifest(rows)
                self.assertEqual(report["counts"]["declared_dependency_components"], 1)
                self.assertIn(
                    "DEPENDENCY_CROSSES_SPLITS",
                    {r["code"] for r in report["blocking_reasons"]},
                )

    def test_parent_transitive_closure_cannot_be_evaded_by_relabeling(self):
        rows = [row("one", "A"), row("two", "A"), row("three", "D_cold")]
        rows[1]["parent_task_ids"] = ["one"]
        rows[2]["parent_task_ids"] = ["two"]
        report = audit_source_manifest(rows)
        self.assertEqual(
            report["components"],
            [
                {
                    "task_ids": ["one", "three", "two"],
                    "declared_splits": ["A", "D_cold"],
                    "metadata_eligible": False,
                }
            ],
        )

    def test_replay_seed_changes_do_not_increase_group_count(self):
        rows = [row("one", "A"), row("two", "A")]
        rows[1].update(origin_id=rows[0]["origin_id"], generation_seed=4)
        self.assertEqual(
            audit_source_manifest(rows)["counts"]["declared_dependency_components"], 1
        )

    def test_gold_read_cannot_become_unseen_by_assignment(self):
        source = row("one", "C")
        source["exposure"] = "gold_read"
        report = audit_source_manifest([source])
        self.assertEqual(report["counts"]["metadata_eligible_components"], 0)
        self.assertIn(
            "HELDOUT_ALREADY_EXPOSED_OR_UNKNOWN",
            {r["code"] for r in report["blocking_reasons"]},
        )

    def test_missing_provenance_authority_and_chronology_block(self):
        source = row("one", "A")
        source.update(source_receipt_sha256=None, available_at="2027-01-01T00:00:00Z")
        source["authorization"]["training_allowed"] = False
        self.assertEqual(
            {r["code"] for r in audit_source_manifest([source])["blocking_reasons"]},
            {
                "MISSING_COMMITMENT",
                "INVALID_SOURCE_CHRONOLOGY",
                "MISSING_SOURCE_AUTHORITY",
            },
        )

    def test_unknown_parent_and_cycles_block_without_recursion_overflow(self):
        first, second = row("one", "A"), row("two", "A")
        first["parent_task_ids"] = ["two", "unknown"]
        second["parent_task_ids"] = ["one"]
        codes = {
            r["code"]
            for r in audit_source_manifest([first, second])["blocking_reasons"]
        }
        self.assertTrue({"UNRESOLVED_PARENT", "LINEAGE_CYCLE"} <= codes)

    def test_duplicates_empty_and_malformed_rows_block(self):
        for rows in ([], [None], [row("one", "A"), row("one", "B")]):
            with self.subTest(rows=rows):
                self.assertEqual(audit_source_manifest(rows)["status"], "BLOCKED")
        source = row("one", "A")
        source.update(
            parent_task_ids=[{}],
            transformation_provenance=None,
            generation_seed=True,
            origin_time=None,
        )
        self.assertEqual(audit_source_manifest([source])["status"], "BLOCKED")
        source["split"] = {}
        self.assertEqual(audit_source_manifest([source])["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
