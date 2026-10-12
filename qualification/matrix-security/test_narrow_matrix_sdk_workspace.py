"""Adversarial proof that narrowing is disposable, non-promoting, and fail closed."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from narrow_matrix_sdk_workspace import (
    SOURCE_SCHEMA,
    digest,
    inspect_cargo_metadata,
    rewrite_workspace,
    stage_narrow_sdk,
)


def cargo_fixture():
    members = ["hepta-matrix-sdk", "hepta-matrixd", "cli", "execpolicy"]
    members += [f"component-{n:03d}" for n in range(102)]
    quoted = "\n".join(f'    "{member}",' for member in members)
    return (f'''[workspace]
members = [
{quoted}
]
resolver = "2"

[workspace.package]
version = "0.0.0"
edition = "2024"

[workspace.dependencies]
matrix-sdk = {{ path = "../../sdk/crates/matrix-sdk", default-features = false, features = ["e2e-encryption", "sqlite"] }}
tokio = "1"
''').encode("utf-8")


def metadata(*, candidate="/tmp/stem-candidate", stage="/tmp/hepta-stage"):
    return {
        "packages": [
            {"name": "codex-hepta-matrix-sdk", "id": "hepta-sdk-id",
             "version": "0.0.0",
             "manifest_path": f"{stage}/codex-rs/hepta-matrix-sdk/Cargo.toml"},
            {"name": "matrix-sdk", "id": "upstream-sdk",
             "version": "0.19.1", "manifest_path": f"{candidate}/crates/matrix-sdk/Cargo.toml"},
            {"name": "matrix-sdk-crypto", "id": "upstream-crypto",
             "version": "0.19.1", "manifest_path": f"{candidate}/crates/matrix-sdk-crypto/Cargo.toml"},
            {"name": "anymap3", "id": "new-anymap", "version": "1.0.0",
             "manifest_path": "/tmp/cargo/anymap3/Cargo.toml"},
            {"name": "blake3", "id": "new-blake3", "version": "1.8.7",
             "manifest_path": "/tmp/cargo/blake3/Cargo.toml"},
        ],
        "workspace_members": ["hepta-sdk-id"],
    }


def enc(value):
    return json.dumps(value, sort_keys=True).encode()


class NarrowWorkspaceTests(unittest.TestCase):
    def test_only_workspace_membership_changes(self):
        original = cargo_fixture()
        edited = rewrite_workspace(original)
        self.assertEqual(edited.count(b'[workspace]'), 1)
        self.assertIn(b'members = ["hepta-matrix-sdk"]', edited)
        self.assertNotIn(b'component-099', edited.split(b'[workspace.package]')[0])
        self.assertIn(b'features = ["e2e-encryption", "sqlite"]', edited)
        self.assertEqual(rewrite_workspace(original), edited)
        self.assertEqual(original, cargo_fixture())

    def test_missing_expected_full_graph_rejected(self):
        for mutated in [
            cargo_fixture().replace(b'    "cli",\n', b''),
            cargo_fixture().replace(b'    "execpolicy",\n', b''),
            cargo_fixture().replace(b'resolver = "2"', b'resolver = "1"'),
            cargo_fixture().replace(b'    "component-003",\n', b'    "component-002",\n'),
            cargo_fixture().replace(b'    "hepta-matrix-sdk",\n', b''),
        ]:
            with self.subTest(mutated=hashlib.sha256(mutated).hexdigest()[:8]):
                with self.assertRaises(ValueError):
                    rewrite_workspace(mutated)

    def test_sdk_crypto_and_sqlite_cannot_be_disabled_or_substituted(self):
        orig = cargo_fixture()
        for bad in [
            orig.replace(b'features = ["e2e-encryption", "sqlite"]',
                         b'features = ["sqlite"]'),
            orig.replace(b'default-features = false', b'default-features = true'),
            orig.replace(b'path = "../../sdk/', b'version = "0.18.0", path = "../../sdk/'),
            orig.replace(b'path = "../../sdk/', b'path = "hepta-matrix-sdk/'),
            orig.replace(b'[workspace.dependencies]', b'[workspace]\n[workspace.dependencies]'),
        ]:
            with self.subTest(bad=hashlib.sha256(bad).hexdigest()[:8]):
                with self.assertRaises(ValueError):
                    rewrite_workspace(bad)

    def test_graph_accepts_only_true_narrowed_sdk_source(self):
        report = inspect_cargo_metadata(
            enc(metadata()), candidate_root="/tmp/stem-candidate",
            stage_root="/tmp/hepta-stage")
        self.assertTrue(report["cli_starlark_absent"])
        self.assertFalse(report["production_authorized"])
        self.assertFalse(report["cargo_deny_verified"])
        self.assertFalse(report["full_matrixd_compilation_verified"])

    def test_graph_rejects_all_known_resolver_and_security_regressions(self):
        mutations = []
        original = metadata()
        for name, version in [
            ("anymap2", "0.13.0"), ("starlark", "0.14.2"),
            ("codex-cli", "0.0.0"), ("codex-hepta-matrixd", "0.0.0"),
        ]:
            bad = json.loads(json.dumps(original))
            bad["packages"].append({"name": name, "id": name, "version": version})
            mutations.append(bad)
        for name, bad_version in [
            ("matrix-sdk-crypto", "0.18.0"), ("blake3", "1.8.2"),
            ("matrix-sdk", "0.18.0"),
        ]:
            bad = json.loads(json.dumps(original))
            next(p for p in bad["packages"] if p["name"] == name)["version"] = bad_version
            mutations.append(bad)
        for k, value in [
            ("workspace_members", []),
            ("packages", [p for p in original["packages"] if p["name"] != "anymap3"]),
        ]:
            bad = json.loads(json.dumps(original))
            bad[k] = value
            mutations.append(bad)
        bad = json.loads(json.dumps(original))
        next(p for p in bad["packages"] if p["name"] == "matrix-sdk")[
            "manifest_path"] = "/unapproved/foreign-sdk/Cargo.toml"
        mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=hashlib.sha256(enc(bad)).hexdigest()[:10]):
                with self.assertRaises(ValueError):
                    inspect_cargo_metadata(
                        enc(bad), candidate_root="/tmp/stem-candidate",
                        stage_root="/tmp/hepta-stage")

    def test_no_invalid_metadata_or_unbounded_source_passes(self):
        for raw in (b"", b"{}", b"invalid", b"{" + b"x" * (32 * 1024 * 1024)):
            with self.assertRaises(ValueError):
                inspect_cargo_metadata(
                    raw, candidate_root="/tmp/stem-candidate",
                    stage_root="/tmp/hepta-stage")

    def test_stage_narrows_only_detached_candidate_and_requires_pinned_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root / "stage"
            (stage / "codex-rs").mkdir(parents=True)
            (stage / ".git").write_text("gitdir: /nonexistent/original\n")
            cargo = stage / "codex-rs/Cargo.toml"
            source = cargo_fixture()
            cargo.write_bytes(source)
            sha = "a" * 40
            report = {
                "schema": SOURCE_SCHEMA,
                "hepta_source_sha": sha,
                "hepta_candidate_manifest_sha256": digest(source),
                "production_authorized": False,
                "cargo_resolution_verified": False,
            }
            def fake_git(root_path, *parts):
                if parts == ("rev-parse", "HEAD"):
                    return sha
                if parts == ("diff", "--name-only"):
                    return "codex-rs/Cargo.toml"
                raise AssertionError(parts)
            with patch("narrow_matrix_sdk_workspace._git", side_effect=fake_git):
                output = stage_narrow_sdk(stage, report, sha)
                self.assertNotEqual(output["narrowed_manifest_sha256"], digest(source))
                self.assertTrue(output["hepta_production_workspace_modified"] is False)
                self.assertEqual(cargo.read_bytes(), rewrite_workspace(source))

    def test_stage_fails_on_changed_sha_or_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root / "stage"
            (stage / "codex-rs").mkdir(parents=True)
            (stage / ".git").write_text("gitdir: /nonexistent/original\n")
            cargo = stage / "codex-rs/Cargo.toml"
            source = cargo_fixture()
            cargo.write_bytes(source)
            sha = "b" * 40
            report = {
                "schema": SOURCE_SCHEMA,
                "hepta_source_sha": sha,
                "hepta_candidate_manifest_sha256": "c" * 64,
                "production_authorized": False,
                "cargo_resolution_verified": False,
            }
            with patch("narrow_matrix_sdk_workspace._git", side_effect=lambda *a: sha):
                with self.assertRaises(ValueError):
                    stage_narrow_sdk(stage, report, sha)
            self.assertEqual(cargo.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
