"""Tests of the qualification recorder, not of the Rust objective implementation."""

from __future__ import annotations

import copy
import fnmatch
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "objective_exact", Path(__file__).with_name("hepta-objective-qualify-exact.py")
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReceiptTests(unittest.TestCase):
    def receipt(self):
        checks = [
            {"name": name, "status": "completed", "exitCode": 0, "logSha256": "a" * 64}
            for name, _ in MODULE.commands()
        ]
        return {
            "sourceClean": True,
            "errors": [],
            "candidates": [
                {"kind": kind, "clean": True, "checks": copy.deepcopy(checks)}
                for kind in ("source-head", "synthetic-merge")
            ],
        }

    def test_complete_declared_scope(self):
        self.assertTrue(MODULE.complete(self.receipt()))

    def test_missing_candidate_missing_check_or_duplicate_cannot_pass(self):
        value = self.receipt()
        value["candidates"].pop()
        self.assertFalse(MODULE.complete(value))
        value = self.receipt()
        value["candidates"][1]["checks"].pop()
        self.assertFalse(MODULE.complete(value))
        value = self.receipt()
        value["candidates"][0]["checks"].append(value["candidates"][0]["checks"][0])
        self.assertFalse(MODULE.complete(value))

    def test_duplicate_candidate_cannot_pass(self):
        value = self.receipt()
        value["candidates"].append(copy.deepcopy(value["candidates"][0]))
        self.assertFalse(MODULE.complete(value))

    def test_failure_timeout_absence_or_bad_digest_cannot_pass(self):
        for changes in (
            {"exitCode": 1},
            {"status": "timed_out"},
            {"status": "unavailable"},
            {"status": "insufficient_tests"},
            {"logSha256": ""},
            {"logSha256": "z" * 64},
        ):
            with self.subTest(changes=changes):
                value = self.receipt()
                value["candidates"][0]["checks"][0].update(changes)
                self.assertFalse(MODULE.complete(value))

    def test_dirty_source_or_merge_error_cannot_pass(self):
        value = self.receipt()
        value["sourceClean"] = False
        self.assertFalse(MODULE.complete(value))
        value = self.receipt()
        value["candidates"][1]["clean"] = False
        self.assertFalse(MODULE.complete(value))
        value = self.receipt()
        value["errors"].append("merge unavailable")
        self.assertFalse(MODULE.complete(value))

    def test_real_nonzero_command_retains_log_and_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = MODULE.run_command(
                root,
                root,
                "failure",
                [
                    sys.executable,
                    "-c",
                    "print('observed failure'); raise SystemExit(7)",
                ],
                5,
            )
            self.assertEqual(result["exitCode"], 7)
            self.assertIn("observed failure", (root / result["log"]).read_text())
            self.assertEqual(result["logSha256"], MODULE.digest(root / result["log"]))

    def test_real_timeout_does_not_become_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = MODULE.run_command(
                root,
                root,
                "timeout",
                [sys.executable, "-c", "import time; time.sleep(10)"],
                1,
            )
            self.assertEqual(result["exitCode"], 124)
            self.assertEqual(result["status"], "timed_out")

    def test_missing_executable_is_explicit_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = MODULE.run_command(
                root, root, "missing", [str(root / "absent-binary")], 1
            )
            self.assertEqual(result["exitCode"], 127)
            self.assertEqual(result["status"], "unavailable")

    def test_signed_product_regressions_cannot_be_omitted_from_receipt(self):
        receipt = self.receipt()
        for candidate in receipt["candidates"]:
            candidate["checks"] = [
                check
                for check in candidate["checks"]
                if check["name"] != "agentd-signed-product"
            ]
        self.assertFalse(MODULE.complete(receipt))

    def test_signed_product_requires_at_least_five_executed_tests(self):
        for passed in (0, 1, 4, 5, 6):
            with self.subTest(passed=passed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = f"test result: ok. {passed} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s"
                result = MODULE.run_command(
                    root,
                    root,
                    "agentd-signed-product",
                    [sys.executable, "-c", f"print({output!r})"],
                    5,
                )
                self.assertEqual(result["exitCode"], 0)
                self.assertEqual(
                    result["status"],
                    "completed" if passed >= 5 else "insufficient_tests",
                )
                self.assertEqual(
                    result["logSha256"], MODULE.digest(root / result["log"])
                )

    def test_signed_product_cannot_pass_with_missing_or_ambiguous_summary(self):
        outputs = (
            "",
            "test result: ok. 5 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.01s",
            "test result: FAILED. 5 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s",
            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n"
            * 2,
        )
        for output in outputs:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result = MODULE.run_command(
                    root,
                    root,
                    "agentd-signed-product",
                    [sys.executable, "-c", f"print({output!r})"],
                    5,
                )
                self.assertEqual(result["exitCode"], 0)
                self.assertEqual(result["status"], "insufficient_tests")


class PushQualificationTests(unittest.TestCase):
    """Exercise enqueue behavior against the real workflow's supported filters."""

    branch = "work/objective-compiler-production-convergence-20260927"
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/hepta-objective-exact-execution.yml"
    )

    def push_enqueues(self, branch, changed_paths):
        # Keep this dependency-free like the recorder tests. Read only the block
        # push filters used here; unknown YAML/filter syntax must fail the test,
        # rather than quietly treating a newly narrowed workflow as unfiltered.
        text = self.workflow.read_text()
        events = re.findall(r"(?m)^on:\n((?:[ \t].*\n|\n)+)", text)
        self.assertEqual(len(events), 1, "one block event mapping is required")
        pushes = re.findall(r"(?m)^  push:\n((?:    .*\n|\n)+)", events[0])
        self.assertEqual(len(pushes), 1, "one block push mapping is required")
        filters = {}
        current = None
        for line in pushes[0].splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key = re.fullmatch(r"    (branches|paths):", line)
            item = re.fullmatch(r"      - ([A-Za-z0-9_./*?-]+)", line)
            if key:
                current = key[1]
                self.assertNotIn(current, filters, "duplicate push filter")
                filters[current] = []
            elif item and current is not None:
                filters[current].append(item[1])
            else:
                self.fail(f"unsupported push filter syntax: {line!r}")
        self.assertIn("branches", filters, "qualification must remain branch-scoped")
        self.assertTrue(all(filters.values()), "empty filters are ambiguous")
        return any(
            fnmatch.fnmatchcase(branch, pattern) for pattern in filters["branches"]
        ) and (
            "paths" not in filters
            or any(
                fnmatch.fnmatchcase(path, pattern)
                for path in changed_paths
                for pattern in filters["paths"]
            )
        )

    def test_final_binding_only_push_enqueues_exact_head(self):
        paths = (
            "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json",
            "docs/modules/kernel.operations/IMPLEMENTATION_MAP.json",
            "docs/modules/learning.plasticity/CURRENT_STATE.json",
            "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json",
            "docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json",
            "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json",
        )
        self.assertTrue(self.push_enqueues(self.branch, paths))

    def test_shared_build_and_lint_inputs_enqueue_exact_head(self):
        for path in (
            "codex-rs/Cargo.toml",
            "codex-rs/Cargo.lock",
            "codex-rs/clippy.toml",
            "codex-rs/rustfmt.toml",
            "codex-rs/.cargo/config.toml",
            "codex-rs/rust-toolchain.toml",
        ):
            with self.subTest(path=path):
                self.assertTrue(self.push_enqueues(self.branch, [path]))

    def test_dependency_and_owned_fixture_changes_enqueue_exact_head(self):
        for path in (
            "codex-rs/hepta-types/src/lib.rs",
            "codex-rs/hepta-agentd/tests/plasticity_process_e2e.rs",
            "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
        ):
            with self.subTest(path=path):
                self.assertTrue(self.push_enqueues(self.branch, [path]))

    def test_unrelated_branches_do_not_enqueue_objective_qualification(self):
        for branch in ("main", "feature/unrelated", self.branch + "-other"):
            with self.subTest(branch=branch):
                self.assertFalse(
                    self.push_enqueues(branch, ["codex-rs/hepta-objective/src/lib.rs"])
                )


class GitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Recorder test")
        self.git("config", "user.email", "test@localhost")
        (self.root / "base").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "source")
        (self.root / "source").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.source = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True
        ).strip()

    def test_exact_checkout_and_external_output_required(self):
        MODULE.validate_identity(
            self.root, self.source, self.base, Path(self.temp.name) / "out"
        )
        for source, out in (
            (self.base, Path(self.temp.name) / "out"),
            (self.source[:12], Path(self.temp.name) / "out"),
            (self.source, self.root / "out"),
        ):
            with self.subTest(source=source, out=out), self.assertRaises(ValueError):
                MODULE.validate_identity(self.root, source, self.base, out)
        (self.root / "untracked").write_text("dirty")
        with self.assertRaises(ValueError):
            MODULE.validate_identity(
                self.root, self.source, self.base, Path(self.temp.name) / "out"
            )

    def test_synthetic_merge_is_deterministic_and_does_not_move_source(self):
        first = MODULE.deterministic_merge(self.root, self.source, self.base)
        second = MODULE.deterministic_merge(self.root, self.source, self.base)
        self.assertEqual(first, second)
        spec = importlib.util.spec_from_file_location(
            "projection",
            Path(__file__).with_name("hepta-objective-evidence-project.py"),
        )
        projection = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(projection)
        self.assertEqual(
            first[0],
            projection.synthetic_commit_identity(first[1], self.base, self.source),
        )
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")
        parents = self.git("show", "-s", "--format=%P", first[0]).split()
        self.assertEqual(parents, [self.base, self.source])

    def test_conflicting_merge_is_not_resolved_by_recorder(self):
        self.git("checkout", "-qb", "other", self.base)
        (self.root / "base").write_text("other\n")
        self.git("commit", "-qam", "other")
        other = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "source")
        (self.root / "base").write_text("source conflict\n")
        self.git("commit", "-qam", "source conflict")
        source = self.git("rev-parse", "HEAD")
        with self.assertRaises(subprocess.CalledProcessError):
            MODULE.deterministic_merge(self.root, source, other)
        self.assertEqual(self.git("rev-parse", "HEAD"), source)
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
