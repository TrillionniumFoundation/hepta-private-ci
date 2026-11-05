import json
import tempfile
import unittest
from pathlib import Path
from windows_current_ci import (
    SANDBOX_HELPERS,
    assess,
    execute_groups,
    publish_sandbox_helpers,
    valid_source,
)

GROUP = {
    "id": "original",
    "package": "owner",
    "filter": "test(=original)",
    "expectedTestCount": 1,
    "requiredTests": ["original"],
}
PASS = "Starting 1 tests across 1 binary (99 tests skipped)\nPASS [ 0.1s] (1/1) owner original\n"


class StrictWindowsReceiptTests(unittest.TestCase):
    def test_nonzero_exit_is_never_pass(self):
        self.assertFalse(assess(GROUP, 100, PASS)["passed"])

    def test_skipped_or_different_test_is_not_the_original(self):
        for text in (
            "99 tests skipped",
            PASS.replace("owner original", "owner replacement"),
            PASS.replace("Starting 1 tests", "Starting 0 tests"),
        ):
            self.assertFalse(assess(GROUP, 0, text)["passed"])

    def test_actual_windows_ci_terminal_lines_without_progress_counts(self):
        actual = "Starting 1 tests across 1 binary (99 tests skipped)\n        PASS [   3.283s] owner original\nSummary [ 3.283s] 1 tests run: 1 passed, 99 skipped\n"
        self.assertTrue(assess(GROUP, 0, actual)["passed"])
        self.assertEqual(assess(GROUP, 0, actual)["observedTests"], ["original"])
        for replacement in ("SKIP", "FAIL", "TIMEOUT", "EXECFAIL", "LEAK"):
            self.assertFalse(
                assess(GROUP, 0, actual.replace("PASS [", replacement + " ["))["passed"]
            )
        self.assertFalse(
            assess(GROUP, 0, actual.replace("owner original", "other original"))[
                "passed"
            ]
        )
        self.assertFalse(
            assess(
                {**GROUP, "requiredTests": []}, 0, "Starting 1 tests across 1 binary"
            )["passed"]
        )

    def test_actual_single_native_materialization_keeps_exact_selection(self):
        name = (
            "sqlite_recovery::windows::tests::materialize_tests::"
            "retained_windows_materialization_preserves_bound_source_bundle"
        )
        group = {
            **GROUP,
            "id": "retained-windows-materialization",
            "package": "codex-state",
            "requiredTests": [name],
        }
        actual = (
            "Starting 1 test across 1 binary (213 tests skipped)\n"
            f"        PASS [   0.016s] codex-state {name}\n"
            "     Summary [   0.018s] 1 test run: 1 passed, 213 skipped\n"
        )
        result = assess(group, 0, actual)
        self.assertEqual(result["selectedTestCount"], 1)
        self.assertEqual(result["observedTests"], [name])
        self.assertTrue(result["passed"])
        for changed in (
            actual.replace("Starting 1 test", "Starting 0 tests"),
            actual.replace("Starting 1 test", "Starting 2 tests"),
            actual.replace("Starting 1 test across", "missing start record"),
            actual.replace(f"codex-state {name}", "codex-state replacement"),
            actual.replace(f"codex-state {name}", f"other-package {name}"),
            actual.replace("PASS [", "LEAK ["),
            actual.replace("PASS [", "FAIL ["),
        ):
            with self.subTest(log=changed):
                self.assertFalse(assess(group, 0, changed)["passed"])
        self.assertFalse(assess(group, 1, actual)["passed"])

    def test_diagnostics_continue_but_each_failure_is_retained(self):
        seen = []

        def invoke(command):
            seen.append(command)
            return (100 if len(seen) == 1 else 0), PASS

        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            results = execute_groups(
                output, output, [GROUP, {**GROUP, "id": "second"}], invoke
            )
        self.assertEqual([result["passed"] for result in results], [False, True])
        self.assertEqual(len(seen), 2)
        for command in seen:
            self.assertEqual(command[-2:], ["--retries", "0"])
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--no-tests") + 1], "fail")

    def test_changed_source_or_wrong_head_never_qualifies(self):
        before = {
            "head": "a" * 40,
            "tree": "b" * 40,
            "trackedChanges": "",
            "cargoLockSha256": "c" * 64,
        }
        self.assertTrue(valid_source("a" * 40, before, before))
        self.assertFalse(valid_source("d" * 40, before, before))
        self.assertFalse(
            valid_source("a" * 40, before, {**before, "cargoLockSha256": "d" * 64})
        )
        self.assertFalse(
            valid_source(
                "a" * 40,
                {**before, "trackedChanges": " M source.rs"},
                {**before, "trackedChanges": " M source.rs"},
            )
        )


class SandboxHelperArtifactTests(unittest.TestCase):
    def fixture(self, root):
        manifest = root / "codex-rs/windows-sandbox-rs/Cargo.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("[package]\nname = 'codex-windows-sandbox'\n")
        target = root / "target"
        profile = target / "dev-small"
        profile.mkdir(parents=True)
        records = []
        for name in SANDBOX_HELPERS:
            binary = profile / (name + ".exe")
            binary.write_bytes(b"MZ-unit-test-artifact-" + name.encode())
            records.append(
                {
                    "reason": "compiler-artifact",
                    "manifest_path": str(manifest),
                    "target": {"name": name, "kind": ["bin"]},
                    "profile": {"test": False},
                    "executable": str(binary),
                }
            )
        return target, records

    def test_both_real_artifact_paths_and_identical_bytes_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            result = publish_sandbox_helpers(
                root, target, "\n".join(json.dumps(item) for item in records)
            )
            self.assertEqual([item["name"] for item in result], list(SANDBOX_HELPERS))
            for item in result:
                self.assertEqual(
                    Path(item["source"]).read_bytes(),
                    Path(item["testSibling"]).read_bytes(),
                )

    def test_missing_or_wrong_manifest_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "both original"):
                publish_sandbox_helpers(root, target, json.dumps(records[0]))
            records[0]["manifest_path"] = str(root / "other/Cargo.toml")
            with self.assertRaisesRegex(ValueError, "different manifest"):
                publish_sandbox_helpers(
                    root, target, "\n".join(json.dumps(item) for item in records)
                )

    def test_existing_different_helper_is_never_overwritten_or_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            sibling = target / "dev-small/deps" / (SANDBOX_HELPERS[0] + ".exe")
            sibling.parent.mkdir()
            sibling.write_bytes(b"unrelated existing executable")
            with self.assertRaisesRegex(ValueError, "changed"):
                publish_sandbox_helpers(
                    root, target, "\n".join(json.dumps(item) for item in records)
                )
            self.assertEqual(sibling.read_bytes(), b"unrelated existing executable")


class ClosedTestTargetTests(unittest.TestCase):
    def test_default_group_keeps_complete_original_lib_command(self):
        seen = []

        def invoke(command):
            seen.append(command)
            return 0, PASS

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = execute_groups(root, root, [GROUP], invoke)
        self.assertEqual(
            seen,
            [
                [
                    "just",
                    "test",
                    "--locked",
                    "-p",
                    "owner",
                    "--lib",
                    "--cargo-profile",
                    "dev-small",
                    "-E",
                    "test(=original)",
                    "--test-threads",
                    "1",
                    "--no-tests",
                    "fail",
                    "--retries",
                    "0",
                ]
            ],
        )
        self.assertTrue(result[0]["passed"])

    def test_app_all_target_requires_exact_integration_binary_receipt(self):
        name = "suite::v2::thread_termination_observed::observed_termination_jsonrpc_reaches_core_and_original_child"
        group = {
            **GROUP,
            "package": "codex-app-server",
            "testTarget": "all",
            "filter": f"test(={name})",
            "requiredTests": [name],
        }
        log = (
            "Starting 1 test across 1 binary (99 tests skipped)\n"
            f"PASS [ 0.1s] codex-app-server::all {name}\n"
        )
        seen = []

        def invoke(command):
            seen.append(command)
            return 0, log

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = execute_groups(root, root, [group], invoke)
        self.assertEqual(
            seen,
            [
                [
                    "just",
                    "test",
                    "--locked",
                    "-p",
                    "codex-app-server",
                    "--test",
                    "all",
                    "--cargo-profile",
                    "dev-small",
                    "-E",
                    f"test(={name})",
                    "--test-threads",
                    "1",
                    "--no-tests",
                    "fail",
                    "--retries",
                    "0",
                ]
            ],
        )
        self.assertTrue(result[0]["passed"])
        for changed in (
            log.replace("codex-app-server::all", "codex-app-server"),
            log.replace("codex-app-server::all", "codex-app-server::other"),
            log.replace("codex-app-server::all", "other::all"),
            log.replace("Starting 1 test", "Starting 0 tests"),
            log.replace(name, "replacement"),
        ):
            with self.subTest(log=changed):
                self.assertFalse(assess(group, 0, changed)["passed"])
        self.assertFalse(assess(group, 1, log)["passed"])

    def test_invalid_target_refuses_before_any_group_is_invoked(self):
        invalid = [
            {**GROUP, "package": "codex-app-server", "testTarget": target}
            for target in (
                None,
                "",
                "lib",
                "integration",
                "all --retries 2",
                ["all"],
                {"name": "all"},
            )
        ]
        invalid.append({**GROUP, "testTarget": "all"})
        for group in invalid:
            with self.subTest(group=group):
                seen = []

                def invoke(command):
                    seen.append(command)
                    return 0, PASS

                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    with self.assertRaisesRegex(
                        ValueError, "unsupported Windows test target"
                    ):
                        execute_groups(root, root, [GROUP, group], invoke)
                    self.assertEqual(list(root.iterdir()), [])
                self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
