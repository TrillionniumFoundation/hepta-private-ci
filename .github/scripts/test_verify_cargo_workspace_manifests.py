import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_cargo_workspace_manifests as policy


class CargoWorkspaceManifestPolicyTest(unittest.TestCase):
    def manifest(self, crate):
        path = policy.CARGO_RS_ROOT / crate / "Cargo.toml"
        return path, policy.load_manifest(path)

    def errors(self, path, manifest):
        with patch.object(policy, "load_manifest", return_value=manifest):
            return policy.manifest_errors(path)

    def test_product_and_client_profiles_keep_metadata_contracts(self):
        for crate in (
            "hepta-agentd",
            "hepta-supervisor",
            "hepta-automation",
            "hepta-matrixd",
        ):
            with self.subTest(crate=crate):
                path, manifest = self.manifest(crate)
                self.assertEqual(self.errors(path, manifest), [])

    def test_new_feature_needs_no_parallel_identity_registration(self):
        path, manifest = self.manifest("hepta-contracts")
        path = policy.CARGO_RS_ROOT / "hepta-new-reader" / "Cargo.toml"
        manifest["package"]["name"] = "codex-hepta-new-reader"
        manifest["features"] = {"default": ["reader"], "reader": []}
        self.assertEqual(self.errors(path, manifest), [])

    def test_metadata_and_naming_checks_still_reject_invalid_members(self):
        for kind in ("version", "edition", "license", "lints", "name"):
            path, manifest = self.manifest("hepta-contracts")
            if kind == "lints":
                manifest.pop("lints")
            elif kind == "name":
                manifest["package"]["name"] = "wrong-owner"
            else:
                manifest["package"][kind] = "not-inherited"
            with self.subTest(kind=kind):
                self.assertTrue(self.errors(path, manifest))

    def test_isolated_cargo_fuzz_workspace_is_narrowly_recognized(self) -> None:
        path = policy.CARGO_RS_ROOT / "hepta-wire" / "fuzz" / "Cargo.toml"
        manifest = {
            "package": {"metadata": {"cargo-fuzz": True}},
            "workspace": {},
        }
        self.assertTrue(policy.is_isolated_cargo_fuzz_workspace(path, manifest))

        near_misses = (
            policy.CARGO_RS_ROOT / "hepta-wire" / "not-fuzz" / "Cargo.toml",
            policy.CARGO_RS_ROOT / "fuzz" / "Cargo.toml",
        )
        for wrong_path in near_misses:
            with self.subTest(path=wrong_path):
                self.assertFalse(
                    policy.is_isolated_cargo_fuzz_workspace(wrong_path, manifest)
                )

        for changed in (
            {"package": {"metadata": {"cargo-fuzz": False}}, "workspace": {}},
            {"package": {"metadata": {"cargo-fuzz": True}}},
            {"workspace": {}},
        ):
            with self.subTest(manifest=changed):
                self.assertFalse(policy.is_isolated_cargo_fuzz_workspace(path, changed))

    def test_isolated_fuzz_exception_does_not_hide_ordinary_manifest_errors(
        self,
    ) -> None:
        path, manifest = self.manifest("hepta-wire")
        manifest.pop("lints", None)
        self.assertFalse(policy.is_isolated_cargo_fuzz_workspace(path, manifest))
        self.assertTrue(
            any(
                "add `[lints]` with `workspace = true`" in error
                for error in self.errors(path, manifest)
            )
        )


class CargoFeatureSemanticsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-manifest-policy-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.workspace = self.root / "codex-rs"
        self.workspace.mkdir()
        self.header = (
            '[workspace]\nmembers=["reader","helper"]\nresolver="2"\n'
            '[workspace.package]\nversion="0.1.0"\nedition="2024"\nlicense="MIT"\n'
            '[workspace.lints.rust]\nunsafe_code="forbid"\n'
        )
        (self.workspace / "Cargo.toml").write_text(self.header)
        self.package("helper", "[features]\nformat=[]\n")
        self.package("reader", "")
        subprocess.run(
            [
                "cargo",
                "generate-lockfile",
                "--offline",
                "--manifest-path",
                str(self.workspace / "Cargo.toml"),
            ],
            check=True,
            capture_output=True,
        )

    def package(self, name, extra):
        root = self.workspace / name
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "src/lib.rs").write_text("")
        manifest = root / "Cargo.toml"
        manifest.write_text(
            f'[package]\nname="codex-{name}"\nversion.workspace=true\nedition.workspace=true\nlicense.workspace=true\n[lints]\nworkspace=true\n'
            + extra
        )
        return manifest

    def test_cargo_accepts_local_optional_and_forwarded_profiles_without_writes(self):
        extra = (
            '[dependencies]\nhelper={package="codex-helper",path="../helper",optional=true,default-features=false}\n'
            '[features]\ndefault=["reader"]\nreader=["dep:helper"]\nformatted=["reader","helper?/format"]\n'
        )
        self.package("reader", extra)
        before = {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(policy.cargo_manifest_errors(self.workspace), [])
        after = {
            p.relative_to(self.root): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_cargo_rejects_unknown_features_and_invalid_optional_dependency(self):
        for extra in (
            '[features]\nreader=["missing"]\n',
            '[features]\nreader=["dep:missing"]\n',
            '[dev-dependencies]\nhelper={package="codex-helper",path="../helper",optional=true}\n',
        ):
            self.package("reader", extra)
            with self.subTest(extra=extra):
                self.assertTrue(policy.cargo_manifest_errors(self.workspace))

    def test_workspace_optional_defaults_are_not_silently_accepted(self):
        (self.workspace / "Cargo.toml").write_text(
            self.header
            + '[workspace.dependencies]\nhelper={package="codex-helper",path="helper",optional=true}\n'
        )
        self.assertTrue(policy.cargo_manifest_errors(self.workspace))

    def test_manifest_validation_does_not_execute_build_scripts(self):
        (self.workspace / "reader/build.rs").write_text(
            'fn main() { panic!("must not execute"); }'
        )
        self.assertEqual(policy.cargo_manifest_errors(self.workspace), [])
        self.assertFalse((self.workspace / "target").exists())

    def test_cargo_failure_is_not_reported_as_success(self):
        with patch.object(
            policy.subprocess, "run", side_effect=OSError("missing cargo")
        ):
            self.assertTrue(policy.cargo_manifest_errors(self.workspace))

    def test_git_inventory_ignores_build_junk_but_sees_new_source(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("codex-rs/target/\n")
        self.package("target/junk", "not valid TOML")
        with patch.object(policy, "ROOT", self.root):
            manifests = policy.cargo_manifests()
        self.assertEqual(
            manifests,
            [
                self.workspace / "helper/Cargo.toml",
                self.workspace / "reader/Cargo.toml",
            ],
        )


if __name__ == "__main__":
    unittest.main()
