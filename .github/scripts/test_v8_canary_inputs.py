import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from v8_canary_changes import canary_required
from v8_canary_changes import scoped_canary_files
from v8_canary_changes import windows_source_required
from v8_canary_inputs import bazel_lock_inputs
from v8_canary_inputs import bazel_module_inputs
from v8_canary_inputs import cargo_manifest_inputs
from v8_canary_inputs import v8_dependency_closure


LOCK = b"""\
[[package]]
name = "v8"
version = "150.4.0"
source = "registry+https://example.invalid"
checksum = "v8-checksum"
dependencies = ["build-dependency 1.0.0"]

[[package]]
name = "build-dependency"
version = "1.0.0"
source = "registry+https://example.invalid"
checksum = "build-checksum"

[[package]]
name = "unrelated"
version = "1.0.0"
source = "registry+https://example.invalid"
checksum = "unrelated-checksum"
"""
MANIFEST = b"""\
[workspace]
members = ["v8-poc", "hepta-infer-worker-host"]
resolver = "3"
[workspace.package]
edition = "2024"
rust-version = "1.95"
[workspace.dependencies]
v8 = "=150.4.0"
unrelated = "1"
"""
MODULE = b"""\
bazel_dep(name = "llvm", version = "0.8.11")
crate.annotation(crate = "unrelated", gen_build_script = "off")
crate.annotation(crate = "v8", patches = ["//patches:v8.patch"])
"""
BAZEL_LOCK = {
    "lockFileVersion": 26,
    "facts": {
        "@@rules_rs+//rs:extensions.bzl%crate": {
            "v8_150.4.0": "original-v8-metadata",
            "build-dependency_1.0.0": "original-build-metadata",
            "unrelated_1.0.0": "unrelated-metadata",
        },
        "@@rules_rs+//rs/toolchains:module_extension.bzl%toolchains": {"rust": "pin"},
    },
    "registryFileHashes": {"llvm/MODULE.bazel": "original-toolchain-pin"},
}


class V8InputTest(unittest.TestCase):
    def test_closure_ignores_unrelated_but_keeps_same_version_source_and_edges(self):
        original = v8_dependency_closure(LOCK)
        self.assertEqual(
            original,
            v8_dependency_closure(LOCK.replace(b"unrelated-checksum", b"changed")),
        )
        for before, after in (
            (b"v8-checksum", b"changed-v8-checksum"),
            (b"build-checksum", b"changed-build-checksum"),
            (
                b"registry+https://example.invalid",
                b"git+https://example.invalid#revision",
            ),
            (b'["build-dependency 1.0.0"]', b"[]"),
        ):
            with self.subTest(before=before):
                self.assertNotEqual(
                    original, v8_dependency_closure(LOCK.replace(before, after))
                )

    def test_unresolved_or_ambiguous_dependency_aborts(self):
        for invalid in (
            LOCK.replace(b"build-dependency 1.0.0", b"missing 1.0.0"),
            LOCK.replace(b"build-dependency 1.0.0", b"build-dependency")
            + b'\n[[package]]\nname="build-dependency"\nversion="2.0.0"\n',
        ):
            with self.assertRaises(ValueError):
                v8_dependency_closure(invalid)

    def test_workspace_dependency_scope_preserves_features_and_compiler_inputs(self):
        closure = v8_dependency_closure(LOCK)
        original = cargo_manifest_inputs(MANIFEST, closure)
        self.assertEqual(
            original,
            cargo_manifest_inputs(
                MANIFEST.replace(b'unrelated = "1"', b'unrelated = "2"'), closure
            ),
        )
        for changed in (
            MANIFEST.replace(
                b'v8 = "=150.4.0"',
                b'v8 = { version = "=150.4.0", features = ["v8_enable_sandbox"] }',
            ),
            MANIFEST.replace(b'edition = "2024"', b'edition = "2021"'),
            MANIFEST.replace(b'rust-version = "1.95"', b'rust-version = "1.96"'),
            MANIFEST + b'\n[patch.crates-io]\nv8 = { git="https://example.invalid" }\n',
            MANIFEST + b"\n[profile.release]\nlto = true\n",
            MANIFEST + b'\n[workspace.metadata.future-compiler]\nflags = ["new"]\n',
        ):
            self.assertNotEqual(original, cargo_manifest_inputs(changed, closure))

    def test_module_skips_only_explicit_unrelated_crate_annotations(self):
        closure = v8_dependency_closure(LOCK)
        original = bazel_module_inputs(MODULE, closure)
        self.assertEqual(
            original,
            bazel_module_inputs(
                MODULE.replace(b'gen_build_script = "off"', b'gen_build_script = "on"'),
                closure,
            ),
        )
        for changed in (
            MODULE.replace(b"v8.patch", b"new-v8.patch"),
            MODULE.replace(b"0.8.11", b"0.8.12"),
            MODULE
            + b'crate.annotation(crate = "build-dependency", gen_build_script = "off")\n',
            MODULE
            + b"crate.annotation(crate = computed_name, patches = arbitrary_patches)\n",
            MODULE + b'crate.annotation(crate = "*", patches = arbitrary_patches)\n',
            MODULE + b'register_toolchains("//unknown:toolchain")\n',
        ):
            self.assertNotEqual(original, bazel_module_inputs(changed, closure))

    def test_lock_skips_only_unrelated_crate_facts_keeps_all_toolchain_metadata(self):
        closure = v8_dependency_closure(LOCK)
        original = bazel_lock_inputs(json.dumps(BAZEL_LOCK).encode(), closure)
        changed = copy.deepcopy(BAZEL_LOCK)
        changed["facts"]["@@rules_rs+//rs:extensions.bzl%crate"]["unrelated_1.0.0"] = (
            "changed"
        )
        self.assertEqual(
            original, bazel_lock_inputs(json.dumps(changed).encode(), closure)
        )
        for extension, key in (
            ("@@rules_rs+//rs:extensions.bzl%crate", "build-dependency_1.0.0"),
            ("@@rules_rs+//rs/toolchains:module_extension.bzl%toolchains", "rust"),
        ):
            changed = copy.deepcopy(BAZEL_LOCK)
            changed["facts"][extension][key] = "changed"
            self.assertNotEqual(
                original, bazel_lock_inputs(json.dumps(changed).encode(), closure)
            )
        changed = copy.deepcopy(BAZEL_LOCK)
        changed["registryFileHashes"]["llvm/MODULE.bazel"] = "changed"
        self.assertNotEqual(
            original, bazel_lock_inputs(json.dumps(changed).encode(), closure)
        )
        changed = copy.deepcopy(BAZEL_LOCK)
        changed["facts"]["@@rules_rs+//rs:extensions.bzl%crate"]["future_schema"] = (
            "new"
        )
        self.assertNotEqual(
            original, bazel_lock_inputs(json.dumps(changed).encode(), closure)
        )

    def test_real_git_range_and_late_build_dependency_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", *args], cwd=root, stderr=subprocess.PIPE
                    )
                    .decode()
                    .strip()
                )

            git("init", "--initial-branch=main")
            git("config", "user.name", "V8 Scope Test")
            git("config", "user.email", "scope@example.invalid")
            files = {
                "codex-rs/Cargo.lock": LOCK,
                "codex-rs/Cargo.toml": MANIFEST,
                "MODULE.bazel": MODULE,
                "MODULE.bazel.lock": json.dumps(BAZEL_LOCK).encode(),
            }
            for path, content in files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(content)
            git("add", ".")
            git("commit", "-m", "baseline")
            base = git("rev-parse", "HEAD")
            (root / "codex-rs/Cargo.lock").write_bytes(
                LOCK.replace(b"unrelated-checksum", b"changed")
            )
            (root / "codex-rs/Cargo.toml").write_bytes(
                MANIFEST.replace(b'unrelated = "1"', b'unrelated = "2"')
            )
            (root / "MODULE.bazel").write_bytes(
                MODULE.replace(b'gen_build_script = "off"', b'gen_build_script = "on"')
            )
            changed_lock = copy.deepcopy(BAZEL_LOCK)
            changed_lock["facts"]["@@rules_rs+//rs:extensions.bzl%crate"][
                "unrelated_1.0.0"
            ] = "changed"
            (root / "MODULE.bazel.lock").write_text(json.dumps(changed_lock))
            git("add", ".")
            git("commit", "-m", "unrelated Hepta dependency update")
            scoped, closure_changed = scoped_canary_files(
                set(files), base, "HEAD", root=root
            )
            self.assertFalse(
                canary_required(
                    scoped, "150.4.0", "150.4.0", dependency_changed=closure_changed
                )
            )
            (root / "codex-rs/Cargo.lock").write_bytes(
                LOCK.replace(b"build-checksum", b"changed")
            )
            git("add", ".")
            git("commit", "-m", "same-version V8 build dependency changes")
            scoped, closure_changed = scoped_canary_files(
                set(files), base, "HEAD", root=root
            )
            self.assertTrue(
                canary_required(
                    scoped, "150.4.0", "150.4.0", dependency_changed=closure_changed
                )
            )
            self.assertTrue(
                windows_source_required(
                    scoped, "150.4.0", "150.4.0", dependency_changed=closure_changed
                )
            )
            # With local V8 sources, package metadata alone cannot prove the
            # source closure unchanged. Even an otherwise unrelated range runs.
            (root / "codex-rs/Cargo.lock").write_bytes(
                LOCK.replace(b'source = "registry+https://example.invalid"\n', b"")
            )
            git("add", ".")
            git("commit", "-m", "local V8 closure")
            local_base = git("rev-parse", "HEAD")
            (root / "README.md").write_text("unrelated local change")
            git("add", ".")
            git("commit", "-m", "unknown local source scope")
            _, closure_changed = scoped_canary_files(
                {"README.md"}, local_base, "HEAD", root=root
            )
            self.assertTrue(closure_changed)


if __name__ == "__main__":
    unittest.main()
