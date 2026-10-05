"""Source-document projection tests; no runtime or acceptance claims."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "intuition_state.py"
SPEC = importlib.util.spec_from_file_location("intuition_state", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
state_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state_tools)


class SourceStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.value = {
            "schema": "hepta.intuition.source-state.v1",
            "module": "intuition.policy",
            "authority": "source_state_only",
            "completion": {name: False for name in state_tools.FLAGS},
            "facts": [
                {
                    "id": name,
                    "summary": "Test-only source fixture",
                    "state": "source_present",
                    "source": "codex-rs/fixture.rs",
                    "symbol": "fixture_symbol",
                    "tests": ["scripts/tests/fixture.py"],
                    "evidence": "Real artifacts required",
                }
                for name in sorted(state_tools.FACT_IDS)
            ],
            "gaps": [
                {"id": name, "required": "Real completion remains required"}
                for name in sorted(state_tools.GAP_IDS)
            ],
            "contracts": [
                {"name": "FixtureV1", "layer": "fixture", "status": "test only"}
            ],
        }
        files = {
            "codex-rs/fixture.rs": "fn fixture_symbol() {}\n",
            "scripts/tests/fixture.py": "# source fixture only\n",
            state_tools.MAP: json.dumps(
                {"full_completion_predicate": self.value["completion"]}
            ),
        }
        for name in state_tools.DOCS:
            files[name] = "# Existing technical document\n\nKEEP THE ORIGINAL DESIGN.\n"
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.save()

    def save(self):
        (self.root / state_tools.STATE).write_text(
            json.dumps(self.value), encoding="utf-8"
        )

    def test_generation_is_idempotent_and_retains_original_design(self):
        self.assertTrue(state_tools.project(self.root, write=True))
        self.assertEqual(state_tools.project(self.root, write=True), [])
        self.assertEqual(state_tools.project(self.root), [])
        for name in state_tools.DOCS:
            self.assertIn(
                "KEEP THE ORIGINAL DESIGN.",
                (self.root / name).read_text(encoding="utf-8"),
            )

    def test_check_reports_drift_without_modifying_any_file(self):
        state_tools.project(self.root, write=True)
        path = self.root / state_tools.DOCS[0]
        path.write_text(
            path.read_text(encoding="utf-8").replace("source_present", "stale", 1),
            encoding="utf-8",
        )
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertIn(state_tools.DOCS[0], state_tools.project(self.root))
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                state_tools.load_json(text)

    def test_unknown_state_fields_are_rejected(self):
        self.value["passed"] = True
        with self.assertRaises(ValueError):
            state_tools.validate(self.value, self.root)

    def test_source_state_cannot_mint_completion_or_numeric_false(self):
        for flag in state_tools.FLAGS:
            for value in (True, 0, "false", None):
                changed = copy.deepcopy(self.value)
                changed["completion"][flag] = value
                with (
                    self.subTest(flag=flag, value=value),
                    self.assertRaises(ValueError),
                ):
                    state_tools.validate(changed, self.root)

    def test_execution_pass_is_not_a_source_state(self):
        self.value["facts"][0]["state"] = "verified"
        with self.assertRaises(ValueError):
            state_tools.validate(self.value, self.root)

    def test_omitted_or_duplicated_requirements_are_rejected(self):
        for collection in ("facts", "gaps"):
            changed = copy.deepcopy(self.value)
            changed[collection][-1] = changed[collection][0]
            with self.assertRaises(ValueError):
                state_tools.validate(changed, self.root)
            changed = copy.deepcopy(self.value)
            changed[collection].pop()
            with self.assertRaises(ValueError):
                state_tools.validate(changed, self.root)

    def test_missing_source_symbol_is_rejected(self):
        self.value["facts"][0]["symbol"] = "not_present"
        with self.assertRaises(ValueError):
            state_tools.validate(self.value, self.root)

    def test_missing_test_file_is_rejected(self):
        self.value["facts"][0]["tests"] = ["scripts/tests/missing.py"]
        with self.assertRaises(ValueError):
            state_tools.validate(self.value, self.root)

    def test_scope_escape_and_noncanonical_paths_are_rejected(self):
        for path in (
            "../escape",
            "/absolute",
            "C:/escape",
            "docs/../escape",
            "docs//x",
            "docs/./x",
            "docs\\x",
            "secrets/key",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                state_tools.safe_file(self.root, path, must_exist=False)

    def test_duplicate_and_incomplete_generated_markers_are_rejected(self):
        for original in (
            "# A\n" + state_tools.START,
            state_tools.START + state_tools.END + state_tools.START,
            state_tools.END + state_tools.START,
        ):
            with self.subTest(original=original), self.assertRaises(ValueError):
                state_tools.replace_block(original, "replacement")

    def test_projection_refuses_disagreeing_completion(self):
        mapping = {
            "full_completion_predicate": {name: True for name in state_tools.FLAGS}
        }
        (self.root / state_tools.MAP).write_text(json.dumps(mapping), encoding="utf-8")
        with self.assertRaises(ValueError):
            state_tools.project(self.root, write=True)

    def test_repository_projection_is_current(self):
        self.assertEqual(state_tools.project(state_tools.ROOT), [])


if __name__ == "__main__":
    unittest.main()
