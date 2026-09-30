from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("build_supply_chain_manifest.py")
SPEC = importlib.util.spec_from_file_location("build_supply_chain_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

HEAD = "a" * 40
TREE = "b" * 40


def valid_metadata() -> dict:
    return {
        "packages": [{"id": "adapter-id", "name": "codex-hepta-bao-adapter",
                      "version": "1.0.0", "source": None,
                      "manifest_path": str(MODULE.ADAPTER_MANIFEST)}],
        "workspace_members": ["adapter-id"],
        "resolve": {"nodes": [], "root": "adapter-id"},
    }


class SupplyChainManifestTests(unittest.TestCase):
    def test_native_locked_resolution_binds_metadata_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            payload = json.dumps(valid_metadata()).encode()
            path.write_bytes(payload)
            with patch.object(MODULE.subprocess, "check_output", return_value=payload.decode()) as run:
                metadata, digest = MODULE.verify_metadata(path)
            self.assertEqual(metadata, valid_metadata())
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            run.assert_called_once_with(MODULE.METADATA_COMMAND, cwd=MODULE.ROOT, text=True)

    def test_empty_invalid_or_unresolved_metadata_is_rejected(self) -> None:
        invalid = [[], {}, {"packages": []}, {"packages": [{}]}]
        unresolved = valid_metadata()
        unresolved["resolve"] = None
        invalid.append(unresolved)
        wrong_source = valid_metadata()
        wrong_source["packages"][0]["manifest_path"] = "/unrelated/Cargo.toml"
        invalid.append(wrong_source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            for value in invalid:
                with self.subTest(metadata=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with patch.object(MODULE.subprocess, "check_output") as run:
                        with self.assertRaises(ValueError):
                            MODULE.verify_metadata(path)
                        run.assert_not_called()

    def test_old_or_forged_metadata_cannot_replace_native_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            metadata = valid_metadata()
            path.write_text(json.dumps(metadata), encoding="utf-8")
            executed = valid_metadata()
            executed["packages"][0]["version"] = "2.0.0"
            with patch.object(MODULE.subprocess, "check_output", return_value=json.dumps(executed)):
                with self.assertRaisesRegex(ValueError, "differs from the native locked"):
                    MODULE.verify_metadata(path)

    def test_dirty_source_is_rejected(self) -> None:
        with patch.object(MODULE, "git", return_value=" M source.rs"):
            with self.assertRaisesRegex(ValueError, "pristine"):
                MODULE.source_identity()

    def test_source_hash_uses_committed_object_bytes(self) -> None:
        path = MODULE.ROOT / "tracked.txt"
        payload = b"committed bytes, not modified filesystem content"
        with patch.object(MODULE, "git_bytes", return_value=payload) as git:
            digest = MODULE.source_digest(path, HEAD)
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        git.assert_called_once_with("show", f"{HEAD}:tracked.txt")

    def test_file_set_comes_from_exact_tree_including_direct_and_nested_sources(self) -> None:
        paths = ["codex-rs/hepta-bao-adapter/src/lib.rs",
                 "codex-rs/hepta-bao-adapter/src/nested/tests.rs",
                 "codex-rs/hepta-bao-adapter/src/README.md",
                 "codex-rs/hepta-bao-adapter/qa/test_supply.py",
                 "codex-rs/hepta-bao-adapter/qa/nested/test_extra.py"]
        MODULE.committed_paths.cache_clear()
        with patch.object(MODULE, "git_bytes", return_value=("\0".join(paths) + "\0").encode()) as git:
            selected = MODULE.files("codex-rs/hepta-bao-adapter/src/**/*.rs", HEAD)
            self.assertEqual(selected, [MODULE.ROOT / path for path in paths[:2]])
            qa = MODULE.files("codex-rs/hepta-bao-adapter/qa/test_*.py", HEAD)
            self.assertEqual(qa, [MODULE.ROOT / paths[3]])
            git.assert_called_once_with("ls-tree", "-r", "-z", "--name-only", HEAD)
        MODULE.committed_paths.cache_clear()

    def run_builder(self, root: Path, artifacts: list[Path], identities=None) -> int:
        metadata = root / "metadata.json"
        metadata.write_text(json.dumps(valid_metadata()), encoding="utf-8")
        args = ["build_supply_chain_manifest.py", "--output", str(root / "out.json"),
                "--cargo-metadata", str(metadata)]
        for artifact in artifacts:
            args.extend(["--artifact", str(artifact)])
        with patch.object(sys, "argv", args), \
                patch.object(MODULE, "source_identity", side_effect=identities or [(HEAD, TREE), (HEAD, TREE)]), \
                patch.object(MODULE, "verify_metadata", return_value=(valid_metadata(), "c" * 64)), \
                patch.object(MODULE, "source_digest", return_value="d" * 64), \
                patch.object(MODULE, "files", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            return MODULE.main()

    def test_missing_duplicate_or_symlink_artifacts_cannot_be_silently_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "artifact.tar"
            first.write_bytes(b"archive")
            second = root / "other" / "artifact.tar"
            second.parent.mkdir()
            second.write_bytes(b"another archive")
            link = root / "symlink.tar"
            link.symlink_to(first)
            for paths in ([root / "missing.tar"], [first, second], [link]):
                with self.subTest(paths=paths):
                    with self.assertRaises(ValueError):
                        self.run_builder(root, paths)
                    self.assertFalse((root / "out.json").exists())

    def test_candidate_change_during_collection_prevents_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "candidate identity changed"):
                self.run_builder(root, [], identities=[(HEAD, TREE), ("e" * 40, TREE)])
            self.assertFalse((root / "out.json").exists())

    def test_exact_source_receipt_never_grants_build_or_release_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "exact-source.tar"
            artifact.write_bytes(b"source archive")
            self.assertEqual(self.run_builder(root, [artifact]), 0)
            receipt = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["sourceHeadSha"], HEAD)
            self.assertEqual(receipt["sourceTreeSha"], TREE)
            self.assertEqual(receipt["artifacts"][0]["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertFalse(receipt["signed"])
            self.assertFalse(receipt["released"])
            self.assertFalse(receipt["productionQualified"])
            self.assertIn("do not prove candidate build provenance", receipt["nonclaims"][1])


if __name__ == "__main__":
    unittest.main()
