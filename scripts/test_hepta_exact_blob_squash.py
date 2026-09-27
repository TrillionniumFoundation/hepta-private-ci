from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("hepta-implementation-maps.py")
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("hepta_implementation_maps", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExactBlobSquashIdentityTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def test_non_ancestor_observation_requires_exact_path_object_equivalence(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src/value.txt").write_text("base\n", encoding="utf-8")
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "Identity Test")
            self.git(root, "config", "user.email", "identity@invalid.example")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "base")
            base = self.git(root, "rev-parse", "HEAD")
            base_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            (root / "src/value.txt").write_text("candidate\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "feature")
            observed = self.git(root, "rev-parse", "HEAD")
            observed_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            self.git(root, "checkout", "-q", base)
            (root / "src/value.txt").write_text("candidate\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "squash equivalent")
            squash = self.git(root, "rev-parse", "HEAD")
            squash_tree = self.git(root, "rev-parse", "HEAD^{tree}")
            self.assertEqual(observed_tree, squash_tree)
            self.assertNotEqual(observed, squash)
            with self.assertRaises(subprocess.CalledProcessError):
                self.git(root, "merge-base", "--is-ancestor", observed, squash)

            row = {
                "module": "control.engineering",
                "sourceBase": {"commit": base, "tree": base_tree},
                "mappingSourceIdentityMode": "exact_blob",
                "sourceBaseIdentityMode": "object_provenance_v1",
                "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
                "observationIdentityMode": "path_object_equivalence_v1",
                "observedAtHead": {"commit": observed, "tree": observed_tree},
                "observedSourcePaths": ["src"],
                "operations": [
                    {
                        "operation": "value",
                        "sourcePath": "src/value.txt",
                        "tests": [],
                        "delegatedCallees": [],
                    }
                ],
            }
            old_root = module.ROOT
            module.ROOT = root
            try:
                checked = module.verify_source_identity(
                    row,
                    ["src"],
                    {"commit": squash, "tree": squash_tree},
                    check_checkout=False,
                )
                self.assertEqual(checked, ["src", "src/value.txt"])

                (root / "src/value.txt").write_text("drift\n", encoding="utf-8")
                self.git(root, "add", ".")
                self.git(root, "commit", "-qm", "drift")
                drift = self.git(root, "rev-parse", "HEAD")
                drift_tree = self.git(root, "rev-parse", "HEAD^{tree}")
                with self.assertRaises(module.SourceDrift):
                    module.verify_source_identity(
                        row,
                        ["src"],
                        {"commit": drift, "tree": drift_tree},
                        check_checkout=False,
                    )

                ancestor_only = dict(row)
                ancestor_only["sourceBaseIdentityMode"] = "ancestor_provenance_v1"
                ancestor_only["sourceBase"] = {
                    "commit": observed,
                    "tree": observed_tree,
                }
                with self.assertRaises(subprocess.CalledProcessError):
                    module.verify_source_identity(
                        ancestor_only,
                        ["src"],
                        {"commit": squash, "tree": squash_tree},
                        check_checkout=False,
                    )

                object_provenance = dict(row)
                object_provenance["sourceBase"] = {
                    "commit": observed,
                    "tree": observed_tree,
                }
                module.verify_source_identity(
                    object_provenance,
                    ["src"],
                    {"commit": squash, "tree": squash_tree},
                    check_checkout=False,
                )

                invalid_tree = dict(object_provenance)
                invalid_tree["sourceBase"] = {
                    "commit": observed,
                    "tree": base_tree,
                }
                with self.assertRaises(ValueError):
                    module.verify_source_identity(
                        invalid_tree,
                        ["src"],
                        {"commit": squash, "tree": squash_tree},
                        check_checkout=False,
                    )
            finally:
                module.ROOT = old_root


    def test_legacy_path_only_source_and_observation_survive_equivalent_squash(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src/value.txt").write_text("base\n", encoding="utf-8")
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "Identity Test")
            self.git(root, "config", "user.email", "identity@invalid.example")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "base")
            base = self.git(root, "rev-parse", "HEAD")

            (root / "src/value.txt").write_text("candidate\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "feature")
            observed = self.git(root, "rev-parse", "HEAD")
            observed_tree = self.git(root, "rev-parse", "HEAD^{tree}")

            self.git(root, "checkout", "-q", base)
            (root / "src/value.txt").write_text("candidate\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "squash equivalent")
            squash = self.git(root, "rev-parse", "HEAD")
            squash_tree = self.git(root, "rev-parse", "HEAD^{tree}")
            self.assertEqual(observed_tree, squash_tree)

            legacy = {
                "module": "legacy.path.only",
                "sourceBase": {"commit": observed, "tree": observed_tree},
                "resolvedRoots": ["src"],
                "operations": [],
            }
            observed_row = {
                **legacy,
                "module": "observed.path.only",
                "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
                "observedAtHead": {"commit": observed, "tree": observed_tree},
                "observedSourcePaths": ["src"],
            }
            old_root = module.ROOT
            module.ROOT = root
            try:
                self.assertEqual(
                    module.verify_source_identity(
                        legacy,
                        ["src"],
                        {"commit": squash, "tree": squash_tree},
                        check_checkout=False,
                    ),
                    ["src"],
                )
                self.assertEqual(
                    module.verify_source_identity(
                        observed_row,
                        ["src"],
                        {"commit": squash, "tree": squash_tree},
                        check_checkout=False,
                    ),
                    ["src"],
                )

                (root / "src/value.txt").write_text("drift\n", encoding="utf-8")
                self.git(root, "add", ".")
                self.git(root, "commit", "-qm", "drift")
                drift = self.git(root, "rev-parse", "HEAD")
                drift_tree = self.git(root, "rev-parse", "HEAD^{tree}")
                for row in (legacy, observed_row):
                    with self.assertRaises(module.SourceDrift):
                        module.verify_source_identity(
                            row,
                            ["src"],
                            {"commit": drift, "tree": drift_tree},
                            check_checkout=False,
                        )

                forced_ancestor = dict(legacy)
                forced_ancestor["sourceBaseIdentityMode"] = "ancestor_provenance_v1"
                with self.assertRaises(subprocess.CalledProcessError):
                    module.verify_source_identity(
                        forced_ancestor,
                        ["src"],
                        {"commit": squash, "tree": squash_tree},
                        check_checkout=False,
                    )
            finally:
                module.ROOT = old_root


if __name__ == "__main__":
    unittest.main()
