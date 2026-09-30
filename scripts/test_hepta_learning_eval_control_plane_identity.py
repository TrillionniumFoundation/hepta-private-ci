#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_eval_control_plane_identity",
    Path(__file__).with_name("hepta-learning-eval-control-plane-identity.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuxiliaryControlPlaneIdentityTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
        values = {
            "scripts/first.py": b"print('first')\n",
            "scripts/model.json": b'{"value":1}\n',
        }
        for path, content in values.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return tuple(values), values

    def test_exact_candidate_bytes_are_bound_to_source_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, values = self.fixture(root)

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
                paths=paths,
                fetcher=fetcher,
            )
            self.assertEqual(
                result["schema"],
                "hepta.learning-eval.auxiliary-control-plane-identity.v1",
            )
            self.assertEqual(set(result["files"]), set(paths))
            self.assertEqual(result["authority"], "DENY_ALL")
            self.assertEqual(result["releasePosture"], "NO_GO")
            self.assertFalse(result["claims"]["sourceQualifiedByThisRun"])

    def test_candidate_byte_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, values = self.fixture(root)

            def fetcher(_repository: str, path: str, _sha: str, _token: str) -> bytes:
                return values[path] + (b"drift" if path == paths[0] else b"")

            with self.assertRaisesRegex(ValueError, "differs from trusted"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "b" * 40,
                    "token",
                    root=root,
                    paths=paths,
                    fetcher=fetcher,
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
            (root / "value").write_text("value", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "owner/name"):
                MODULE.verify_control_plane(
                    "not-a-repository",
                    "c" * 40,
                    "token",
                    root=root,
                    paths=("value",),
                    fetcher=lambda *_: b"value",
                )
            with self.assertRaisesRegex(ValueError, "empty or duplicated"):
                MODULE.verify_control_plane(
                    "owner/repository",
                    "c" * 40,
                    "token",
                    root=root,
                    paths=("value", "value"),
                    fetcher=lambda *_: b"value",
                )

    def test_default_inventory_covers_auxiliary_execution_dependencies(self):
        required = {
            ".github/workflows/hepta-learning-eval-control-plane-bootstrap.yml",
            ".github/workflows/hepta-learning-eval-convergence.yml",
            ".github/workflows/hepta-learning-eval-exact.yml",
            ".github/workflows/hepta-learning-eval-trusted-report.yml",
            "scripts/hepta-learning-eval-control-plane-identity.py",
            "scripts/hepta-learning-eval-markdown-links.py",
            "scripts/hepta_learning_eval_projection.py",
            "scripts/hepta_rust_identifiers.py",
            "scripts/learning_eval_status_model.json",
            "scripts/test_hepta_learning_eval_control_plane_identity.py",
            "scripts/test_hepta_learning_eval_projection.py",
        }
        self.assertEqual(set(MODULE.EXTRA_CONTROL_PLANE_PATHS), required)


if __name__ == "__main__":
    unittest.main()
