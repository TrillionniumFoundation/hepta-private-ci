"""Cross-version auditor behavior tests; synthetic archives are not model runs."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from event_posthoc_citation_receipt import (
    SCHEMA,
    checked_archive,
    check_lineage,
    sha_file,
)


class SourceSeparationTests(unittest.TestCase):
    def lineage(self):
        source = "a" * 40
        plan = "b" * 64
        policy = "c" * 64
        model = "d" * 64
        frozen = dict(
            source_commit=source,
            original_test_plan_sha256=plan,
            reader_identity=model,
            frozen_before_evaluation=True,
            production_accepted=False,
        )
        run = dict(
            source_commit=source,
            test_plan_sha256=plan,
            policy_sha256=policy,
            phase="evaluation",
            training_during_query=False,
        )
        report = dict(
            source_commit=source,
            total_attempts=72,
            test_task_count=8,
            production_accepted=False,
        )
        inventory = dict(inventory_digest=model)
        return source, frozen, run, report, inventory, plan, policy

    def assert_lineage(self, value):
        source, frozen, run, report, inventory, plan, policy = value
        check_lineage(
            source,
            frozen,
            run,
            report,
            inventory,
            plan_sha=plan,
            policy_sha=policy,
            attempts=72,
        )

    def test_source_identity_and_72_original_rows_are_required(self):
        self.assert_lineage(self.lineage())

    def test_refuses_relabelled_generating_commit_or_test_plan(self):
        import copy

        for field, replacement in (
            ("source_commit", "f" * 40),
            ("original_test_plan_sha256", "0" * 64),
            ("reader_identity", "1" * 64),
        ):
            value = list(copy.deepcopy(self.lineage()))
            value[1][field] = replacement
            with self.assertRaises(ValueError):
                self.assert_lineage(value)

    def test_refuses_missing_procedure_and_output_census(self):
        import copy

        for field, replacement in (
            ("total_attempts", 71),
            ("test_task_count", 7),
            ("production_accepted", True),
        ):
            value = list(copy.deepcopy(self.lineage()))
            value[3][field] = replacement
            with self.assertRaises(ValueError):
                self.assert_lineage(value)

    def test_refuses_unfrozen_policy_and_online_weight_updates(self):
        import copy

        value = list(copy.deepcopy(self.lineage()))
        value[1]["frozen_before_evaluation"] = False
        with self.assertRaises(ValueError):
            self.assert_lineage(value)
        value = list(copy.deepcopy(self.lineage()))
        value[2]["training_during_query"] = True
        with self.assertRaises(ValueError):
            self.assert_lineage(value)

    def test_rejects_unsafe_archive_traversal_and_duplicate_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            zip_path = root / "input.zip"
            for entries in (
                {"../leak": "fake"},
                {"/absolute": "fake"},
                {"a\\bad": "fake"},
                {"./alias": "fake"},
            ):
                with zipfile.ZipFile(zip_path, "w") as archive:
                    for name, payload in entries.items():
                        archive.writestr(name, payload)
                with self.assertRaises(ValueError):
                    checked_archive(zip_path, sha_file(zip_path), root / "output")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("duplicate", "first")
                archive.writestr("duplicate", "second")
            with self.assertRaises(ValueError):
                checked_archive(zip_path, sha_file(zip_path), root / "output")

    def test_binds_outer_zip_bytes_before_extraction(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            zip_path = root / "archive.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("safe/data.json", json.dumps({"ok": True}))
            pinned = sha_file(zip_path)
            self.assertEqual(checked_archive(zip_path, pinned, root / "data"), 1)
            self.assertEqual(
                json.loads((root / "data/safe/data.json").read_text()),
                {"ok": True},
            )
            with self.assertRaises(ValueError):
                checked_archive(zip_path, "0" * 64, root / "bad")
            with zip_path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaises(ValueError):
                checked_archive(zip_path, pinned, root / "bad")

    def test_schema_never_claims_trained_memory_or_semantic_entailment(self):
        self.assertEqual(SCHEMA, "hepta.memory-strong-rag.posthoc-citation-audit.v1")


if __name__ == "__main__":
    unittest.main()
