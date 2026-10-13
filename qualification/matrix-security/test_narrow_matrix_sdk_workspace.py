"""Adversarial proof that narrowing is disposable, non-promoting, and fail closed."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from narrow_matrix_sdk_workspace import (
    PINNED_MIGRATION_SHA,
    PINNED_RELEASE_SHA,
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
    result = {
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
        "resolve": {
            "nodes": [
                {"id": "hepta-sdk-id", "features": [],
                 "deps": [{"pkg": "upstream-sdk"}]},
                {"id": "upstream-sdk", "features": ["e2e-encryption", "sqlite"],
                 "deps": [{"pkg": "upstream-crypto"}, {"pkg": "new-anymap"}]},
                {"id": "upstream-crypto", "features": [],
                 "deps": [{"pkg": "new-blake3"}]},
                {"id": "new-anymap", "features": [], "deps": []},
                {"id": "new-blake3", "features": [], "deps": []},
            ],
            "root": None,
        },
    }
    for node in result["resolve"]["nodes"]:
        for edge in node["deps"]:
            edge["dep_kinds"] = [{"kind": None, "target": None}]
    return result


def enc(value):
    return json.dumps(value, sort_keys=True).encode()


class NarrowWorkspaceTests(unittest.TestCase):
    def test_only_workspace_membership_changes(self):
        original = cargo_fixture()
        edited = rewrite_workspace(original)
        # The authoritative Cargo-parser boundary takes exact bytes; a
        # decoded string must never be handed back to the bounded reader.
        self.assertIsInstance(edited, bytes)
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
        self.assertTrue(report["codex_state_execpolicy_absent"])
        self.assertFalse(report["production_authorized"])
        self.assertFalse(report["cargo_deny_verified"])
        self.assertFalse(report["full_matrixd_compilation_verified"])

    def test_graph_rejects_all_known_resolver_and_security_regressions(self):
        mutations = []
        original = metadata()
        for name, version in [
            ("anymap2", "0.13.0"), ("starlark", "0.14.2"),
            ("codex-cli", "0.0.0"), ("codex-hepta-matrixd", "0.0.0"),
            ("codex-state", "0.0.0"), ("codex-execpolicy", "0.0.0"),
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

    def test_real_cargo_resolve_edges_required_not_decoy_package_names(self):
        source = metadata()
        arms = []
        no_resolve = json.loads(json.dumps(source))
        no_resolve.pop("resolve")
        arms.append(no_resolve)

        invalid_resolve = json.loads(json.dumps(source))
        invalid_resolve["resolve"] = {"nodes": None}
        arms.append(invalid_resolve)

        unrelated_crypto = json.loads(json.dumps(source))
        next(node for node in unrelated_crypto["resolve"]["nodes"]
             if node["id"] == "upstream-sdk")["deps"] = [{"pkg": "new-anymap"}]
        arms.append(unrelated_crypto)

        unrelated_anymap = json.loads(json.dumps(source))
        next(node for node in unrelated_anymap["resolve"]["nodes"]
             if node["id"] == "upstream-sdk")["deps"] = [{"pkg": "upstream-crypto"}]
        arms.append(unrelated_anymap)

        unrelated_blake = json.loads(json.dumps(source))
        next(node for node in unrelated_blake["resolve"]["nodes"]
             if node["id"] == "upstream-crypto")["deps"] = []
        arms.append(unrelated_blake)

        no_crypto_feature = json.loads(json.dumps(source))
        next(node for node in no_crypto_feature["resolve"]["nodes"]
             if node["id"] == "upstream-sdk")["features"] = ["sqlite"]
        arms.append(no_crypto_feature)

        no_sqlite_feature = json.loads(json.dumps(source))
        next(node for node in no_sqlite_feature["resolve"]["nodes"]
             if node["id"] == "upstream-sdk")["features"] = ["e2e-encryption"]
        arms.append(no_sqlite_feature)

        missing_node = json.loads(json.dumps(source))
        missing_node["resolve"]["nodes"].pop()
        arms.append(missing_node)

        duplicate_node = json.loads(json.dumps(source))
        duplicate_node["resolve"]["nodes"].append(
            dict(duplicate_node["resolve"]["nodes"][0]))
        arms.append(duplicate_node)

        dangling_edge = json.loads(json.dumps(source))
        dangling_edge["resolve"]["nodes"][0]["deps"].append(
            {"pkg": "phantom-unregistered-crate"})
        arms.append(dangling_edge)

        malformed_edge = json.loads(json.dumps(source))
        malformed_edge["resolve"]["nodes"][0]["deps"] = [{}]
        arms.append(malformed_edge)

        wrong_crypto_source = json.loads(json.dumps(source))
        next(p for p in wrong_crypto_source["packages"]
             if p["name"] == "matrix-sdk-crypto")["manifest_path"] = (
                 "/unapproved/foreign-crypto/Cargo.toml")
        arms.append(wrong_crypto_source)

        sdk_path_substitution = json.loads(json.dumps(source))
        next(p for p in sdk_path_substitution["packages"]
             if p["name"] == "matrix-sdk")["manifest_path"] = (
                 "/tmp/stem-candidate/unreviewed-sdk/Cargo.toml")
        arms.append(sdk_path_substitution)

        duplicate_pkgid = json.loads(json.dumps(source))
        duplicate_pkgid["packages"].append(
            dict(duplicate_pkgid["packages"][-1]))
        arms.append(duplicate_pkgid)

        for case in arms:
            with self.subTest(case=hashlib.sha256(enc(case)).hexdigest()[:12]):
                with self.assertRaises(ValueError):
                    inspect_cargo_metadata(
                        enc(case), candidate_root="/tmp/stem-candidate",
                        stage_root="/tmp/hepta-stage")

    def test_decoy_fix_reachable_only_from_hepta_not_sdk_is_rejected(self):
        # The CLI may accidentally depend on a maintained crate, but that
        # does not repair an unpatched Matrix SDK's own dependency subtree.
        for repaired, owner in (
            ("new-anymap", "upstream-sdk"),
            ("new-blake3", "upstream-crypto"),
        ):
            with self.subTest(repaired=repaired):
                candidate = metadata()
                sdk = next(n for n in candidate["resolve"]["nodes"]
                           if n["id"] == owner)
                sdk["deps"] = [e for e in sdk["deps"]
                               if e["pkg"] != repaired]
                hepta = next(n for n in candidate["resolve"]["nodes"]
                             if n["id"] == "hepta-sdk-id")
                hepta["deps"].append({
                    "pkg": repaired,
                    "dep_kinds": [{"kind": None, "target": None}],
                })
                with self.assertRaisesRegex(
                    ValueError, "required patched Matrix"
                ):
                    inspect_cargo_metadata(
                        enc(candidate), candidate_root="/tmp/stem-candidate",
                        stage_root="/tmp/hepta-stage")

    def test_legacy_matrix_family_version_in_sdk_closure_is_rejected(self):
        candidate = metadata()
        candidate["packages"].append({
            "name": "matrix-sdk-base", "id": "legacy-sdk-base",
            "version": "0.18.0",
            "manifest_path": "/tmp/stem-candidate/crates/matrix-sdk-base/Cargo.toml",
        })
        candidate["resolve"]["nodes"].append(
            {"id": "legacy-sdk-base", "features": [], "deps": []})
        sdk = next(n for n in candidate["resolve"]["nodes"]
                   if n["id"] == "upstream-sdk")
        sdk["deps"].append({
            "pkg": "legacy-sdk-base",
            "dep_kinds": [{"kind": None, "target": None}],
        })
        with self.assertRaisesRegex(
            ValueError, "mixed patched and legacy"
        ):
            inspect_cargo_metadata(
                enc(candidate), candidate_root="/tmp/stem-candidate",
                stage_root="/tmp/hepta-stage")

    def test_dev_only_or_build_only_dependency_cannot_count_as_security_fix(self):
        for affected_pkg, parent in (
            ("new-anymap", "upstream-sdk"),
            ("upstream-crypto", "upstream-sdk"),
            ("new-blake3", "upstream-crypto"),
        ):
            for kind in ("dev", "build"):
                with self.subTest(crate=affected_pkg, dependency_kind=kind):
                    case = metadata()
                    edges = next(n for n in case["resolve"]["nodes"]
                                 if n["id"] == parent)["deps"]
                    next(edge for edge in edges if edge["pkg"] == affected_pkg)[
                        "dep_kinds"] = [{"kind": kind, "target": None}]
                    with self.assertRaisesRegex(
                        ValueError, "required patched Matrix"
                    ):
                        inspect_cargo_metadata(
                            enc(case), candidate_root="/tmp/stem-candidate",
                            stage_root="/tmp/hepta-stage")

    def test_malformed_dependency_kind_data_fails_closed(self):
        for wrong in (None, [], [{}], [{"kind": "magical"}], [42]):
            case = metadata()
            case["resolve"]["nodes"][0]["deps"][0]["dep_kinds"] = wrong
            with self.subTest(value=str(wrong)):
                with self.assertRaises(ValueError):
                    inspect_cargo_metadata(
                        enc(case), candidate_root="/tmp/stem-candidate",
                        stage_root="/tmp/hepta-stage")

    def test_two_blake3_versions_cannot_pass_with_only_one_patched(self):
        case = metadata()
        case["packages"].append({
            "name": "blake3", "id": "legacy-blake3",
            "version": "1.8.2",
            "manifest_path": "/tmp/cargo/legacy-blake3/Cargo.toml",
        })
        case["resolve"]["nodes"].append(
            {"id": "legacy-blake3", "features": [], "deps": []})
        next(node for node in case["resolve"]["nodes"]
             if node["id"] == "upstream-crypto")["deps"].append(
                 {"pkg": "legacy-blake3",
                  "dep_kinds": [{"kind": None, "target": None}]})
        with self.assertRaisesRegex(ValueError, "old blake3"):
            inspect_cargo_metadata(
                enc(case), candidate_root="/tmp/stem-candidate",
                stage_root="/tmp/hepta-stage")

    def test_no_invalid_metadata_or_unbounded_source_passes(self):
        for raw in (
            b"", b"{}", b"invalid", b"{" + b"x" * (32 * 1024 * 1024),
            b'{"packages":[],"packages":[],"workspace_members":[]}',
            b'{"packages":NaN,"workspace_members":[]}',
        ):
            with self.assertRaises(ValueError):
                inspect_cargo_metadata(
                    raw, candidate_root="/tmp/stem-candidate",
                    stage_root="/tmp/hepta-stage")

    def test_invalid_package_and_workspace_member_types_fail_closed(self):
        source = metadata()
        cases = []
        for members in (None, [], ["hepta-sdk-id", "hepta-sdk-id"], [42]):
            bad = json.loads(json.dumps(source))
            bad["workspace_members"] = members
            cases.append(bad)
        for value in (None, 123, [], {"name": "matrix-sdk"}):
            bad = json.loads(json.dumps(source))
            bad["packages"][0] = value
            cases.append(bad)
        for bad in cases:
            with self.subTest(kind=hashlib.sha256(enc(bad)).hexdigest()[:10]):
                with self.assertRaises(ValueError):
                    inspect_cargo_metadata(
                        enc(bad), candidate_root="/tmp/stem-candidate",
                        stage_root="/tmp/hepta-stage")

    def test_stage_narrows_only_detached_candidate_and_requires_pinned_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root / "stage"
            (stage / "codex-rs").mkdir(parents=True)
            (stage / ".git").write_text("gitdir: /nonexistent/original\n")
            (root / "sdk/crates/matrix-sdk").mkdir(parents=True)
            (root / "sdk/crates/matrix-sdk/Cargo.toml").write_text(
                '[package]\nname = "matrix-sdk"\nversion = "0.19.1"\n')
            cargo = stage / "codex-rs/Cargo.toml"
            source = cargo_fixture()
            cargo.write_bytes(source)
            sha = "a" * 40
            report = {
                "schema": SOURCE_SCHEMA,
                "hepta_source_sha": sha,
                "hepta_candidate_manifest_sha256": digest(source),
                "signed_upstream_release_sha": PINNED_RELEASE_SHA,
                "upstream_anymap_change_sha": PINNED_MIGRATION_SHA,
                "minimal_upstream_patch_sha256": "f" * 64,
                "sdk_source_root": str(root / "sdk"),
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
            (root / "sdk/crates/matrix-sdk").mkdir(parents=True)
            (root / "sdk/crates/matrix-sdk/Cargo.toml").write_text(
                '[package]\nname = "matrix-sdk"\nversion = "0.19.1"\n')
            cargo = stage / "codex-rs/Cargo.toml"
            source = cargo_fixture()
            cargo.write_bytes(source)
            sha = "b" * 40
            report = {
                "schema": SOURCE_SCHEMA,
                "hepta_source_sha": sha,
                "hepta_candidate_manifest_sha256": "c" * 64,
                "signed_upstream_release_sha": PINNED_RELEASE_SHA,
                "upstream_anymap_change_sha": PINNED_MIGRATION_SHA,
                "minimal_upstream_patch_sha256": "f" * 64,
                "sdk_source_root": str(root / "sdk"),
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
                with self.assertRaisesRegex(ValueError, "mutated source candidate"):
                    stage_narrow_sdk(stage, report, sha)
            self.assertEqual(cargo.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
