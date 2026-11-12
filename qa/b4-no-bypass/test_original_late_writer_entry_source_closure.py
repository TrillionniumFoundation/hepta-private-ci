"""Mutate real late-writer source copies and require the original B4 verifier to reject them.

These source-proof tests create no Root owner and perform no handoff. Diagnostic
path labels remain raw text requirements; only the entry value and CODEX_HOME
key have exact literal-span requirements.
"""

import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_late_writer_entry_verifier", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

STARTUP = "codex-rs/hepta-agentd/src/production_launcher_late_startup.rs"
IDENTITY = "codex-rs/hepta-agentd/src/config_late_writer_identity.rs"
PATH_CALLS = (
    'require_canonical(&self.fleet_root, "fleet root")?;',
    'require_exact_path(&self.home_root, record.layout.home_root(), "agent home")?;',
    'require_exact_path(&self.run_root, record.layout.run_root(), "agent run root")?;',
    'require_exact_path(&self.codex_home, record.layout.home_root(), "Codex home")?;',
)


class OriginalLateWriterEntrySourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        rows = [
            row for row in manifest["protected_file"]
            if row["path"] in (STARTUP, IDENTITY)
        ]
        self.assertEqual(tuple(row["path"] for row in rows), (STARTUP, IDENTITY))
        self.manifest = {"protected_file": rows}
        for relative in (STARTUP, IDENTITY):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.assertEqual(
            MODULE._verify_protected_files(self.root, self.manifest),
            [STARTUP, IDENTITY],
        )

    def rejects(self, relative, original, replacement, reason):
        path = self.root / relative
        source = path.read_text(encoding="utf-8")
        self.assertEqual(source.count(original), 1)
        path.write_text(source.replace(original, replacement, 1), encoding="utf-8")
        try:
            with self.assertRaisesRegex(MODULE.VerificationFailure, reason):
                MODULE._verify_protected_files(self.root, self.manifest)
        finally:
            path.write_text(source, encoding="utf-8")

    def test_entry_value_cannot_change(self):
        self.rejects(
            STARTUP,
            'Some("late-writer")',
            'Some("late-writeX")',
            "unique actual literal call required",
        )

    def test_entry_value_cannot_be_supplied_by_comment(self):
        self.rejects(
            STARTUP,
            'Some("late-writer")',
            '/* Some("late-writer") */ Some("late-writeX")',
            "unique actual literal call required",
        )

    def test_entry_value_comparison_cannot_reverse(self):
        self.rejects(
            STARTUP,
            '!= Some("late-writer")',
            '== Some("late-writer")',
            "required code order missing",
        )

    def test_duplicate_entry_cannot_drop_its_rejection(self):
        self.rejects(
            STARTUP,
            'if selected.is_some() {\n'
            '            return Err(AgentdError::Invalid(\n'
            '                "duplicate --root-production-entry".into(),\n'
            '            ));\n'
            '        }',
            "if selected.is_some() {}",
            "required code order missing",
        )

    def test_codex_home_key_cannot_change_or_hide_in_comment(self):
        original = 'required_path("CODEX_HOME")'
        for replacement in (
            'required_path("CODEX_H0ME")',
            '/* required_path("CODEX_HOME") */ required_path("CODEX_H0ME")',
        ):
            with self.subTest(replacement=replacement):
                self.rejects(
                    IDENTITY, original, replacement,
                    "unique actual literal call required",
                )

    def test_codex_home_read_cannot_drop_error_propagation(self):
        self.rejects(
            IDENTITY,
            'required_path("CODEX_HOME")?,',
            'required_path("CODEX_HOME"),',
            "required code order missing",
        )

    def test_path_guards_cannot_be_replaced_by_comments(self):
        for original in PATH_CALLS:
            with self.subTest(call=original):
                self.rejects(
                    IDENTITY, original, f"/* {original} */",
                    "required code order missing",
                )

    def test_path_guards_cannot_change_the_checked_actual_path(self):
        wrong_actual = (
            PATH_CALLS[0].replace("self.fleet_root", "self.home_root"),
            PATH_CALLS[1].replace("self.home_root", "self.run_root"),
            PATH_CALLS[2].replace("self.run_root", "self.home_root"),
            PATH_CALLS[3].replace("self.codex_home", "self.run_root"),
        )
        for original, replacement in zip(PATH_CALLS, wrong_actual, strict=True):
            with self.subTest(call=original):
                self.rejects(
                    IDENTITY, original, f"/* {original} */ {replacement}",
                    "required code order missing",
                )

    def test_path_guards_cannot_change_the_expected_path(self):
        wrong_expected = (
            PATH_CALLS[1].replace("record.layout.home_root()", "record.layout.run_root()"),
            PATH_CALLS[2].replace("record.layout.run_root()", "record.layout.home_root()"),
            PATH_CALLS[3].replace("record.layout.home_root()", "record.layout.run_root()"),
        )
        for original, replacement in zip(PATH_CALLS[1:], wrong_expected, strict=True):
            with self.subTest(call=original):
                self.rejects(
                    IDENTITY, original, f"/* {original} */ {replacement}",
                    "required code order missing",
                )

    def test_path_guards_cannot_drop_error_propagation(self):
        for original in PATH_CALLS:
            replacement = original.replace("?;", ";")
            with self.subTest(call=original):
                self.rejects(
                    IDENTITY, original, f"/* {original} */ {replacement}",
                    "required code order missing",
                )


if __name__ == "__main__":
    unittest.main()
