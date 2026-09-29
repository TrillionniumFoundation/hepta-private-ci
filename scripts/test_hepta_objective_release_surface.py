#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-objective-release-surface.py")
SPEC = importlib.util.spec_from_file_location("hepta_objective_release_surface", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ReleaseSurfaceError = MODULE.ReleaseSurfaceError
verify_release_surface = MODULE.verify_release_surface

VALID_WORKFLOW = """\
name: Objective read-only fixture

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-24.04
    steps:
      - name: Check out exact source
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
          fetch-depth: 0
      - name: Local deterministic merge identity
        run: |
          tree="$(git merge-tree --write-tree "$BASE" "$HEAD")"
          git commit-tree "$tree" -p "$BASE" -p "$HEAD"
"""


class ReleaseSurfaceTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".github/workflows").mkdir(parents=True)
        return temporary, root

    @staticmethod
    def write(root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_accepts_explicit_read_only_checkout_and_local_commit_tree(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        self.write(root, ".github/workflows/hepta-objective-test.yml", VALID_WORKFLOW)

        result = verify_release_surface(root)

        self.assertEqual(result["schema"], "hepta.objective-release-surface.v1")
        self.assertEqual(
            result["workflowsChecked"],
            [".github/workflows/hepta-objective-test.yml"],
        )
        self.assertTrue(result["retiredAuthoringPathsAbsent"])
        self.assertFalse(result["checkoutCredentialsRetained"])

    def test_rejects_repository_write_permission(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace("contents: read", "contents: write")
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)

        with self.assertRaisesRegex(
            ReleaseSurfaceError, "repository write permission is forbidden"
        ):
            verify_release_surface(root)

    def test_rejects_missing_checkout_credential_hardening(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace("          persist-credentials: false\n", "")
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)

        with self.assertRaisesRegex(
            ReleaseSurfaceError,
            "actions/checkout must set persist-credentials: false",
        ):
            verify_release_surface(root)

    def test_rejects_retained_checkout_credentials(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace(
            "persist-credentials: false", "persist-credentials: true"
        )
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)

        with self.assertRaisesRegex(
            ReleaseSurfaceError, "checkout credentials may not be retained"
        ):
            verify_release_surface(root)

    def test_rejects_repository_authoring_commands(self) -> None:
        for command in (
            "git push origin HEAD",
            "git commit -m forbidden",
            "git add .",
            "git rm old",
        ):
            with self.subTest(command=command):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                workflow = VALID_WORKFLOW.replace(
                    '          git commit-tree "$tree" -p "$BASE" -p "$HEAD"\n',
                    f"          {command}\n",
                )
                self.write(
                    root, ".github/workflows/hepta-objective-test.yml", workflow
                )

                with self.assertRaisesRegex(
                    ReleaseSurfaceError,
                    "repository-authoring command is forbidden",
                ):
                    verify_release_surface(root)

    def test_rejects_retired_authoring_paths(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        self.write(root, ".github/workflows/hepta-objective-test.yml", VALID_WORKFLOW)
        self.write(
            root,
            "scripts/hepta-objective-materialize-closure.py",
            "# retired one-shot source writer\n",
        )

        with self.assertRaisesRegex(
            ReleaseSurfaceError, "retired objective authoring path exists"
        ):
            verify_release_surface(root)

    def test_requires_at_least_one_objective_workflow(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)

        with self.assertRaisesRegex(ReleaseSurfaceError, "no objective workflows found"):
            verify_release_surface(root)


if __name__ == "__main__":
    unittest.main()
