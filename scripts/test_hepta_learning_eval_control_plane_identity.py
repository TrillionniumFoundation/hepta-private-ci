#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
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
    def git_tree(self):
        return {
            "sha": "2" * 40,
            "truncated": False,
            "tree": [
                {
                    "path": "scripts/tool.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "3" * 40,
                }
            ],
        }

    def candidate_layout(self, tree, commit=None):
        if commit is None:
            commit = {"sha": "1" * 40, "tree": {"sha": "2" * 40}}
        responses = [json.dumps(value).encode() for value in (commit, tree)]
        with mock.patch.object(MODULE, "read_response", side_effect=responses):
            return MODULE.fetch_candidate_python_import_layout(
                "owner/repository", "1" * 40, "token"
            )

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
            "scripts/just-shell.py",
        )
        values = {
            workflows[0]: b"name: first\n",
            workflows[1]: b"name: second\n",
            auxiliary[0]: b"print('first')\n",
            auxiliary[1]: b'{"value":1}\n',
            auxiliary[2]: b"print('trusted shell')\n",
        }
        for path, content in values.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Inventory test",
                "-c",
                "user.email=inventory@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
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
                import_layout_fetcher=lambda *_: MODULE.trusted_python_import_layout(
                    root
                ),
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

            for changed in (auxiliary[0], "scripts/just-shell.py"):

                def fetcher(
                    _repository: str, path: str, _sha: str, _token: str
                ) -> bytes:
                    return values[path] + (b"drift" if path == changed else b"")

                with (
                    self.subTest(changed=changed),
                    self.assertRaisesRegex(ValueError, "differs from trusted"),
                ):
                    MODULE.verify_control_plane(
                        "owner/repository",
                        "b" * 40,
                        "token",
                        root=root,
                        paths=auxiliary,
                        fetcher=fetcher,
                        workflow_fetcher=lambda *_: workflows,
                        import_layout_fetcher=lambda *_: (
                            MODULE.trusted_python_import_layout(root)
                        ),
                    )

    def test_module_addition_deletion_and_package_replacement_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows, auxiliary, values = self.fixture(root)
            trusted = MODULE.trusted_python_import_layout(root)
            without_first = tuple(
                row for row in trusted if row[0] != "scripts/first.py"
            )
            changed_layouts = [
                without_first,
                without_first + (("scripts/first/__init__.py", "100644"),),
            ]
            for path in (
                "scripts/subprocess.py",
                "scripts/subprocess/__init__.py",
                "scripts/subprocess.pyc",
                "scripts/subprocess.pyo",
                "scripts/subprocess.cpython-313-x86_64-linux-gnu.so",
                "scripts/subprocess.pyd",
                "json.py",
                "json/__init__.py",
                "codex-rs/json/__init__.py",
                "codex-rs/namespace/nested/observer.py",
            ):
                changed_layouts.append(trusted + ((path, "100644"),))
            for layout in changed_layouts:
                parsed_layout = MODULE.python_import_layout(
                    (path, mode, "blob") for path, mode in layout
                )
                with (
                    self.subTest(layout=layout),
                    self.assertRaisesRegex(ValueError, "Python import layout differs"),
                ):
                    MODULE.verify_control_plane(
                        "owner/repository",
                        "a" * 40,
                        "token",
                        root=root,
                        paths=auxiliary,
                        fetcher=lambda _, path, *__: values[path],
                        workflow_fetcher=lambda *_: workflows,
                        import_layout_fetcher=lambda *_: parsed_layout,
                    )

    def test_layout_binds_committed_import_paths_without_freezing_blob_content(self):
        tree = self.git_tree()
        before = self.candidate_layout(tree)
        tree["tree"][0]["sha"] = "4" * 40
        self.assertEqual(self.candidate_layout(tree), before)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            before = MODULE.trusted_python_import_layout(root)
            (root / "scripts/first.py").write_text("changed body\n", encoding="utf-8")
            (root / "scripts/untracked.py").write_text("untracked\n", encoding="utf-8")
            self.assertEqual(MODULE.trusted_python_import_layout(root), before)

    def test_git_tree_completeness_identity_and_entry_shape_are_fail_closed(self):
        tree = self.git_tree()
        invalid = []
        for key, value in (("truncated", True), ("truncated", None), ("sha", "5" * 40)):
            changed = json.loads(json.dumps(tree))
            changed[key] = value
            invalid.append(changed)
        changed = json.loads(json.dumps(tree))
        changed.pop("truncated")
        invalid.append(changed)
        changed = json.loads(json.dumps(tree))
        changed["tree"] *= 2
        invalid.append(changed)
        for field, value in (
            ("path", "../subprocess.py"),
            ("path", "/subprocess.py"),
            ("path", "scripts/./subprocess.py"),
            ("path", "scripts\\subprocess.py"),
            ("sha", "bad"),
            ("mode", "120000"),
            ("type", "tree"),
            ("mode", {}),
        ):
            changed = json.loads(json.dumps(tree))
            changed["tree"][0][field] = value
            invalid.append(changed)
        for changed in invalid:
            with self.subTest(tree=changed), self.assertRaises(ValueError):
                self.candidate_layout(changed)
        for commit in ([], {"sha": "5" * 40, "tree": {"sha": "2" * 40}}):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                self.candidate_layout(tree, commit)

    def test_opaque_import_packages_and_oversize_local_tree_are_rejected(self):
        for path, mode, kind in (
            ("scripts/json", "120000", "blob"),
            ("json", "160000", "commit"),
            ("codex-rs/json", "120000", "blob"),
        ):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "opaque"):
                MODULE.python_import_layout([(path, mode, kind)])
        process = mock.MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.BytesIO(b"x" * (MODULE.MAX_DIRECTORY_RESPONSE_BYTES + 1))
        with mock.patch.object(MODULE.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "size bound"):
                MODULE.trusted_python_import_layout(Path("."))
        process.kill.assert_called_once()

    def test_duplicate_truncation_keys_and_oversize_api_response_are_rejected(self):
        responses = [
            json.dumps({"sha": "1" * 40, "tree": {"sha": "2" * 40}}).encode(),
            (
                '{"sha":"'
                + "2" * 40
                + '","truncated":true,"truncated":false,"tree":[]}'
            ).encode(),
        ]
        with mock.patch.object(MODULE, "read_response", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MODULE.fetch_candidate_python_import_layout(
                    "owner/repository", "1" * 40, "token"
                )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"x" * 33
        with mock.patch.object(MODULE, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "too large"):
                MODULE.read_response(
                    MODULE.github_request("https://api.github.com", "token"), 32
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
                    import_layout_fetcher=lambda *_: (
                        MODULE.trusted_python_import_layout(root)
                    ),
                )
            with self.assertRaisesRegex(ValueError, "workflow inventory differs"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "c" * 40,
                    "token",
                    root=root,
                    paths=auxiliary,
                    fetcher=fetcher,
                    workflow_fetcher=lambda *_: (
                        workflows + (".github/workflows/hepta-learning-eval-extra.yml",)
                    ),
                    import_layout_fetcher=lambda *_: (
                        MODULE.trusted_python_import_layout(root)
                    ),
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
                    import_layout_fetcher=lambda *_: (
                        MODULE.trusted_python_import_layout(root)
                    ),
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
                    import_layout_fetcher=lambda *_: (
                        MODULE.trusted_python_import_layout(root)
                    ),
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
                "scripts/just-shell.py",
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
