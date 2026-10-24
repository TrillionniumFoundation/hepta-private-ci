"""Synthetic receipt-parser controls; no Windows test is executed here."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-windows-delete-boundary.yml"


def reader():
    text = WORKFLOW.read_text()
    start = text.index("          import hashlib, json, os, re, sys\n")
    end = text.index("          PY\n", start)
    return textwrap.dedent(text[start:end])


def owner_cases(source):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(n, ast.Name) and n.id == "owner_selectors" for n in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("missing complete library case inventory")


VOLUME = (
    "native_local_ntfs_file_and_directory_report_same_volume",
    "native_nondisk_handle_is_rejected",
    "native_volume_observation_stays_bound_to_renamed_held_object",
    "native_directory_volume_observation_stays_bound_after_rename",
)
LOCK = (
    "native_owner_lock_child",
    "actual_second_process_reports_state_locked_then_owner_drop_releases",
    "actual_natural_process_exit_releases_original_os_lock_without_destructor",
    "actual_cold_missing_marker_and_nonempty_marker_never_reset",
)
PRINCIPAL = (
    "native_same_effective_token_revalidates",
    "native_same_sid_replacement_is_refused_and_cannot_revive",
    "native_held_token_modification_is_refused",
    "native_degraded_and_unqueryable_thread_tokens_never_fall_back",
)


def log(cases, *, passed=None, skipped=0, failed=0):
    return "".join(f"test {name} ... ok\n" for name in cases) + (
        f"Summary [0.123s] {len(cases)} tests run: {len(cases) if passed is None else passed} passed, {failed} failed, {skipped} skipped\n"
    )


def volume_markers():
    return "".join(
        "HEPTA_LOCAL_NTFS_OBSERVATION "
        + json.dumps(
            {
                "stage": stage,
                "owner_supported": False,
                "trusted_parent": False,
                "power_loss_qualified": False,
            }
        )
        + "\n"
        for stage in (
            "local_ntfs_complete",
            "nondisk_complete",
            "held_binding_complete",
            "held_directory_binding_complete",
        )
    )


class WindowsBoundaryReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = reader()
        cls.cases = owner_cases(cls.source)

    def evaluate(self, tag, minimum, text, *, codes="0 0"):
        with tempfile.TemporaryDirectory(
            prefix="windows-receipt-parser-only-"
        ) as temporary:
            out = Path(temporary) / "windows-delete-boundary"
            out.mkdir()
            (out / (tag + ".log")).write_text(text)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    self.source,
                    "tests",
                    tag,
                    str(minimum),
                    codes,
                ],
                cwd=ROOT,
                env={**os.environ, "RUNNER_TEMP": temporary},
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.stderr, b"")
            receipt = json.loads((out / (tag + ".json")).read_text())
            self.assertEqual(
                result.returncode, 0 if receipt["status"] == "passed" else 1
            )
            return result.returncode

    def test_complete_library_receipt_and_original_descriptors_are_required(self):
        self.assertEqual(len(self.cases), 37)
        self.assertEqual(len(set(self.cases)), 37)
        self.assertEqual(
            sum(name.startswith("security::tests::") for name in self.cases), 5
        )
        self.assertEqual(
            self.evaluate("private-owner-descriptor", 37, log(self.cases)), 0
        )
        self.assertEqual(
            self.evaluate("private-owner-descriptor", 5, log(self.cases)), 1
        )
        original = tuple(
            name for name in self.cases if name.startswith("security::tests::")
        )
        self.assertEqual(
            self.evaluate("private-owner-descriptor", 37, log(original)), 1
        )

    def test_every_missing_library_case_refuses_even_with_a_green_total(self):
        for name in self.cases:
            with self.subTest(name=name):
                missing = tuple(value for value in self.cases if value != name)
                self.assertEqual(
                    self.evaluate(
                        "private-owner-descriptor", 37, log(missing, passed=37)
                    ),
                    1,
                )

    def test_duplicate_and_unknown_named_results_refuse(self):
        for extra in (self.cases[0], "unregistered::case"):
            with self.subTest(extra=extra):
                text = "test " + extra + " ... ok\n" + log(self.cases)
                self.assertEqual(self.evaluate("private-owner-descriptor", 37, text), 1)

    def test_failures_skips_mismatched_totals_and_logging_failures_refuse(self):
        for kwargs in ({"passed": 36}, {"skipped": 1}, {"failed": 1}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(
                    self.evaluate(
                        "private-owner-descriptor", 37, log(self.cases, **kwargs)
                    ),
                    1,
                )
        self.assertEqual(
            self.evaluate("private-owner-descriptor", 37, log(self.cases), codes="0 1"),
            1,
        )

    def test_original_filtered_acl_selection_still_requires_every_selected_case(self):
        tree = ast.parse(self.source)
        cases = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(n, ast.Name) and n.id == "acl_selectors"
                for n in node.targets
            )
        )
        self.assertEqual(
            self.evaluate("acl-unit-controls", 8, log(cases, skipped=13)), 0
        )
        self.assertEqual(
            self.evaluate(
                "acl-unit-controls", 8, log(cases[:-1], passed=8, skipped=13)
            ),
            1,
        )

    def test_original_volume_controls_and_new_held_directory_are_all_required(self):
        complete = volume_markers() + log(VOLUME)
        self.assertEqual(self.evaluate("private-local-ntfs", 4, complete), 0)
        for index in range(4):
            with self.subTest(index=index):
                markers = volume_markers().splitlines(keepends=True)
                self.assertEqual(
                    self.evaluate(
                        "private-local-ntfs",
                        4,
                        "".join(markers[:index] + markers[index + 1 :]) + log(VOLUME),
                    ),
                    1,
                )
                self.assertEqual(
                    self.evaluate(
                        "private-local-ntfs",
                        4,
                        volume_markers() + log(VOLUME[:index] + VOLUME[index + 1 :]),
                    ),
                    1,
                )

    def test_all_real_owner_lock_process_cases_are_required(self):
        self.assertEqual(self.evaluate("private-owner-lock", 4, log(LOCK)), 0)
        for index in range(4):
            with self.subTest(index=index):
                self.assertEqual(
                    self.evaluate(
                        "private-owner-lock",
                        4,
                        log(LOCK[:index] + LOCK[index + 1 :], passed=4),
                    ),
                    1,
                )

    def test_multiple_or_missing_terminal_summaries_refuse(self):
        text = log(self.cases)
        for value in (text + text, "\n".join(text.splitlines()[:-1]) + "\n"):
            with self.subTest(value=value[-80:]):
                self.assertEqual(
                    self.evaluate("private-owner-descriptor", 37, value), 1
                )

    def test_all_principal_cases_require_exact_names_and_no_skips(self):
        self.assertEqual(
            self.evaluate("private-principal-continuity", 4, log(PRINCIPAL)), 0
        )
        for index in range(4):
            with self.subTest(index=index):
                self.assertEqual(
                    self.evaluate(
                        "private-principal-continuity",
                        4,
                        log(PRINCIPAL[:index] + PRINCIPAL[index + 1 :], passed=4),
                    ),
                    1,
                )
        for extra in (PRINCIPAL[0], "unregistered::principal"):
            with self.subTest(extra=extra):
                self.assertEqual(
                    self.evaluate(
                        "private-principal-continuity",
                        4,
                        "test " + extra + " ... ok\n" + log(PRINCIPAL),
                    ),
                    1,
                )
        self.assertEqual(
            self.evaluate("private-principal-continuity", 4, log(PRINCIPAL, skipped=1)),
            1,
        )

    def test_original_store_receipts_require_every_selected_native_case(self):
        tree = ast.parse(self.source)
        targets = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "store_selectors"
                for target in node.targets
            )
        )
        self.assertEqual(
            {name: len(cases) for name, cases in targets.items()},
            {"original-final-use-windows": 7, "original-registry-windows": 3},
        )
        for name, cases in targets.items():
            count = len(cases)
            with self.subTest(name=name):
                self.assertEqual(self.evaluate(name, count, log(cases, skipped=200)), 0)
                for index in range(count):
                    missing = cases[:index] + cases[index + 1 :]
                    self.assertEqual(
                        self.evaluate(name, count, log(missing, passed=count)), 1
                    )
                for extra in (cases[0], "unregistered::store"):
                    text = "test " + extra + " ... ok\n" + log(cases)
                    self.assertEqual(self.evaluate(name, count, text), 1)
                self.assertEqual(self.evaluate(name, count, log(cases, failed=1)), 1)
                self.assertEqual(self.evaluate(name, count + 1, log(cases)), 1)

    def test_existing_workflow_executes_complete_targets_without_filters(self):
        text = WORKFLOW.read_text()
        for target in ("--lib", "--test native_owner_lock", "--test native_volume"):
            command = next(
                line
                for line in text.splitlines()
                if "just test --locked -p codex-utils-windows-private-state "
                + target
                + " "
                in line
            )
            self.assertNotIn(" -E ", command)
            self.assertNotIn("--ignored", command)
        self.assertIn('tests private-owner-descriptor 37 "$codes"', text)
        self.assertIn('tests private-local-ntfs 4 "$codes"', text)
        self.assertIn('tests private-owner-lock 4 "$codes"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
