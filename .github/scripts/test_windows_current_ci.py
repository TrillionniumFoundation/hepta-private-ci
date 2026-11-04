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


if __name__ == "__main__":
    unittest.main()
