#!/usr/bin/env python3
"""Regression checks for declaration-only legacy NDU compatibility."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-ndu-source-policy.py")
SPEC = importlib.util.spec_from_file_location("hepta_ndu_source_policy", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
ROOT_API = Path("codex-rs/hepta-ndu/src/lib.rs")
DEFINITION = (
    "pub fn evaluate_candidates(set: ContributionSet) -> Result<Receipt, Error> {\n"
    "    evaluate_candidates_with_policy(set, explicit_policy)\n"
    "}\n"
)


class LegacyNduSourcePolicyTests(unittest.TestCase):
    def test_approved_root_definition_is_not_a_call(self):
        self.assertEqual(POLICY.legacy_call_lines(ROOT_API, DEFINITION), [])

    def test_whitespace_in_approved_definition_is_supported(self):
        definition = DEFINITION.replace(
            "pub fn evaluate_candidates(", "pub\nfn\n evaluate_candidates\n("
        )
        self.assertEqual(POLICY.legacy_call_lines(ROOT_API, definition), [])

    def test_root_invocations_are_rejected(self):
        for call in [
            "evaluate_candidates(set, profile, None);",
            "codex_hepta_ndu::evaluate_candidates(set, profile, None);",
            "evaluate_candidates \n(set, profile, None);",
        ]:
            with self.subTest(call=call):
                self.assertEqual(POLICY.legacy_call_lines(ROOT_API, call), [1])

    def test_root_definition_does_not_exempt_later_invocation(self):
        text = DEFINITION + "fn product() { evaluate_candidates(set, profile, None); }\n"
        self.assertEqual(POLICY.legacy_call_lines(ROOT_API, text), [4])

    def test_root_definition_does_not_exempt_recursive_invocation(self):
        text = DEFINITION.replace(
            "evaluate_candidates_with_policy(set, explicit_policy)",
            "evaluate_candidates(set, profile, None)",
        )
        self.assertEqual(POLICY.legacy_call_lines(ROOT_API, text), [2])

    def test_same_line_definition_exempts_only_its_name(self):
        text = "pub fn evaluate_candidates() { evaluate_candidates(set, profile, None); }"
        self.assertEqual(POLICY.legacy_call_lines(ROOT_API, text), [1])

    def test_other_production_definition_fails_closed(self):
        self.assertEqual(
            POLICY.legacy_call_lines(Path("codex-rs/other/src/lib.rs"), DEFINITION),
            [1],
        )

    def test_former_evaluator_file_is_no_longer_exempt(self):
        self.assertEqual(
            POLICY.legacy_call_lines(
                Path("codex-rs/hepta-ndu/src/evaluator.rs"),
                "fn product() { evaluate_candidates(set, profile, None); }",
            ),
            [1],
        )

    def test_existing_compatibility_test_allowance_is_retained(self):
        self.assertEqual(
            POLICY.legacy_call_lines(
                Path("codex-rs/hepta-ndu/src/evaluator_tests.rs"),
                "evaluate_candidates(set, profile, None);",
            ),
            [],
        )

    def test_explicit_policy_call_is_not_legacy(self):
        self.assertEqual(
            POLICY.legacy_call_lines(ROOT_API, "evaluate_candidates_with_policy(set, policy);"),
            [],
        )

    def test_filesystem_scan_reports_root_invocation_beside_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ROOT_API
            path.parent.mkdir(parents=True)
            path.write_text(
                DEFINITION + "evaluate_candidates(set, profile, None);\n",
                encoding="utf-8",
            )
            with mock.patch.object(POLICY, "ROOT", root):
                with self.assertRaises(SystemExit) as raised:
                    POLICY.main()
            self.assertEqual(
                str(raised.exception),
                "FAIL_NDU_LEGACY_CALLER_POLICY: codex-rs/hepta-ndu/src/lib.rs:4"
                "; use evaluate_candidates_with_policy",
            )

    def test_filesystem_scan_accepts_only_approved_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ROOT_API
            path.parent.mkdir(parents=True)
            path.write_text(DEFINITION, encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(POLICY, "ROOT", root), contextlib.redirect_stdout(output):
                POLICY.main()
            self.assertEqual(output.getvalue(), "PASS_NDU_LEGACY_CALLER_POLICY\n")


if __name__ == "__main__":
    unittest.main()
