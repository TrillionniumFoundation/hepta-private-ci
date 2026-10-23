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
                self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)

                with self.assertRaisesRegex(
                    ReleaseSurfaceError,
                    "repository-authoring command is forbidden",
                ):
                    verify_release_surface(root)

    def test_rejects_retired_authoring_paths(self) -> None:
        for relative in MODULE.RETIRED_AUTHORING_PATHS:
            with self.subTest(relative=relative):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                self.write(
                    root, ".github/workflows/hepta-objective-test.yml", VALID_WORKFLOW
                )
                self.write(root, str(relative), "# retired one-shot source writer\n")
                with self.assertRaisesRegex(
                    ReleaseSurfaceError, "retired objective authoring path exists"
                ):
                    verify_release_surface(root)

    def test_rejects_quoted_and_flow_job_write_permissions(self) -> None:
        for declaration in (
            "    permissions: {contents: write}\n",
            '    permissions: {"contents": "write"}\n',
            '    permissions:\n      contents: "write"\n',
            "    'permissions': {'contents': 'write'}\n",
        ):
            with self.subTest(declaration=declaration):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                self.write(
                    root,
                    ".github/workflows/hepta-objective-test.yml",
                    VALID_WORKFLOW.replace(
                        "    runs-on:", declaration + "    runs-on:"
                    ),
                )
                with self.assertRaisesRegex(
                    ReleaseSurfaceError, "repository write permission"
                ):
                    verify_release_surface(root)

    def test_rejects_quoted_checkout_and_flow_retained_credentials(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace(
            "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            'uses: "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"',
        ).replace(
            "        with:\n          persist-credentials: false\n          fetch-depth: 0",
            "        with: {persist-credentials: true, fetch-depth: 0}",
        )
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
        with self.assertRaisesRegex(
            ReleaseSurfaceError, "credentials may not be retained"
        ):
            verify_release_surface(root)

    def test_other_candidate_jobs_cannot_obtain_identity_or_write_scopes(self) -> None:
        for scope in ("id-token", "attestations", "actions", "issues", "packages"):
            with self.subTest(scope=scope):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                workflow = VALID_WORKFLOW.replace(
                    "    runs-on:",
                    f"    permissions: {{contents: read, {scope}: write}}\n    runs-on:",
                )
                self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
                with self.assertRaisesRegex(
                    ReleaseSurfaceError, "job write permissions"
                ):
                    verify_release_surface(root)

    def test_case_variants_cannot_hide_checkout_credentials(self) -> None:
        for replacement in (
            "persist-credentials: true",
            "persist-credentials: false\n          PERSIST-CREDENTIALS: true",
        ):
            with self.subTest(replacement=replacement):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                workflow = VALID_WORKFLOW.replace(
                    "actions/checkout@", "Actions/Checkout@"
                ).replace("persist-credentials: false", replacement)
                self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
                with self.assertRaises(ReleaseSurfaceError):
                    verify_release_surface(root)

    def test_accepts_static_quoted_and_flow_hardening(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = (
            VALID_WORKFLOW.replace(
                "permissions:\n  contents: read",
                'permissions: {"contents": "read"}',
            )
            .replace(
                "uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                "uses: 'actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd'",
            )
            .replace(
                "        with:\n          persist-credentials: false\n          fetch-depth: 0",
                '        with: {"persist-credentials": "false", fetch-depth: 0}',
            )
        )
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
        verify_release_surface(root)

    def test_unsupported_security_relevant_yaml_fails_closed(self) -> None:
        for old, new in (
            (
                "permissions:\n  contents: read",
                "permissions: &read_only\n  contents: read",
            ),
            (
                "    runs-on: ubuntu-24.04",
                "    permissions: *read_only\n    runs-on: ubuntu-24.04",
            ),
            ("        with:", "        with:\n          <<: *checkout_inputs"),
            ("jobs:\n", "jobs: {verify: {permissions: {contents: write}}}\n"),
            ("    steps:\n", "    steps: [{uses: actions/checkout@v4}]\n"),
            (
                "persist-credentials: false",
                "persist-credentials: ${{ inputs.keep_credentials }}",
            ),
            (
                "permissions:\n  contents: read",
                "permissions: {contents: read, contents: write}",
            ),
        ):
            with self.subTest(new=new):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                self.write(
                    root,
                    ".github/workflows/hepta-objective-test.yml",
                    VALID_WORKFLOW.replace(old, new),
                )
                with self.assertRaises(ReleaseSurfaceError):
                    verify_release_surface(root)

    def test_checkout_cannot_borrow_another_steps_with(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace(
            "        with:\n          persist-credentials: false\n          fetch-depth: 0\n",
            "",
        ).replace(
            "      - name: Local deterministic merge identity",
            "      - uses: actions/upload-artifact@v4\n        with:\n          persist-credentials: false\n      - name: Local deterministic merge identity",
        )
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
        with self.assertRaisesRegex(ReleaseSurfaceError, "checkout must set"):
            verify_release_surface(root)

    def test_top_level_identity_write_permissions_are_forbidden(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        workflow = VALID_WORKFLOW.replace(
            "  contents: read", "  contents: read\n  id-token: write"
        )
        self.write(root, ".github/workflows/hepta-objective-test.yml", workflow)
        with self.assertRaisesRegex(ReleaseSurfaceError, "workflow-wide write"):
            verify_release_surface(root)

    def test_actual_target_host_candidate_jobs_remain_unprivileged(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        relative = ".github/workflows/hepta-objective-target-host.yml"
        source = SCRIPT.resolve().parents[1] / relative
        self.write(root, relative, source.read_text(encoding="utf-8"))
        verify_release_surface(root)

    def test_attestation_job_cannot_execute_candidate_or_checkout_code(self) -> None:
        relative = ".github/workflows/hepta-objective-target-host.yml"
        original = (SCRIPT.resolve().parents[1] / relative).read_text(encoding="utf-8")
        for extra in (
            "      - run: cargo test\n",
            "      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n        with: {persist-credentials: false}\n",
        ):
            with self.subTest(extra=extra):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                workflow = original.replace(
                    "  target-host:\n", extra + "\n  target-host:\n"
                )
                self.write(root, relative, workflow)
                with self.assertRaisesRegex(ReleaseSurfaceError, "attest-candidate"):
                    verify_release_surface(root)

    def test_target_host_yaml_extension_has_the_same_privilege_boundary(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        original = (
            SCRIPT.resolve().parents[1]
            / ".github/workflows/hepta-objective-target-host.yml"
        ).read_text(encoding="utf-8")
        workflow = original.replace(
            "  target-host:\n", "      - run: cargo test\n\n  target-host:\n"
        )
        self.write(root, ".github/workflows/hepta-objective-target-host.yaml", workflow)
        with self.assertRaisesRegex(ReleaseSurfaceError, "attest-candidate"):
            verify_release_surface(root)

    def test_target_host_candidate_job_cannot_receive_identity_write_permission(
        self,
    ) -> None:
        for candidate_job in ("package-candidate", "target-host"):
            with self.subTest(candidate_job=candidate_job):
                temporary, root = self.make_repo()
                self.addCleanup(temporary.cleanup)
                workflow = VALID_WORKFLOW.replace(
                    "  verify:\n",
                    "  package-candidate:\n    permissions: {contents: read}\n",
                )
                workflow += "  target-host:\n    permissions: {contents: read}\n    runs-on: ubuntu-24.04\n    steps:\n      - run: true\n"
                workflow = workflow.replace(
                    f"  {candidate_job}:\n    permissions: {{contents: read}}",
                    f"  {candidate_job}:\n    permissions: {{contents: read, id-token: write}}",
                )
                self.write(
                    root, ".github/workflows/hepta-objective-target-host.yml", workflow
                )
                with self.assertRaisesRegex(
                    ReleaseSurfaceError, "candidate job .* may not obtain"
                ):
                    verify_release_surface(root)

    def test_requires_at_least_one_objective_workflow(self) -> None:
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)

        with self.assertRaisesRegex(
            ReleaseSurfaceError, "no objective workflows found"
        ):
            verify_release_surface(root)


if __name__ == "__main__":
    unittest.main()
