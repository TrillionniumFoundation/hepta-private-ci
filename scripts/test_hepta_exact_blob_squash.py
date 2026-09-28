"""Regression for squash-safe exact-manifest source identity."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
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


if __name__ == "__main__":
    unittest.main()
