"""Bounded integrity and archive tests; these fixtures do not run Rust or mutants."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evidence_inventory as inventory
import run_qualification as qualification


class EvidenceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        (self.evidence / "mutations").mkdir()
        (self.evidence / "quality-receipt.json").write_text('{"fixture":true}\n')
        (self.evidence / "mutations/mutation-receipt.json").write_text('{"fixture":true}\n')

    def test_roundtrip_binds_every_byte_with_stable_sorted_paths(self):
        manifest = inventory.collect_inventory(self.evidence)
        names = [row["path"] for row in manifest["files"]]
        self.assertEqual(names, ["mutations/mutation-receipt.json", "quality-receipt.json"])
        self.assertEqual(manifest, inventory.verify_inventory(self.evidence, manifest))
        for row in manifest["files"]:
            content = (self.evidence / row["path"]).read_bytes()
            self.assertEqual(row["bytes"], len(content))
            self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())
        (self.evidence / "receipt.json").write_text("excluded to avoid a cycle")
        (self.evidence / "receipt.sha256").write_text("excluded sidecar")
        self.assertEqual(inventory.collect_inventory(self.evidence), manifest)

    def test_nested_receipts_are_not_excluded(self):
        manifest = inventory.collect_inventory(self.evidence)
        (self.evidence / "mutations/receipt.json").write_text("nested evidence")
        with self.assertRaises(ValueError):
            inventory.verify_inventory(self.evidence, manifest)

    def test_symlinked_file_directory_and_excluded_sidecar_reject(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "data").write_text("borrowed")
        for name, target in (("linked", outside), ("linked.log", outside / "data"),
                             ("receipt.json", outside / "data")):
            with self.subTest(name=name):
                link = self.evidence / name
                link.symlink_to(target)
                with self.assertRaises(ValueError):
                    inventory.collect_inventory(self.evidence)
                link.unlink()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_fifo_rejects_without_opening_or_waiting(self):
        os.mkfifo(self.evidence / "blocked.log")
        with self.assertRaises(ValueError):
            inventory.collect_inventory(self.evidence)

    def test_entry_depth_path_and_byte_budgets_fail_closed(self):
        for constant, limit in (("MAX_ENTRIES", 1), ("MAX_DEPTH", 0),
                                ("MAX_PATH_BYTES", 4), ("MAX_TOTAL_BYTES", 1)):
            with self.subTest(bound=constant), patch.object(inventory, constant, limit):
                with self.assertRaises(ValueError):
                    inventory.collect_inventory(self.evidence)

    def test_byte_budget_accepts_exact_limit_and_rejects_one_more(self):
        manifest = inventory.collect_inventory(self.evidence)
        with patch.object(inventory, "MAX_TOTAL_BYTES", manifest["total_bytes"]):
            self.assertEqual(inventory.collect_inventory(self.evidence), manifest)
            with (self.evidence / "quality-receipt.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(ValueError):
                inventory.collect_inventory(self.evidence)

    def test_typed_metadata_and_exact_closed_inventory(self):
        original = inventory.collect_inventory(self.evidence)
        actions = [lambda m: m.update(total_bytes=True),
                   lambda m: m["files"][0].update(bytes=False),
                   lambda m: m["files"][0].update(path="../outside"),
                   lambda m: m["files"][0].update(path="a//b"),
                   lambda m: m["files"][0].update(sha256="0" * 64),
                   lambda m: m["files"].append(copy.deepcopy(m["files"][0])),
                   lambda m: m["files"].reverse(),
                   lambda m: m.update(unexpected=True)]
        for action in actions:
            value = copy.deepcopy(original)
            action(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                inventory.verify_inventory(self.evidence, value)

    def test_fresh_output_does_not_overwrite_previous_evidence(self):
        empty = self.root / "new"
        inventory.require_fresh_output(empty)
        empty.mkdir()
        inventory.require_fresh_output(empty)
        saved = self.evidence / "quality-receipt.json"
        before = saved.read_bytes()
        with self.assertRaises(ValueError):
            inventory.require_fresh_output(self.evidence)
        self.assertEqual(saved.read_bytes(), before)
        link = self.root / "symlink"
        link.symlink_to(empty)
        with self.assertRaises(ValueError):
            inventory.require_fresh_output(link)

    def test_archive_copies_only_finished_evidence_not_sibling_builds(self):
        source = self.root / "scratch/evidence"
        source.mkdir(parents=True)
        (source / "mutation-receipt.json").write_text('{"fixture":true}')
        (source / "build.log").write_text("synthetic fixture log")
        target = source.parent / "cognitive-mutation-target"
        target.mkdir()
        (target / "binary").write_bytes(b"not evidence")
        destination = self.evidence / "archived"
        inventory.archive(source, destination)
        self.assertEqual(inventory.collect_inventory(source), inventory.collect_inventory(destination))
        self.assertFalse((destination / "binary").exists())
        self.assertTrue((target / "binary").exists())
        with self.assertRaises(ValueError):
            inventory.archive(source, destination)

    def test_archive_rejects_missing_result_and_overlapping_paths(self):
        source = self.root / "source-results"
        source.mkdir()
        with self.assertRaises(ValueError):
            inventory.archive(source, self.root / "archive")
        (source / "mutation-receipt.json").write_text("fixture")
        with self.assertRaises(ValueError):
            inventory.archive(source, source / "nested")

    def test_execution_paths_reject_source_ancestor_and_scratch_aliases(self):
        source = self.root / "qualified-source"
        source.mkdir()
        output = self.root / "upload"
        qualification.validate_execution_paths(source, output)
        for overlapping in (source, source / "evidence", self.root):
            with self.subTest(path=overlapping), self.assertRaises(ValueError):
                qualification.validate_execution_paths(source, overlapping)
        scratch = self.root / "cognitive-mutation-work"
        scratch.symlink_to(source)
        with self.assertRaises(ValueError):
            qualification.validate_execution_paths(source, output)

    def test_command_plan_keeps_mutation_build_and_source_out_of_upload(self):
        source = self.root / "qualified-source"
        output = self.root / "upload"
        plan = {name: argv for name, argv, _ in qualification.command_plan(source, "native", output)}
        mutation = plan["targeted-source-mutations"]
        working_evidence = Path(mutation[mutation.index("--output") + 1])
        build_target = working_evidence.parent / "cognitive-mutation-target"
        for path in (working_evidence, build_target):
            self.assertNotIn(output, path.parents)
            self.assertNotIn(source, path.parents)
        archive = plan["archive-mutation-evidence"]
        self.assertEqual(Path(archive[archive.index("--archive") + 1]), working_evidence)
        self.assertEqual(Path(archive[archive.index("--destination") + 1]), output / "mutations")


if __name__ == "__main__":
    unittest.main()
