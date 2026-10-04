import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "verify_rust_toolchain_locks",
    Path(__file__).with_name("verify_rust_toolchain_locks.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EXTENSION = "@@rules_rs+//rs/toolchains:module_extension.bzl%toolchains"


class GeneratedLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.root = directory / "repo"
        self.root.mkdir()
        self.output = directory / "evidence"
        self.output.mkdir()
        self.name = "rustc-1.99.0-x86_64-unknown-linux-gnu.tar.xz"
        self.digest = "a" * 64
        old = {"facts": {EXTENSION: {self.name.replace("1.99.0", "1.96.0"): "b" * 64}}}
        nix = {
            "nodes": {
                "nixpkgs": {"locked": {"rev": "preserved"}},
                "rust-overlay": {
                    "locked": {"rev": "old"},
                    "inputs": {"nixpkgs": ["nixpkgs"]},
                },
            }
        }
        for name, value in (("MODULE.bazel.lock", old), ("flake.lock", nix)):
            encoded = json.dumps(value)
            (self.root / name).write_text(encoded)
            (self.output / (name + ".before")).write_text(encoded)
        (self.root / "source.txt").write_text("original source")
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "input",
        )
        (self.output / "source.txt").write_text(
            self.git("rev-parse", "HEAD", "HEAD^{tree}")
        )
        self.lock = {"facts": {EXTENSION: {self.name: self.digest}}}
        self.nix = copy.deepcopy(nix)
        self.nix["nodes"]["rust-overlay"]["locked"]["rev"] = "new"
        self.write_locks()
        (self.output / "channel-rust-1.99.0.toml").write_text(
            '[pkg.rust]\nversion = "1.99.0 (official)"\n'
            "[pkg.rustc.target.x86_64-unknown-linux-gnu]\navailable = true\n"
            f'xz_url = "https://static.rust-lang.org/dist/{self.name}"\n'
            f'xz_hash = "{self.digest}"\n'
        )

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def write_locks(self):
        (self.root / "MODULE.bazel.lock").write_text(json.dumps(self.lock))
        (self.root / "flake.lock").write_text(json.dumps(self.nix))

    def test_valid_generation_is_bound_without_claiming_compilation(self):
        receipt = MODULE.verify(self.root, self.output)
        self.assertEqual(receipt["sourceCommit"], self.git("rev-parse", "HEAD").strip())
        self.assertEqual(receipt["verifiedArchives"], 1)
        self.assertFalse(receipt["compiledOrTested"])

    def test_rejects_wrong_archive_hash(self):
        self.lock["facts"][EXTENSION][self.name] = "c" * 64
        self.write_locks()
        with self.assertRaisesRegex(ValueError, "differs from official"):
            MODULE.verify(self.root, self.output)

    def test_verifies_compiler_source_artifact_outside_package_table(self):
        name = "rustc-1.99.0-src.tar.xz"
        digest = "c" * 64
        before_path = self.output / "MODULE.bazel.lock.before"
        before = json.loads(before_path.read_text())
        before["facts"][EXTENSION]["rustc-1.96.0-src.tar.xz"] = "d" * 64
        before_path.write_text(json.dumps(before))
        self.lock["facts"][EXTENSION][name] = digest
        self.write_locks()
        manifest = self.output / "channel-rust-1.99.0.toml"
        manifest.write_text(
            manifest.read_text()
            + (
                '\n[[artifacts.source-code.target."*"]]\n'
                f'url = "https://static.rust-lang.org/dist/2026-10-01/{name}"\n'
                f'hash-sha256 = "{digest}"\n'
            )
        )
        self.assertEqual(MODULE.verify(self.root, self.output)["verifiedArchives"], 2)

    def test_rejects_lost_target_coverage(self):
        self.lock["facts"][EXTENSION].clear()
        self.write_locks()
        with self.assertRaisesRegex(ValueError, "coverage changed"):
            MODULE.verify(self.root, self.output)

    def test_verifies_target_independent_rust_src_package(self):
        name = "rust-src-1.99.0.tar.xz"
        digest = "e" * 64
        before_path = self.output / "MODULE.bazel.lock.before"
        before = json.loads(before_path.read_text())
        before["facts"][EXTENSION]["rust-src-1.96.0.tar.xz"] = "f" * 64
        before_path.write_text(json.dumps(before))
        self.lock["facts"][EXTENSION][name] = digest
        self.write_locks()
        manifest = self.output / "channel-rust-1.99.0.toml"
        manifest.write_text(
            manifest.read_text()
            + (
                '\n[pkg.rust-src.target."*"]\navailable = true\n'
                f'xz_url = "https://static.rust-lang.org/dist/2026-10-01/{name}"\n'
                f'xz_hash = "{digest}"\n'
            )
        )
        self.assertEqual(MODULE.verify(self.root, self.output)["verifiedArchives"], 2)

    def test_rejects_unrelated_nix_update(self):
        self.nix["nodes"]["nixpkgs"]["locked"]["rev"] = "changed"
        self.write_locks()
        with self.assertRaisesRegex(ValueError, "beyond rust-overlay"):
            MODULE.verify(self.root, self.output)

    def test_rejects_source_mutation(self):
        (self.root / "source.txt").write_text("modified source")
        with self.assertRaisesRegex(ValueError, "unexpected source mutations"):
            MODULE.verify(self.root, self.output)

    def test_rejects_rebound_source_receipt(self):
        (self.output / "source.txt").write_text("different identity\n")
        with self.assertRaisesRegex(ValueError, "source identity changed"):
            MODULE.verify(self.root, self.output)

    def test_rejects_unofficial_archive_origin(self):
        path = self.output / "channel-rust-1.99.0.toml"
        path.write_text(
            path.read_text().replace("static.rust-lang.org", "example.invalid")
        )
        with self.assertRaisesRegex(ValueError, "distribution origin"):
            MODULE.verify(self.root, self.output)


if __name__ == "__main__":
    unittest.main()
