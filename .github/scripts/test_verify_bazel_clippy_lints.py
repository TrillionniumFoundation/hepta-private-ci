"""Exercise Cargo-to-Bazel lint levels and platform-specific target discovery."""

import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("verify_bazel_clippy_lints.py")
PREFIX = "build:clippy --@rules_rust//rust/settings:clippy_flag="


class LintSynchronizationTests(unittest.TestCase):
    def run_verifier(self, cargo_lints, bazel_lints):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo = root / "Cargo.toml"
            bazel = root / ".bazelrc"
            cargo.write_text("[workspace.lints.clippy]\n" + cargo_lints)
            bazel.write_text("".join(PREFIX + flag + "\n" for flag in bazel_lints))
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cargo-toml",
                    str(cargo),
                    "--bazelrc",
                    str(bazel),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_prioritized_group_and_string_level_match_actual_bazel_flags(self):
        result = self.run_verifier(
            'correctness = { level = "deny", priority = -1 }\n'
            'unwrap_used = "deny"\nidentity_op = "warn"\n',
            [
                "--deny=clippy::correctness",
                "-Dclippy::unwrap_used",
                "--warn=clippy::identity_op",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_level_mismatch_remains_failure_for_table_lint(self):
        result = self.run_verifier(
            'correctness = { level = "deny", priority = -1 }\n',
            ["--warn=clippy::correctness"],
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Mismatched lint levels", result.stderr)

    def test_invalid_tables_do_not_bypass_synchronization(self):
        for value in [
            "{ priority = -1 }",
            '{ level = "deny", priority = true }',
            '{ level = "deny", priority = "low" }',
            '{ level = "deny", unexpected = 1 }',
            '{ level = "unknown", priority = -1 }',
        ]:
            with self.subTest(value=value):
                result = self.run_verifier(
                    "correctness = " + value + "\n",
                    ["--deny=clippy::correctness"],
                )
                self.assertNotEqual(result.returncode, 0)


REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_LISTER = REPO_ROOT / "scripts/list-bazel-clippy-targets.sh"
UNIX_QUALIFICATION = (
    "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
)
UNIT = "//codex-rs/core:core-unit-tests-bin"
NATIVE = "//codex-rs/core:core-all-test-bin"
OTHER_NATIVE = "//codex-rs/other:unrelated-test-bin"
OTHER_MANUAL = "//codex-rs/other:custom-manual-rust-test"
CROSS = "//codex-rs/core:core-all-test-windows-cross-bin"
OTHER_CROSS = "//codex-rs/other:other-integration-test-windows-cross-bin"
DISCOVERED = [
    UNIT,
    NATIVE,
    OTHER_NATIVE,
    OTHER_MANUAL,
    CROSS,
    OTHER_CROSS,
    UNIX_QUALIFICATION,
]
BASE_PATTERNS = ["//codex-rs/...", "-//codex-rs/v8-poc:all"]
QUERY = 'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))'


class ClippyTargetSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        (self.root / ".github/scripts").mkdir(parents=True)
        self.script = self.root / "scripts/list-bazel-clippy-targets.sh"
        shutil.copyfile(TARGET_LISTER, self.script)
        query = self.root / ".github/scripts/run-bazel-query-ci.sh"
        query.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$@" > "$QUERY_ARGS_FILE"\n'
            'cat "$QUERY_TARGETS_FILE"\n'
            'exit "${QUERY_EXIT_CODE:-0}"\n',
            newline="\n",
        )
        query.chmod(0o755)
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        uname = fake_bin / "uname"
        uname.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$TEST_UNAME"\n', newline="\n"
        )
        uname.chmod(0o755)
        self.targets = self.root / "targets.txt"
        self.targets.write_text("\n".join(DISCOVERED) + "\n", newline="\n")
        self.query_args = self.root / "query-args.txt"
        self.env = dict(os.environ)
        self.env.pop("RUNNER_OS", None)
        self.env.update(
            PATH=str(fake_bin) + os.pathsep + self.env["PATH"],
            QUERY_ARGS_FILE=str(self.query_args),
            QUERY_TARGETS_FILE=str(self.targets),
            QUERY_EXIT_CODE="0",
            TEST_UNAME="Linux",
        )

    def invoke(self, runner_os=None, args=()):
        env = dict(self.env)
        if runner_os is not None:
            env["RUNNER_OS"] = runner_os
        return subprocess.run(
            ["bash", str(self.script), *args],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def assert_targets(self, result, targets):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [*BASE_PATTERNS, *targets])
        self.assertEqual(
            self.query_args.read_text().splitlines(), ["--output=label", "--", QUERY]
        )

    def test_linux_native_retains_unix_qualification_and_all_native_helpers(self):
        self.assert_targets(
            self.invoke("Linux"),
            [UNIT, NATIVE, OTHER_NATIVE, OTHER_MANUAL, UNIX_QUALIFICATION],
        )

    def test_macos_native_retains_unix_qualification_and_all_native_helpers(self):
        self.assert_targets(
            self.invoke("macOS"),
            [UNIT, NATIVE, OTHER_NATIVE, OTHER_MANUAL, UNIX_QUALIFICATION],
        )

    def test_windows_native_omits_only_cross_and_declared_unix_only_helpers(self):
        self.assert_targets(
            self.invoke("Windows"), [UNIT, NATIVE, OTHER_NATIVE, OTHER_MANUAL]
        )

    def test_windows_native_normalizes_crlf_query_records_before_filtering(self):
        self.targets.write_bytes(("\r\n".join(DISCOVERED) + "\r\n").encode())
        self.assert_targets(
            self.invoke("Windows"), [UNIT, NATIVE, OTHER_NATIVE, OTHER_MANUAL]
        )

    def test_windows_cross_keeps_existing_cross_and_unit_coverage(self):
        self.assert_targets(
            self.invoke("Windows", ("--windows-cross-compile",)),
            [UNIT, OTHER_MANUAL, CROSS, OTHER_CROSS],
        )

    def test_unset_runner_os_detects_supported_hosts(self):
        for host, is_windows in [
            ("Linux", False),
            ("Darwin", False),
            ("MINGW64_NT-10.0", True),
            ("MSYS_NT-10.0", True),
            ("CYGWIN_NT-10.0", True),
        ]:
            with self.subTest(host=host):
                self.env["TEST_UNAME"] = host
                expected = [UNIT, NATIVE, OTHER_NATIVE, OTHER_MANUAL]
                if not is_windows:
                    expected.append(UNIX_QUALIFICATION)
                self.assert_targets(self.invoke(), expected)

    def test_cross_mode_rejects_non_windows_runner_before_query(self):
        for platform in ("Linux", "macOS"):
            with self.subTest(platform=platform):
                result = self.invoke(platform, ("--windows-cross-compile",))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("requires a Windows runner", result.stderr)
                self.assertFalse(self.query_args.exists())

    def test_unknown_explicit_platform_fails_before_query(self):
        result = self.invoke("Plan9")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Unsupported RUNNER_OS", result.stderr)
        self.assertFalse(self.query_args.exists())

    def test_unknown_detected_platform_fails_before_query(self):
        self.env["TEST_UNAME"] = "Plan9"
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Unsupported host platform", result.stderr)
        self.assertFalse(self.query_args.exists())

    def test_unknown_mode_fails_before_query(self):
        result = self.invoke("Windows", ("--windows-cross-compile=maybe",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Usage:", result.stderr)
        self.assertFalse(self.query_args.exists())

    def test_query_failure_never_emits_partial_targets(self):
        self.env["QUERY_EXIT_CODE"] = "7"
        result = self.invoke("Windows")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "")

    def test_exact_exclusion_does_not_match_similarly_named_native_helper(self):
        near_match = UNIX_QUALIFICATION + "-other"
        self.targets.write_text(near_match + "\n", newline="\n")
        self.assert_targets(self.invoke("Windows"), [near_match])

    def test_known_exclusion_tracks_actual_unix_only_build_declaration(self):
        tree = ast.parse((REPO_ROOT / "codex-rs/hepta-agentd/BUILD.bazel").read_text())
        compatibility = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(name, ast.Name) and name.id == "_COGNITIVE_E2E_COMPATIBILITY"
                for name in node.targets
            )
        )
        self.assertIsInstance(compatibility, ast.Call)
        self.assertEqual(compatibility.func.id, "select")
        self.assertEqual(
            ast.literal_eval(compatibility.args[0]),
            {
                "@platforms//os:linux": [],
                "@platforms//os:macos": [],
                "//conditions:default": ["@platforms//:incompatible"],
            },
        )
        rules = [
            node.value
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "rust_test"
        ]
        rule = next(
            rule
            for rule in rules
            if any(
                keyword.arg == "name"
                and ast.literal_eval(keyword.value)
                == UNIX_QUALIFICATION.split(":", 1)[1]
                for keyword in rule.keywords
            )
        )
        keywords = {keyword.arg: keyword.value for keyword in rule.keywords}
        self.assertEqual(
            keywords["target_compatible_with"].id, "_COGNITIVE_E2E_COMPATIBILITY"
        )
        self.assertIn("manual", ast.literal_eval(keywords["tags"]))


if __name__ == "__main__":
    unittest.main()
