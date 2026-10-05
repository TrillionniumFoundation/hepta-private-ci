from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path
from unittest import mock


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

    def test_authority_receiver_renaming_cannot_escape_the_production_closed_set(self) -> None:
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        boundaries = {row.identifier: row for row in MODULE._boundary_rows(manifest)}
        ignored = tuple(manifest["ignored_path_fragments"])
        extra_path = "codex-rs/unregistered/src/lib.rs"
        generic_methods = {
            "final_use_delivery_raw",
            "final_use_dispatch_raw",
            "final_use_guarded_effect",
            "final_use_async_dispatch_fence",
            "bao_authbus_final_use_consumer",
        }
        for identifier in (
            "final_use_claim_raw",
            "final_use_delivery_raw",
            "final_use_dispatch_raw",
            "final_use_revocation_update",
            "final_use_guarded_effect",
            "final_use_async_dispatch_fence",
            "final_use_async_entry",
            "bao_final_use_consumer",
            "bao_authbus_final_use_consumer",
        ):
            boundary = boundaries[identifier]
            source_index = {
                path: MODULE._strip_cfg_test_items(
                    MODULE._strip_rust_non_code(
                        (ROOT / path).read_text(encoding="utf-8")
                    )
                )
                for path in boundary.product_callers
            }
            MODULE._verify_boundary(ROOT, boundary, source_index, ignored)
            type_name, method_name = boundary.symbol.split("::")
            crate_name = (
                "codex_hepta_bao_adapter"
                if type_name == "BaoClient"
                else "codex_hepta_contracts"
            )
            calls = [
                f"renamed.{method_name}()",
                f"{type_name}::{method_name}(renamed)",
            ]
            if identifier in generic_methods:
                calls.extend(
                    (
                        f"renamed.{method_name}::<Option<()>>()",
                        f"{type_name}::{method_name}::<Option<()>>(renamed)",
                    )
                )
            for call in calls:
                with self.subTest(boundary=identifier, call=call):
                    source_index[extra_path] = (
                        f"use {crate_name}::{type_name};\n"
                        f"fn leak(renamed: &{type_name}) {{ {call}; }}\n"
                    )
                    with self.assertRaisesRegex(
                        MODULE.VerificationFailure,
                        r"caller set mismatch; missing=\[\], unexpected=\['"
                        + extra_path
                        + r"'\]",
                    ):
                        MODULE._verify_boundary(ROOT, boundary, source_index, ignored)

    def test_unique_methods_reject_cross_file_reexport_alias_callers(self) -> None:
        import test_kernel_authority_closed_world as independent

        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        boundaries = {row.identifier: row for row in MODULE._boundary_rows(manifest)}
        inventory = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text(
                encoding="utf-8"
            )
        )
        rows = {row["id"]: row for row in inventory["boundaries"]}
        ignored = tuple(manifest["ignored_path_fragments"])
        alias_path = "codex-rs/unregistered/src/alias.rs"
        caller_path = "codex-rs/unregistered/src/lib.rs"
        for identifier in (
            "final_use_delivery_raw",
            "final_use_dispatch_raw",
            "final_use_revocation_update",
            "final_use_guarded_effect",
            "final_use_async_dispatch_fence",
            "final_use_async_entry",
            "bao_final_use_consumer",
            "bao_authbus_final_use_consumer",
        ):
            boundary = boundaries[identifier]
            source_index = {
                path: MODULE._strip_cfg_test_items(
                    MODULE._strip_rust_non_code(
                        (ROOT / path).read_text(encoding="utf-8")
                    )
                )
                for path in boundary.product_callers
            }
            MODULE._verify_boundary(ROOT, boundary, source_index, ignored)
            type_name, method_name = boundary.symbol.split("::")
            crate_name = (
                "codex_hepta_bao_adapter"
                if type_name == "BaoClient"
                else "codex_hepta_contracts"
            )
            calls = [
                f"renamed.{method_name}()",
                f"Gate::{method_name}(renamed)",
                f"<Gate>::{method_name}(renamed)",
            ]
            if identifier in (
                "final_use_delivery_raw",
                "final_use_dispatch_raw",
                "final_use_guarded_effect",
                "final_use_async_dispatch_fence",
                "bao_authbus_final_use_consumer",
            ):
                calls.extend(
                    (
                        f"renamed.{method_name}::<Option<()>>()",
                        f"Gate::{method_name}::<Option<()>>(renamed)",
                    )
                )
            with tempfile.TemporaryDirectory() as directory:
                fixture = Path(directory)
                alias = fixture / alias_path
                alias.parent.mkdir(parents=True)
                alias.write_text(
                    f"pub use {crate_name}::{type_name} as Gate;\n",
                    encoding="utf-8",
                )
                caller = fixture / caller_path
                for call in calls:
                    with self.subTest(boundary=identifier, call=call):
                        caller.write_text(
                            "mod alias;\n"
                            "use crate::alias::Gate;\n"
                            f"fn leak(renamed: &Gate) {{ {call}; }}\n",
                            encoding="utf-8",
                        )
                        for path in (alias_path, caller_path):
                            source_index[path] = MODULE._strip_cfg_test_items(
                                MODULE._strip_rust_non_code(
                                    (fixture / path).read_text(encoding="utf-8")
                                )
                            )
                        with self.assertRaisesRegex(
                            MODULE.VerificationFailure,
                            r"caller set mismatch; missing=\[\], unexpected=\['"
                            + caller_path
                            + r"'\]",
                        ):
                            MODULE._verify_boundary(ROOT, boundary, source_index, ignored)
                        proof = independent.KernelAuthorityClosedWorldTests(
                            "test_type_anchored_callers_match_independent_closed_set"
                        )
                        # The independent policy must see this alias caller even
                        # though its file contains no original authority type name.
                        with (
                            mock.patch.object(independent, "ROOT", fixture),
                            mock.patch.object(
                                proof,
                                "inventory",
                                return_value=[{**rows[identifier], "allowedCallers": []}],
                            ),
                            mock.patch.object(
                                proof, "rust_sources", return_value=[alias, caller]
                            ),
                            self.assertRaisesRegex(
                                AssertionError,
                                f"{identifier}: independent kernel.authority caller set drifted",
                            ),
                        ):
                            proof.test_type_anchored_callers_match_independent_closed_set()

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
