#!/usr/bin/env python3
"""Regression tests against real isolated Git repositories; no remote writes."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from cognitive_store_map_generate import generate
from cognitive_store_map_verify import CLAIMS, HOST, MAP_PATH, MANDATORY_INPUTS
from cognitive_store_map_verify import Invalid, git, object_at, source_path, verify


class MapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for key, value in (("user.name", "Isolated fixture"), ("user.email", "fixture@example.invalid")):
            subprocess.run(["git", "config", key, value], cwd=self.root, check=True)
        self.files = {
            HOST: "pub struct AgentdProductionWriterHost;\n",
            "codex-rs/hepta-agentd/src/runtime.rs": "pub fn reader() {}\n",
            "codex-rs/hepta-cognitive-store/src/lib.rs": "pub fn semantic() {}\n",
            "codex-rs/hepta-memory/src/lib.rs": "pub fn durable() {}\n",
            "codex-rs/hepta-agentd/tests/boundary.rs": "fn regression() {}\n",
            "docs/modules/cognitive.store/TECHNICAL.md": "# Existing detailed guide\n",
            **{path: "# bound input\n" for path in MANDATORY_INPUTS},
        }
        for path, text in self.files.items():
            self.write(path, text)
        base = self.commit("historical source")
        base_tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.write(HOST, "pub struct AgentdProductionWriterHost; // revised source\n")
        row = {
            "schema": "hepta.module-implementation-map.v3", "module": "cognitive.store",
            "sourceBase": {"commit": base, "tree": base_tree},
            "productionImplementation": False,
            "resolvedRoots": ["codex-rs/hepta-cognitive-store"],
            "implementationRoots": ["codex-rs/hepta-memory", "codex-rs/hepta-agentd"],
            "technicalGuide": "docs/modules/cognitive.store/TECHNICAL.md",
            "productCallers": [{"sourcePath": HOST, "nativeSymbol": "AgentdProductionWriterHost",
                                "state": "canonical_production_write_facade"}],
            "readCallers": [{"sourcePath": "codex-rs/hepta-agentd/src/runtime.rs"}],
            "operations": [{"operation": "product_writer_host", "sourcePath": HOST,
                            "nativeSymbol": "AgentdProductionWriterHost",
                            "delegatedCallees": [{"path": "codex-rs/hepta-memory/src/lib.rs"}],
                            "tests": ["codex-rs/hepta-agentd/tests/boundary.rs::regression"]}],
            "claimBoundary": {key: False for key in CLAIMS}, "sourceObjects": [],
        }
        self.write_map(row)
        source = self.commit("author source and definitions")
        self.write_map(generate(self.root, source))
        self.commit("bind reviewed source")

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def read_map(self) -> dict:
        return json.loads((self.root / MAP_PATH).read_text(encoding="utf-8"))

    def write_map(self, row: dict) -> None:
        self.write(MAP_PATH, json.dumps(row, indent=2) + "\n")

    def commit(self, message: str) -> str:
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=self.root, check=True)
        return git(self.root, "rev-parse", "HEAD")

    def verify(self) -> dict:
        return verify(self.root, git(self.root, "rev-parse", "HEAD"),
                      git(self.root, "rev-parse", "HEAD^{tree}"))

    def test_historical_base_and_changed_current_source_both_validate(self) -> None:
        result = self.verify()
        self.assertFalse(result["executionClaim"])
        self.assertNotEqual(object_at(self.root, result["sourceBase"]["commit"], HOST),
                            object_at(self.root, result["candidate"]["commit"], HOST))

    def test_stale_workflow_object_is_rejected(self) -> None:
        self.write(MANDATORY_INPUTS[-1], "# changed workflow\n")
        self.commit("workflow changed after map")
        with self.assertRaisesRegex(Invalid, "source object drift"):
            self.verify()

    def test_new_unmapped_file_in_bound_implementation_root_is_rejected(self) -> None:
        self.write("codex-rs/hepta-memory/src/new_writer.rs", "fn hidden() {}\n")
        self.commit("new source file")
        with self.assertRaisesRegex(Invalid, "source object drift"):
            self.verify()

    def test_read_caller_requires_exact_object(self) -> None:
        row = self.read_map()
        row["sourceObjects"] = [item for item in row["sourceObjects"]
                                if item["path"] != "codex-rs/hepta-agentd/src/runtime.rs"]
        self.write_map(row)
        self.commit("remove read caller binding")
        with self.assertRaisesRegex(Invalid, "inventory mismatch"):
            self.verify()

    def test_verifier_itself_cannot_be_removed_from_inventory(self) -> None:
        row = self.read_map()
        row["sourceObjects"] = [item for item in row["sourceObjects"]
                                if item["path"] != MANDATORY_INPUTS[0]]
        self.write_map(row)
        self.commit("remove verifier binding")
        with self.assertRaisesRegex(Invalid, "inventory mismatch"):
            self.verify()

    def test_duplicate_object_is_rejected(self) -> None:
        row = self.read_map()
        row["sourceObjects"].append(row["sourceObjects"][0])
        self.write_map(row)
        self.commit("duplicate binding")
        with self.assertRaisesRegex(Invalid, "duplicate source object"):
            self.verify()

    def test_wrong_candidate_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(Invalid, "expected SHA"):
            verify(self.root, "0" * 40, git(self.root, "rev-parse", "HEAD^{tree}"))
        with self.assertRaisesRegex(Invalid, "expected tree"):
            verify(self.root, git(self.root, "rev-parse", "HEAD"), "0" * 40)

    def test_dirty_source_cannot_be_qualified_or_regenerated(self) -> None:
        self.write(HOST, "uncommitted mutation\n")
        with self.assertRaisesRegex(Invalid, "not clean"):
            self.verify()
        with self.assertRaisesRegex(Invalid, "commit source"):
            generate(self.root, git(self.root, "rev-parse", "HEAD"))

    def test_claims_cannot_be_self_promoted(self) -> None:
        row = self.read_map()
        row["claimBoundary"]["productExecutionProved"] = True
        self.write_map(row)
        self.commit("unproved success")
        with self.assertRaisesRegex(Invalid, "unproved claim"):
            self.verify()

    def test_unsafe_and_recursive_paths_are_rejected(self) -> None:
        for path in ("../escape", "/absolute", "a/../b", "a//b", "a\\b", MAP_PATH):
            with self.subTest(path=path), self.assertRaises(Invalid):
                source_path(path)

    def test_symlink_cannot_be_a_source_object(self) -> None:
        target = self.root / HOST
        target.unlink()
        target.symlink_to("runtime.rs")
        self.commit("symlink source")
        with self.assertRaisesRegex(Invalid, "regular file or tree"):
            object_at(self.root, "HEAD", HOST)

    def test_generator_is_deterministic_read_only_and_preserves_base(self) -> None:
        before = self.read_map()
        head = git(self.root, "rev-parse", "HEAD")
        first, second = generate(self.root, head), generate(self.root, head)
        self.assertEqual(first, second)
        self.assertEqual(first["sourceBase"], before["sourceBase"])
        self.assertEqual(self.read_map(), before)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
