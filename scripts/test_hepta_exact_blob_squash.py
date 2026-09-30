"""Regression for squash-safe exact-manifest source identity."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "implementation_maps", SCRIPTS / "hepta-implementation-maps.py"
)
assert SPEC and SPEC.loader
maps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maps)


class ExactManifestSquashTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(maps, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.write("src/alpha/lib.py", "VALUE = 1\n")
        self.write("docs/modules/alpha/TECHNICAL.md", "guide\n")
        self.anchor = self.commit("source")

    def git(self, *args: str) -> str:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def write(self, rel: str, value: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def commit(self, message: str) -> dict[str, str]:
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return {
            "commit": self.git("rev-parse", "HEAD"),
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }

    def row(self) -> dict:
        paths = [
            "docs/modules/alpha/TECHNICAL.md",
            "src/alpha",
            "src/alpha/lib.py",
        ]
        return {
            "sourceBase": self.anchor,
            "module": "alpha",
            "technicalGuide": "docs/modules/alpha/TECHNICAL.md",
            "declaredRoots": ["src/alpha"],
            "resolvedRoots": ["src/alpha"],
            "sourceRootPresent": True,
            "operations": [
                {
                    "operation": "value",
                    "sourcePath": "src/alpha/lib.py",
                    "sourceBlob": self.git(
                        "rev-parse", "HEAD:src/alpha/lib.py"
                    ),
                    "tests": [],
                    "delegatedCallees": [],
                }
            ],
            "mappingSourceIdentityMode": "exact_blob",
            "sourceIdentityPolicy": "candidate_or_exact_manifest_v2",
            "observedAtHead": {"commit": "f" * 40, "tree": "e" * 40},
            "observedSourcePaths": ["src/alpha"],
            "sourceObjects": [
                {
                    "path": path,
                    "object": self.git("rev-parse", f"HEAD:{path}"),
                }
                for path in paths
            ],
        }

    def test_unreachable_observation_is_metadata_not_currentness_authority(self):
        row = self.row()
        candidate = maps.current_source_base()
        paths = maps.verify_source_identity(row, ["src/alpha"], candidate)
        self.assertIn("src/alpha", paths)

    def test_exact_object_drift_still_rejects(self):
        row = self.row()
        self.write("src/alpha/lib.py", "VALUE = 2\n")
        self.commit("squash-like new tree")
        with self.assertRaisesRegex(ValueError, "exact source object drift"):
            maps.verify_source_identity(
                row, ["src/alpha"], maps.current_source_base()
            )

    def test_known_nonancestral_observation_survives_equal_tree_integration(self):
        self.git("checkout", "-qb", "reviewed")
        self.write("src/alpha/lib.py", "VALUE = 2\n")
        reviewed = self.commit("reviewed source")
        row = self.row()
        row["observedAtHead"] = reviewed
        self.git("checkout", "-qb", "integrated", self.anchor["commit"])
        self.write("src/alpha/lib.py", "VALUE = 2\n")
        candidate = self.commit("squash integration")
        self.assertEqual(candidate["tree"], reviewed["tree"])
        self.assertNotEqual(candidate["commit"], reviewed["commit"])
        maps.verify_source_identity(row, ["src/alpha"], candidate)
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        with self.assertRaises(subprocess.CalledProcessError):
            maps.verify_source_identity(row, ["src/alpha"], candidate)

    def test_manifest_is_mandatory_and_must_cover_all_evidence(self):
        for missing in (None, "src/alpha", "docs/modules/alpha/TECHNICAL.md"):
            with self.subTest(missing=missing):
                row = self.row()
                if missing is None:
                    del row["sourceObjects"]
                else:
                    row["sourceObjects"] = [
                        entry for entry in row["sourceObjects"]
                        if entry["path"] != missing
                    ]
                with self.assertRaisesRegex(ValueError, "sourceObjects|omit evidence"):
                    maps.verify_source_identity(
                        row, ["src/alpha"], maps.current_source_base()
                    )

    def test_duplicate_manifest_paths_reject(self):
        row = self.row()
        row["sourceObjects"].append(dict(row["sourceObjects"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate exact source object"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())

    def test_operation_blob_cannot_disagree_with_valid_manifest(self):
        row = self.row()
        row["operations"][0]["sourceBlob"] = "a" * 40
        with self.assertRaisesRegex(ValueError, "mapped operation blob drift"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())

    def test_manifest_symlinks_and_own_map_reject(self):
        self.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", "{}\n")
        (self.root / "src/alpha/link.py").symlink_to("lib.py")
        self.commit("unsafe manifest witnesses")
        for path, error in (
            ("src/alpha/link.py", "symlink source path"),
            ("docs/modules/alpha/IMPLEMENTATION_MAP.json", "own implementation map"),
        ):
            with self.subTest(path=path):
                row = self.row()
                row["sourceObjects"].append({
                    "path": path,
                    "object": self.git("rev-parse", f"HEAD:{path}"),
                })
                with self.assertRaisesRegex(ValueError, error):
                    maps.verify_source_identity(
                        row, ["src/alpha"], maps.current_source_base()
                    )

    def test_additional_manifest_witnesses_are_checked_for_checkout_drift(self):
        self.write("host/caller.py", "CALLER = 1\n")
        self.commit("extra source witness")
        row = self.row()
        row["sourceObjects"].append({
            "path": "host/caller.py",
            "object": self.git("rev-parse", "HEAD:host/caller.py"),
        })
        paths = maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())
        self.assertIn("host/caller.py", paths)
        self.write("host/caller.py", "CALLER = 2\n")
        with self.assertRaisesRegex(ValueError, "dirty"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())

    def test_explicit_observed_inputs_need_exact_objects(self):
        self.write("host/caller.py", "CALLER = 1\n")
        self.commit("explicit observed witness")
        row = self.row()
        row["observedSourcePaths"].append("host/caller.py")
        with self.assertRaisesRegex(ValueError, "omit evidence"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())
        row["sourceObjects"] = maps.current_source_objects(row)
        paths = maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())
        self.assertIn("host/caller.py", paths)

    def test_known_observation_tree_mismatch_and_zero_identity_reject(self):
        for observation in (
            {"commit": self.anchor["commit"], "tree": "f" * 40},
            {"commit": "0" * 40, "tree": "e" * 40},
        ):
            with self.subTest(observation=observation):
                row = self.row()
                row["observedAtHead"] = observation
                with self.assertRaisesRegex(ValueError, "source observation"):
                    maps.verify_source_identity(
                        row, ["src/alpha"], maps.current_source_base()
                    )

    def test_exact_manifest_requires_exact_blob_mode_and_observation(self):
        row = self.row()
        row["mappingSourceIdentityMode"] = "path_only"
        with self.assertRaisesRegex(ValueError, "requires exact_blob"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())
        row = self.row()
        del row["observedAtHead"]
        with self.assertRaisesRegex(ValueError, "explicit current source observation"):
            maps.verify_source_identity(row, ["src/alpha"], maps.current_source_base())


if __name__ == "__main__":
    unittest.main()
