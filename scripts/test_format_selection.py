"""Local formatter selection must never silently replace the full CI check."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "hepta_format_test_subject", Path(__file__).with_name("format.py")
)
formatter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = formatter
spec.loader.exec_module(formatter)


class FormatterSelectionTests(unittest.TestCase):
    def factories(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        mocks = {}
        for key, name in zip(
            formatter.FORMATTER_SCOPES,
            (
                "just_formatter_group",
                "rust_formatter_group",
                "buildifier_formatter_group",
                "python_sdk_formatter_group",
                "python_scripts_formatter_group",
            ),
            strict=True,
        ):
            mock = Mock(return_value=formatter.FormatterGroup(key, ()))
            mocks[key] = stack.enter_context(patch.object(formatter, name, mock))
        return mocks

    def test_default_retains_all_groups_in_existing_order(self):
        factories = self.factories()
        groups = formatter.formatter_groups(check=True)
        self.assertEqual(
            tuple(group.name for group in groups), formatter.FORMATTER_SCOPES
        )
        for factory in factories.values():
            factory.assert_called_once_with(check=True)

    def test_explicit_groups_are_deduplicated_before_construction(self):
        factories = self.factories()
        groups = formatter.formatter_groups(
            check=False, only=["rust", "python-scripts", "rust"]
        )
        self.assertEqual(
            tuple(group.name for group in groups), ("rust", "python-scripts")
        )
        for key, factory in factories.items():
            if key in ("rust", "python-scripts"):
                factory.assert_called_once_with(check=False)
            else:
                factory.assert_not_called()

    def test_unselected_sdk_and_bazel_factories_cannot_block_rust(self):
        factories = self.factories()
        for key in ("python-sdk", "bazel"):
            factories[key].side_effect = AssertionError(
                "unrelated dependency resolution"
            )
        self.assertEqual(
            formatter.formatter_groups(check=True, only=["rust"])[0].name, "rust"
        )

    def test_empty_or_unknown_internal_selection_never_becomes_success(self):
        self.factories()
        for selected in ([], ["unknown"], ["rust", "unknown"]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                formatter.formatter_groups(check=True, only=selected)

    def test_cli_rejects_unknown_scope_before_any_formatter_runs(self):
        self.factories()
        with (
            patch("sys.argv", ["format.py", "--only", "unknown"]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as result,
        ):
            formatter.main()
        self.assertEqual(result.exception.code, 2)

    def test_scoped_cli_reports_limited_scope_and_preserves_failure(self):
        self.factories()
        for code in (0, 1):
            output = io.StringIO()
            error = io.StringIO()
            with (
                patch("sys.argv", ["format.py", "--check", "--only", "rust"]),
                patch.object(
                    formatter,
                    "run_formatter_group",
                    return_value=formatter.FormatterResult("rust", "diagnostic", code),
                ),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(error),
            ):
                self.assertEqual(formatter.main(), code)
            self.assertIn("not full-repository validation", output.getvalue())
            if code:
                self.assertIn("diagnostic", error.getvalue())

    def test_unscoped_cli_still_executes_all_checks(self):
        self.factories()
        with (
            patch("sys.argv", ["format.py", "--check"]),
            patch.object(
                formatter,
                "run_formatter_group",
                side_effect=lambda group: formatter.FormatterResult(group.name, "", 0),
            ) as run,
        ):
            self.assertEqual(formatter.main(), 0)
        self.assertEqual(
            {call.args[0].name for call in run.call_args_list},
            set(formatter.FORMATTER_SCOPES),
        )

    def test_just_recipes_forward_explicit_options_but_keep_unscoped_defaults(self):
        recipes = Path(__file__).resolve().parents[1].joinpath("justfile").read_text()
        self.assertIn(
            "fmt *args:\n    @{{ python }} ../scripts/format.py {args}", recipes
        )
        self.assertIn(
            "fmt-check *args:\n    @{{ python }} ../scripts/format.py --check {args}",
            recipes,
        )

    def test_ci_keeps_unscoped_full_format_check(self):
        workflow = (
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath(".github/workflows/repo-checks.yml")
            .read_text()
        )
        self.assertIn("run: just fmt-check\n", workflow)
        self.assertNotIn("run: just fmt-check --only", workflow)


if __name__ == "__main__":
    unittest.main()
