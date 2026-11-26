#!/usr/bin/env python3
"""Finite end-to-end controls for the fixed required-method-literal prefilter.

The controls exercise the real verify entry point on complete temporary source
trees and manifests. A transparent regex wrapper counts actual original search
calls; it never substitutes a matcher result.
"""

import importlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
scanner = importlib.import_module("verify_hepta_callers")


ASCII_PREFIX = r"(?:\.\s*|[A-Za-z_][A-Za-z0-9_]*\s*::\s*)"
WORD_PREFIX = r"(?:\.\s*|[A-Za-z_]\w*\s*::\s*)"


class OriginalSearch:
    def __init__(self, compiled: re.Pattern[str], calls: list[int]):
        self.compiled = compiled
        self.calls = calls

    def search(self, *args, **kwargs):
        self.calls[0] += 1
        return self.compiled.search(*args, **kwargs)


class RequiredLiteralBoundaryControls(unittest.TestCase):
    def verify_fixture(
        self,
        pattern: str | None,
        caller: str,
        *,
        expected: tuple[str, ...] = ("src/caller.rs",),
        receiver_type: str | None = None,
        definition: str = "pub struct Gate;\npub struct Other;\n",
    ) -> dict:
        self.search_calls = [0]
        manifest = [
            "schema_version = 2",
            'plan_id = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"',
            'source_roots = ["src"]',
            'ignored_path_fragments = ["/tests/"]',
            "[authority]",
            "granted = false",
            "[privileged_inventory]",
            'required_boundary_ids = ["gate"]',
            "[[boundary]]",
            'id = "gate"',
            'symbol = "Gate::commit"',
            'definition_path = "src/definition.rs"',
            'definition_markers = ["pub struct Gate;"]',
            "product_callers = " + json.dumps(list(expected)),
            'caller_markers = ["require_authority()"]',
        ]
        if pattern is not None:
            manifest.append("call_pattern = " + json.dumps(pattern))
        if receiver_type is not None:
            manifest.append("receiver_type = " + json.dumps(receiver_type))
        manifest.extend(
            [
                "[[protected_file]]",
                'path = "src/caller.rs"',
                'required = ["fn guarded"]',
                'forbidden = ["Forbidden::grant"]',
            ]
        )
        observed_pattern = (
            pattern if pattern is not None else re.escape("Gate::commit") + r"\s*\("
        )
        original_compile = re.compile

        def compile_with_tracking(expression, flags=0):
            compiled = original_compile(expression, flags)
            if expression == observed_pattern:
                return OriginalSearch(compiled, self.search_calls)
            return compiled

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "src").mkdir()
            (root / "CALLERS.toml").write_text(
                "\n".join(manifest) + "\n", encoding="utf-8"
            )
            (root / "src/definition.rs").write_text(definition, encoding="utf-8")
            (root / "src/caller.rs").write_text(caller, encoding="utf-8")
            with mock.patch.object(scanner.re, "compile", compile_with_tracking):
                return scanner.verify(root)

    def assert_pass(self, receipt, callers=("src/caller.rs",)):
        self.assertEqual(receipt["status"], "PASS_HEPTA_CALLER_CLOSED_SET")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], list(callers))
        self.assertEqual(receipt["privilegedInventory"], ["gate"])
        self.assertEqual(receipt["protectedFiles"], ["src/caller.rs"])
        self.assertEqual(receipt["rustFilesScanned"], 2)
        self.assertIs(receipt["authorityGranted"], False)

    def test_known_ascii_dot_call_still_runs_original_search(self):
        result = self.verify_fixture(
            ASCII_PREFIX + r"commit\s*\(",
            "fn guarded() { require_authority(); receiver.commit(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_known_word_qualified_multiline_call_still_matches(self):
        result = self.verify_fixture(
            WORD_PREFIX + r"commit\s*\(",
            "fn guarded() { require_authority(); Gate \n :: \n commit \n (); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_absent_method_can_skip_search_without_granting_a_caller(self):
        result = self.verify_fixture(
            ASCII_PREFIX + r"commit\s*\(",
            "fn guarded() { require_authority(); unrelated(); }\n",
            expected=(),
        )
        self.assert_pass(result, callers=())
        self.assertEqual(self.search_calls, [0])

    def test_absent_declared_caller_is_rejected(self):
        with self.assertRaisesRegex(
            scanner.VerificationFailure,
            "caller set mismatch; missing=\\['src/caller.rs'\\]",
        ):
            self.verify_fixture(
                WORD_PREFIX + r"commit\s*\(",
                "fn guarded() { require_authority(); unrelated(); }\n",
            )
        self.assertEqual(self.search_calls, [0])

    def test_unlisted_known_caller_is_rejected(self):
        with self.assertRaisesRegex(
            scanner.VerificationFailure,
            "caller set mismatch; missing=\\[\\], unexpected=\\['src/caller.rs'\\]",
        ):
            self.verify_fixture(
                ASCII_PREFIX + r"commit\s*\(",
                "fn guarded() { require_authority(); receiver.commit(); }\n",
                expected=(),
            )
        self.assertEqual(self.search_calls, [1])

    def test_literal_presence_without_call_does_not_grant(self):
        with self.assertRaisesRegex(scanner.VerificationFailure, "caller set mismatch"):
            self.verify_fixture(
                WORD_PREFIX + r"commit\s*\(",
                "fn guarded() { require_authority(); let commit_pending = true; }\n",
            )
        self.assertEqual(self.search_calls, [1])

    def test_comments_literals_and_cfg_tests_cannot_supply_a_caller(self):
        source = (
            'fn guarded() { require_authority(); let text = "Gate::commit()"; }\n'
            "// receiver.commit();\n"
            "#[cfg(test)] mod tests { fn fake() { Gate::commit(); } }\n"
        )
        with self.assertRaisesRegex(scanner.VerificationFailure, "caller set mismatch"):
            self.verify_fixture(ASCII_PREFIX + r"commit\s*\(", source)
        self.assertEqual(self.search_calls, [0])

    def test_unknown_whole_pattern_alternation_falls_back(self):
        pattern = ASCII_PREFIX + r"commit\s*\(|\bpermit\s*\("
        result = self.verify_fixture(
            pattern, "fn guarded() { require_authority(); permit(); }\n"
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_method_alternation_falls_back(self):
        result = self.verify_fixture(
            WORD_PREFIX + r"(?:commit|cancel)\s*\(",
            "fn guarded() { require_authority(); receiver.cancel(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_case_flag_falls_back(self):
        result = self.verify_fixture(
            "(?i)" + ASCII_PREFIX + r"commit\s*\(",
            "fn guarded() { require_authority(); receiver.COMMIT(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_escaped_method_falls_back(self):
        result = self.verify_fixture(
            WORD_PREFIX + r"\x63ommit\s*\(",
            "fn guarded() { require_authority(); receiver.commit(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_optional_method_suffix_falls_back(self):
        result = self.verify_fixture(
            ASCII_PREFIX + r"commit(?:_checked)?\s*\(",
            "fn guarded() { require_authority(); receiver.commit_checked(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_suffix_assertion_falls_back(self):
        result = self.verify_fixture(
            WORD_PREFIX + r"commit\s*\((?=\))",
            "fn guarded() { require_authority(); receiver.commit(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_unicode_method_falls_back(self):
        result = self.verify_fixture(
            ASCII_PREFIX + r"commít\s*\(",
            "fn guarded() { require_authority(); receiver.commít(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_unknown_pattern_does_not_borrow_the_symbol_hint(self):
        result = self.verify_fixture(
            r"\bcancel\s*\(",
            "fn guarded() { require_authority(); cancel(); }\n",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])

    def test_typed_boundary_keeps_its_independent_receiver_path(self):
        result = self.verify_fixture(
            ASCII_PREFIX + r"irrelevant\s*\(",
            "fn guarded(authority: &Gate) { require_authority(); authority.commit(); }\n",
            receiver_type="Gate",
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [0])

    def test_unresolved_typed_receiver_is_still_rejected(self):
        with self.assertRaisesRegex(
            scanner.VerificationFailure, "unresolved possible Gate::commit receiver"
        ):
            self.verify_fixture(
                WORD_PREFIX + r"irrelevant\s*\(",
                "fn guarded(authority: &Gate) { require_authority(); opaque.commit(); }\n",
                expected=(),
                receiver_type="Gate",
            )
        self.assertEqual(self.search_calls, [0])

    def test_caller_guard_marker_remains_required(self):
        with self.assertRaisesRegex(scanner.VerificationFailure, "lacks guard marker"):
            self.verify_fixture(
                ASCII_PREFIX + r"commit\s*\(",
                "fn guarded() { receiver.commit(); }\n",
            )
        self.assertEqual(self.search_calls, [1])

    def test_protected_forbidden_marker_is_checked_after_skipped_search(self):
        with self.assertRaisesRegex(
            scanner.VerificationFailure, "forbidden marker present"
        ):
            self.verify_fixture(
                WORD_PREFIX + r"commit\s*\(",
                "fn guarded() { require_authority(); Forbidden::grant(); }\n",
                expected=(),
            )
        self.assertEqual(self.search_calls, [0])

    def test_definition_marker_is_checked_before_any_filter(self):
        with self.assertRaisesRegex(
            scanner.VerificationFailure, "missing definition marker"
        ):
            self.verify_fixture(
                ASCII_PREFIX + r"commit\s*\(",
                "fn guarded() { require_authority(); unrelated(); }\n",
                expected=(),
                definition="pub struct Other;\n",
            )
        self.assertEqual(self.search_calls, [0])

    def test_automatic_exact_symbol_path_is_unchanged(self):
        result = self.verify_fixture(
            None, "fn guarded() { require_authority(); Gate::commit(); }\n"
        )
        self.assert_pass(result)
        self.assertEqual(self.search_calls, [1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
