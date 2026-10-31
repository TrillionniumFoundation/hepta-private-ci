"""Immutable activation and source-byte refusal fixtures; no provider study read."""

import base64
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import portable_common as c, resolve_binding as resolver


def args(root, **values):
    result = dict(
        activation=str(root / "ACTIVATE.json"),
        binding_commit="",
        binding_path="",
        binding_sha256="",
        output=str(root / "output"),
        event_name="workflow_dispatch",
        before_commit="",
    )
    result.update(values)
    return SimpleNamespace(**result)


class BindingTests(unittest.TestCase):
    def test_no_activation_and_unrelated_push_never_contact_provider(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with patch.object(resolver.provider, "api_json") as api:
                self.assertEqual(resolver.resolve(args(root)), {"active": "false"})
                selected = args(
                    root,
                    binding_commit="a" * 40,
                    binding_path="supplements/parameter_field_deployment_activity_20261031/bindings/RUN.json",
                    binding_sha256="b" * 64,
                    event_name="push",
                    before_commit="c" * 40,
                )
                with patch.object(c, "git", return_value=b""):
                    self.assertEqual(resolver.resolve(selected), {"active": "false"})
                api.assert_not_called()
                self.assertFalse((root / "output").exists())

    def test_partial_dispatch_or_unregistered_path_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for value in (
                args(root, binding_commit="a" * 40),
                args(
                    root,
                    binding_commit="a" * 40,
                    binding_path="../credentials.json",
                    binding_sha256="b" * 64,
                ),
            ):
                with self.assertRaises(ValueError):
                    resolver.activation(value)

    def test_wrong_binding_hash_never_enters_source_or_scientific_admission(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            selected = args(
                root,
                binding_commit="a" * 40,
                binding_path="supplements/parameter_field_deployment_activity_20261031/bindings/RUN.json",
                binding_sha256="b" * 64,
            )
            raw = b'{"synthetic_fixture":true}\n'
            response = {
                "type": "file",
                "encoding": "base64",
                "path": selected.binding_path,
                "content": base64.b64encode(raw).decode(),
                "size": len(raw),
            }
            with (
                patch.dict(
                    resolver.os.environ, {"GITHUB_TOKEN": "synthetic-placeholder"}
                ),
                patch.object(resolver.provider, "api_json", return_value=response),
                patch.object(c, "load_binding") as admission,
            ):
                with self.assertRaisesRegex(
                    ValueError, "Activated binding bytes differ"
                ):
                    resolver.resolve(selected)
                admission.assert_not_called()

    def test_duplicate_activation_keys_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "ACTIVATE.json").write_text('{"schema":"one","schema":"two"}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                resolver.activation(args(root))

    def test_registered_blob_current_bytes_and_clean_checkout_are_all_required(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            subprocess.run(
                ["git", "init", "-q", str(root)], check=True, capture_output=True
            )
            (root / "source.py").write_text("value = 1\n")
            (root / ".gitignore").write_text("*.cache\n")
            subprocess.run(
                ["git", "-C", str(root), "add", "."], check=True, capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "synthetic source fixture",
                ],
                check=True,
                capture_output=True,
            )
            commit = c.git(root, "rev-parse", "HEAD").decode().strip()
            raw = (root / "source.py").read_bytes()
            pins = {
                "source.py": {
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            }
            self.assertEqual(
                c.source_identity(root, commit, pins, exact_head=True)[
                    "registered_commit"
                ],
                commit,
            )
            (root / "hidden.cache").write_text("unregistered")
            with self.assertRaisesRegex(ValueError, "not pristine"):
                c.source_identity(root, commit, pins, exact_head=True)
            (root / "hidden.cache").unlink()
            (root / "source.py").write_text("value = 2\n")
            with self.assertRaises(ValueError):
                c.source_identity(root, commit, pins, exact_head=True)


if __name__ == "__main__":
    unittest.main()
