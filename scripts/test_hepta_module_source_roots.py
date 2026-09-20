"""Regression coverage for source alias resolution without authority transfer."""

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hepta_module_source_roots import resolve_source_roots


class SourceRootTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.module = {
            "id": "runtime.fixture",
            "rootBindings": [{"path": "alias"}, {"path": "adapter"}],
        }
        for name in ("alias", "implementation", "adapter", "legacy"):
            (self.root / name).mkdir()
        (self.root / "legacy/callee.rs").write_text("fn run() {}\n", encoding="utf-8")
        self.binding = {
            "schema_version": 1,
            "module": "runtime.fixture",
            "declared_root": "alias",
            "implementation_root": "implementation",
            "binding_mode": "canonical_alias",
            "duplicate_cargo_package_created": False,
            "model_authority": False,
            "provider_authority": False,
            "source_evidence_paths": ["legacy/callee.rs"],
        }
        self.write_binding()

    def write_binding(self):
        (self.root / "alias/BINDING.json").write_text(
            json.dumps(self.binding), encoding="utf-8"
        )

    def test_alias_preserves_declarations_and_exact_file_scope(self):
        before = copy.deepcopy(self.module)
        self.assertEqual(
            resolve_source_roots(self.root, self.module),
            ["implementation", "legacy/callee.rs", "adapter"],
        )
        self.assertEqual(self.module, before)
        self.assertNotIn("legacy", resolve_source_roots(self.root, self.module))

    def test_plain_and_missing_roots_retain_existing_behavior(self):
        module = {
            "id": "plain",
            "rootBindings": [{"path": "adapter"}, {"path": "missing"}],
        }
        self.assertEqual(resolve_source_roots(self.root, module), ["adapter"])

    def test_migration_uses_aliases_without_changing_evidence_or_claims(self):
        spec = importlib.util.spec_from_file_location(
            "implementation_maps",
            Path(__file__).with_name("hepta-implementation-maps.py"),
        )
        maps = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(maps)
        self.module.update(
            {"owner": "owner", "deputy": "deputy", "technicalDocument": "guide"}
        )
        source_base = {"commit": "a" * 40, "tree": "b" * 40}
        row = {
            "module": self.module["id"],
            "sourceBase": source_base,
            "operations": [
                {
                    "operation": "run",
                    "nativeSymbol": "fn run(",
                    "sourcePath": "legacy/callee.rs",
                    "tests": [{"path": "test.py"}],
                }
            ],
            "repositoryControlledGaps": ["Real product integration remains open."],
            "claimBoundary": {"productionImplementation": False, "activation": False},
        }
        before = copy.deepcopy(row)
        with mock.patch.object(maps, "ROOT", self.root):
            result = maps.migrate_map(
                row, self.module, {self.module["id"]: "lane"}, source_base
            )
            repeated = maps.migrate_map(
                result, self.module, {self.module["id"]: "lane"}, source_base
            )
        self.assertEqual(row, before)
        self.assertEqual(result, repeated)
        self.assertEqual(
            result["resolvedRoots"], ["implementation", "legacy/callee.rs", "adapter"]
        )
        self.assertEqual(result["declaredRoots"], ["alias", "adapter"])
        self.assertEqual(
            result["repositoryControlledGaps"], row["repositoryControlledGaps"]
        )
        self.assertEqual(
            result["operations"][0]["tests"], row["operations"][0]["tests"]
        )
        self.assertEqual(result["sourceBase"], source_base)
        self.assertFalse(result["claimBoundary"]["activation"])

    def test_source_base_tracks_latest_source_commit_not_document_only_head(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Hepta Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "hepta-test@example.invalid"],
            cwd=repo,
            check=True,
        )
        source = repo / "source"
        docs = repo / "docs"
        source.mkdir()
        docs.mkdir()
        (source / "lib.rs").write_text("pub fn first() {}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "source"], cwd=repo, check=True)
        source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

        (docs / "guide.md").write_text("documentation only\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "docs"], cwd=repo, check=True)
        docs_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(source_commit, docs_head)

        spec = importlib.util.spec_from_file_location(
            "implementation_maps_source_base",
            Path(__file__).with_name("hepta-implementation-maps.py"),
        )
        maps = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(maps)
        module = {"id": "fixture", "rootBindings": [{"path": "source"}]}
        with mock.patch.object(maps, "ROOT", repo):
            self.assertEqual(
                maps.latest_module_source_base(module),
                {"commit": source_commit, "tree": source_tree},
            )
            self.assertTrue(maps.source_roots_match_head(module, source_commit))

            (source / "lib.rs").write_text("pub fn second() {}\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "source-2"], cwd=repo, check=True)
            source_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                maps.latest_module_source_base(module)["commit"],
                source_head,
            )
            self.assertFalse(maps.source_roots_match_head(module, source_commit))

    def test_identity_version_and_authority_mismatches_reject(self):
        original = copy.deepcopy(self.binding)
        for key, value in [
            ("module", "other"),
            ("declared_root", "other"),
            ("schema_version", 2),
            ("schema_version", True),
            ("binding_mode", "dynamic"),
            ("runtimeAuthority", True),
            ("model_authority", True),
            ("provider_authority", 0),
            ("duplicate_cargo_package_created", True),
        ]:
            with self.subTest(key=key, value=value):
                self.binding = {**original, key: value}
                self.write_binding()
                with self.assertRaises(ValueError):
                    resolve_source_roots(self.root, self.module)

    def test_paths_cannot_escape_or_broaden_to_a_crate(self):
        for value in (
            "../outside",
            "/tmp",
            "legacy",
            "legacy//callee.rs",
            "legacy/./callee.rs",
            "legacy\\callee.rs",
            "missing.rs",
            "C:/outside",
            "",
        ):
            with self.subTest(value=value):
                self.binding["source_evidence_paths"] = [value]
                self.write_binding()
                with self.assertRaises(ValueError):
                    resolve_source_roots(self.root, self.module)

    def test_duplicate_keys_and_resolved_paths_reject(self):
        self.binding["source_evidence_paths"].append("legacy/callee.rs")
        self.write_binding()
        with self.assertRaisesRegex(ValueError, "duplicate resolved"):
            resolve_source_roots(self.root, self.module)
        (self.root / "alias/BINDING.json").write_text(
            '{"module":"a","module":"b"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "duplicate binding"):
            resolve_source_roots(self.root, self.module)

    def test_nested_alias_binding_rejects_live_and_dangling_symlinks(self):
        binding = self.root / "implementation/BINDING.json"
        for target in ("missing.json", "alias/BINDING.json"):
            with self.subTest(target=target):
                binding.symlink_to(self.root / target)
                try:
                    with self.assertRaisesRegex(ValueError, "nested source alias"):
                        resolve_source_roots(self.root, self.module)
                finally:
                    binding.unlink()

    def test_symlink_targets_and_binding_reject(self):
        (self.root / "linked").symlink_to(
            self.root / "legacy", target_is_directory=True
        )
        self.binding["source_evidence_paths"] = ["linked/callee.rs"]
        self.write_binding()
        with self.assertRaisesRegex(ValueError, "symlink"):
            resolve_source_roots(self.root, self.module)
        path = self.root / "alias/BINDING.json"
        path.rename(self.root / "binding.json")
        path.symlink_to(self.root / "binding.json")
        with self.assertRaisesRegex(ValueError, "invalid alias binding"):
            resolve_source_roots(self.root, self.module)


if __name__ == "__main__":
    unittest.main()
