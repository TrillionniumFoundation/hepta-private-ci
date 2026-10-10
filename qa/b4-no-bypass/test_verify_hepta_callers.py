from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CallerProofTests(unittest.TestCase):
    def make_fixture(self, *, method_pattern: bool = False) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "codex-rs/owner/src").mkdir(parents=True)
        (root / "codex-rs/caller/src").mkdir(parents=True)
        (root / "codex-rs/owner/src/lib.rs").write_text(
            "pub struct Gate; impl Gate { pub fn enter(&self) {} }\n", encoding="utf-8"
        )
        caller = "fn use_gate(gate: &Gate) { gate.enter(); }\n" if method_pattern else "fn use_gate() { Gate::enter(); }\n"
        (root / "codex-rs/caller/src/lib.rs").write_text(caller, encoding="utf-8")
        pattern = 'call_pattern = "gate\\\\s*\\\\.\\\\s*enter\\\\s*\\\\("\n' if method_pattern else ""
        caller_marker = "gate.enter" if method_pattern else "Gate::enter"
        (root / "CALLERS.toml").write_text(
            textwrap.dedent(
                f"""
                schema_version = 2
                plan_id = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
                source_roots = ["codex-rs"]
                ignored_path_fragments = ["/tests/", "/examples/", "_tests.rs"]
                [privileged_inventory]
                required_boundary_ids = ["gate"]
                [[boundary]]
                id = "gate"
                symbol = "Gate::enter"
                {pattern}definition_path = "codex-rs/owner/src/lib.rs"
                definition_markers = ["pub struct Gate", "pub fn enter"]
                product_callers = ["codex-rs/caller/src/lib.rs"]
                caller_markers = ["{caller_marker}"]
                [[protected_file]]
                path = "codex-rs/caller/src/lib.rs"
                required = ["{caller_marker}"]
                forbidden = ["Gate::bypass"]
                [authority]
                runtime_authority = false
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return root

    def test_exact_caller_set_passes(self) -> None:
        root = self.make_fixture()
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["status"], "PASS_HEPTA_CALLER_CLOSED_SET")

    def test_method_call_pattern_passes(self) -> None:
        root = self.make_fixture(method_pattern=True)
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_typed_receiver_rejects_arbitrary_unregistered_parameter(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = manifest.read_text()
        text = "\n".join(line for line in text.splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass(completely_different: &Gate) { completely_different.enter(); }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_receiver_rejects_arbitrary_field_alias_in_split_impl(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(line for line in manifest.read_text().splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("struct Owner { anything: Gate }\n")
        (extra / "child.rs").write_text("impl Owner { fn bypass(&self) { self.anything.enter(); } }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_related_method_cannot_bypass_closed_set(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(line for line in manifest.read_text().splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"\nreceiver_methods = ["enter", "enter_next"]') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass(unexpected: &Gate) { unexpected.enter_next(); }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_cfg_test_callsite_does_not_manufacture_product_caller(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "#[cfg(all(test, unix))]\nmod tests { fn only_test() { Gate::enter(); } }\n",
            encoding="utf-8",
        )
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_cfg_test_fields_preserve_the_production_suffix(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "struct Store { live: u8, #[cfg(test)] test_only: Pair<u8, u8>, }\n"
            "impl Store { fn open() -> Self { Self { live: 1, #[cfg(test)] test_only: Pair::new(1, 2), } } }\n"
            "fn bypass() { Gate::enter(); }\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, root / "CALLERS.toml")
        stripped = MODULE._strip_cfg_test_items((extra / "lib.rs").read_text())
        self.assertEqual(stripped.count("{"), stripped.count("}"))
        self.assertIn("fn bypass", stripped)
        self.assertNotIn("test_only", stripped)

    def test_last_cfg_test_field_does_not_remove_enclosing_brace(self) -> None:
        source = "struct Store { live: u8, #[cfg(test)] test_only: u8 } fn f() { Gate::enter(); }"
        stripped = MODULE._strip_cfg_test_items(source)
        self.assertEqual(stripped.count("{"), stripped.count("}"))
        self.assertIn("Gate::enter", stripped)

    def test_cfg_production_alternatives_remain_visible(self) -> None:
        for condition in ("not(test)", "any(test, unix)", "all(not(test), unix)"):
            with self.subTest(condition=condition):
                source = f"#[cfg({condition})] fn bypass() {{ Gate::enter(); }}"
                self.assertIn("Gate::enter", MODULE._strip_cfg_test_items(source))
        self.assertNotIn("Gate::enter", MODULE._strip_cfg_test_items(
            "#[cfg(all(test, unix))] fn only_test() { Gate::enter(); }"
        ))

    def test_inventory_omission_fails(self) -> None:
        root = self.make_fixture()
        manifest = root / "CALLERS.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                'required_boundary_ids = ["gate"]',
                'required_boundary_ids = ["gate", "missing_privileged_boundary"]',
            ),
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, manifest)

    def test_unexpected_product_caller_fails(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass() { Gate::enter(); }\n", encoding="utf-8")
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, root / "CALLERS.toml")

    def test_comment_and_string_do_not_manufacture_callers(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            '// Gate::enter()\nconst TEXT: &str = "Gate::enter()";\n', encoding="utf-8"
        )
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_positive_authority_fails(self) -> None:
        root = self.make_fixture()
        manifest = root / "CALLERS.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "runtime_authority = false", "runtime_authority = true"
            ),
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, manifest)


if __name__ == "__main__":
    unittest.main()
