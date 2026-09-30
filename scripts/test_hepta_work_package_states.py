"""Exercise drift detection and safe refresh of existing work-package envelopes."""

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "hepta_module_docs", Path(__file__).with_name("hepta-module-docs.py")
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class WorkPackageStatesTests(unittest.TestCase):
    def project(self, text, check):
        return DOCS.project_work_package_states(
            text,
            [{"id": "WP-1", "state": "source_implemented"}],
            "fixture",
            check=check,
        )

    def test_drift_rejects_and_refresh_preserves_other_envelope_facts(self):
        text = "#### `WP-1`\n\n- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.\n- Owner: `team`.\n"
        with self.assertRaisesRegex(SystemExit, "state drift"):
            self.project(text, True)
        refreshed = self.project(text, False)
        self.assertEqual(refreshed, text.replace("`planned`", "`source_implemented`"))
        self.assertEqual(self.project(refreshed, True), refreshed)

    def test_refresh_changes_the_state_line_and_preserves_quoted_prose(self):
        text = (
            "#### `WP-1`\nA quoted example: - State: `planned`\n\n- State: `planned`\n"
        )
        refreshed = self.project(text, False)
        self.assertIn("A quoted example: - State: `planned`", refreshed)
        self.assertTrue(refreshed.endswith("- State: `source_implemented`\n"))
        self.project(refreshed, True)

    def test_conflicting_state_lines_cannot_hide_behind_the_first_line(self):
        text = "#### `WP-1`\n- State: `source_implemented`\n- State: `planned`\n"
        for check in (False, True):
            with (
                self.subTest(check=check),
                self.assertRaisesRegex(SystemExit, "duplicate"),
            ):
                self.project(text, check)

    def test_unknown_envelope_and_ambiguous_suffix_reject(self):
        for text in (
            "#### `WP-2`\n- State: `planned`\n",
            "#### `WP-1`\n- State: `source_implemented` then `planned`\n",
        ):
            with self.subTest(text=text), self.assertRaises(SystemExit):
                self.project(text, True)

    def test_prose_without_an_envelope_remains_optional(self):
        text = "## Operations\nA normal guide with no generated state inventory.\n"
        self.assertEqual(self.project(text, True), text)

    def test_malformed_state_lines_cannot_be_ignored_or_hide_a_duplicate(self):
        for line in ("- State: planned", "- State: `planned", "- State: ``"):
            for prefix in ("", "- State: `source_implemented`\n"):
                with (
                    self.subTest(line=line, prefix=prefix),
                    self.assertRaises(SystemExit),
                ):
                    self.project("#### `WP-1`\n" + prefix + line + "\n", True)


if __name__ == "__main__":
    unittest.main()
