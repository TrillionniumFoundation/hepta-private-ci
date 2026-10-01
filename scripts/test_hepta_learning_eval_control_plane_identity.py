#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_eval_control_plane_identity",
    Path(__file__).with_name("hepta-learning-eval-control-plane-identity.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ControlPlaneIdentityTests(unittest.TestCase):
    def fixture(
        self, root: Path
    ) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, bytes]]:
        workflows = (
            ".github/workflows/hepta-learning-eval-first.yml",
            ".github/workflows/hepta-learning-eval-second.yml",
        )
        auxiliary = (
            "scripts/first.py",
            "scripts/model.json",
        )
        values = {
            workflows[0]: b"name: first\n",
            workflows[1]: b"name: second\n",
            auxiliary[0]: b"print('first')\n",
            auxiliary[1]: b'{"value":1}\n',
        }
        for path, content in values.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return workflows, auxiliary, values

    def test_exact_candidate_bytes_and_workflow_inventory_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows, auxiliary, values = self.fixture(root)

            def fetcher(repository: str, path: str, sha: str, token: str) -> bytes:
                self.assertEqual(repository, "owner/repository")
                self.assertEqual(sha, "a" * 40)
                self.assertEqual(token, "token")
                return values[path]

            result = MODULE.verify_control_plane(
                "owner/repository",
                "a" * 40,
                "token",
                root=root,
                paths=auxiliary,
                fetcher=fetcher,
                workflow_fetcher=lambda *_: workflows,
            )
            self.assertEqual(
                result["schema"],
                "hepta.learning-eval.control-plane-identity.v2",
            )
            self.assertEqual(result["workflowInventory"], list(workflows))
            self.assertEqual(set(result["files"]), set(values))
            self.assertEqual(result["authority"], "DENY_ALL")
            self.assertEqual(result["releasePosture"], "NO_GO")
            self.assertFalse(result["claims"]["sourceQualifiedByThisRun"])

    def test_candidate_byte_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows, auxiliary, values = self.fixture(root)

            def fetcher(_repository: str, path: str, _sha: str, _token: str) -> bytes:
                return values[path] + (b"drift" if path == auxiliary[0] else b"")

            with self.assertRaisesRegex(ValueError, "differs from trusted"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "b" * 40,
                    "token",
                    root=root,
                    paths=auxiliary,
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: workflows,
                )

    def test_candidate_workflow_addition_or_removal_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows, auxiliary, values = self.fixture(root)
            fetcher = lambda _repository, path, _sha, _token: values[path]
            with self.assertRaisesRegex(ValueError, "workflow inventory differs"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "c" * 40,
                    "token",
                    root=root,
                    paths=auxiliary,
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: workflows[:-1],
                )
            with self.assertRaisesRegex(ValueError, "workflow inventory differs"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "c" * 40,
                    "token",
                    root=root,
                    paths=auxiliary,
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: workflows
                    + (".github/workflows/hepta-learning-eval-extra.yml",),
                )

    def test_local_symlink_component_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            (real / "value.py").write_text("pass\n", encoding="utf-8")
            linked = root / "scripts"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink fixture is unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "contains symlink"):
                MODULE.trusted_file_bytes("scripts/value.py", root=root)

    def test_identity_and_path_inventory_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows, auxiliary, values = self.fixture(root)
            fetcher = lambda _repository, path, _sha, _token: values[path]
            with self.assertRaisesRegex(ValueError, "owner/name"):
                MODULE.verify_control_plane(
                    "not-a-repository",
                    "d" * 40,
                    "token",
                    root=root,
                    paths=auxiliary,
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: workflows,
                )
            with self.assertRaisesRegex(ValueError, "empty or duplicated"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "d" * 40,
                    "token",
                    root=root,
                    paths=(auxiliary[0], auxiliary[0]),
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: workflows,
                )

    def test_main_redacts_exception_payload_and_token(self):
        secret = "github-token-must-not-reach-logs"
        stream = io.StringIO()
        with (
            mock.patch.object(
                MODULE,
                "verify_control_plane",
                side_effect=ValueError(f"request failed with {secret}"),
            ),
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": secret}, clear=False),
            redirect_stderr(stream),
        ):
            status = MODULE.main(
                [
                    "--repository",
                    "owner/repository",
                    "--source-sha",
                    "e" * 40,
                ]
            )
        diagnostic = stream.getvalue()
        self.assertEqual(status, 1)
        self.assertNotIn(secret, diagnostic)
        self.assertNotIn("request failed", diagnostic)
        self.assertEqual(
            diagnostic.strip(),
            "ValueError: control-plane verification failed",
        )

    def test_repository_workflow_inventory_is_closed_world(self):
        self.assertEqual(
            MODULE.trusted_learning_eval_workflow_paths(MODULE.ROOT),
            (
                ".github/workflows/hepta-learning-eval-api-diagnostics.yml",
                ".github/workflows/hepta-learning-eval-control-plane-bootstrap.yml",
                ".github/workflows/hepta-learning-eval-convergence.yml",
                ".github/workflows/hepta-learning-eval-exact.yml",
                ".github/workflows/hepta-learning-eval-soak.yml",
                ".github/workflows/hepta-learning-eval-trusted-report.yml",
            ),
        )

    def test_default_auxiliary_inventory_covers_execution_dependencies(self):
        self.assertEqual(
            set(MODULE.AUXILIARY_CONTROL_PLANE_PATHS),
            {
                "scripts/hepta-learning-eval-control-plane-identity.py",
                "scripts/hepta-learning-eval-markdown-links.py",
                "scripts/hepta_learning_eval_projection.py",
                "scripts/hepta_rust_identifiers.py",
                "scripts/learning_eval_status_model.json",
                "scripts/test_hepta_learning_eval_control_plane_identity.py",
                "scripts/test_hepta_learning_eval_projection.py",
            },
        )


if __name__ == "__main__":
    unittest.main()
