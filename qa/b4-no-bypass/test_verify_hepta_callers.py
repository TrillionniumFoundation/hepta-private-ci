from __future__ import annotations

import importlib.util
import json
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

    def test_registered_final_use_receivers_and_async_method_calls_remain_closed(self) -> None:
        boundaries = {
            row["id"]: row
            for row in MODULE._load_manifest(ROOT / "CALLERS.toml")["boundary"]
        }
        cases = [
            ("final_use_claim_raw", "claim", "authority", "."),
            ("final_use_claim_raw", "claim", "final_use", "."),
            ("final_use_claim_raw", "claim", "FinalUseAuthority", "::"),
            ("final_use_delivery_raw", "with_verified_use", "authority", "."),
            ("final_use_delivery_raw", "with_verified_use", "final_use", "."),
            ("final_use_delivery_raw", "with_verified_use", "FinalUseAuthority", "::"),
            ("final_use_async_dispatch_fence", "with_verified_use_async", "authority", "."),
            ("final_use_async_dispatch_fence", "with_verified_use_async", "FinalUseAuthority", "::"),
        ]
        for boundary_id, method, receiver, separator in cases:
            with self.subTest(boundary=boundary_id, receiver=receiver):
                root = self.make_fixture(method_pattern=True)
                manifest = root / "CALLERS.toml"
                lines = manifest.read_text(encoding="utf-8").splitlines()
                for index, line in enumerate(lines):
                    if line.lstrip().startswith("call_pattern = "):
                        lines[index] = "call_pattern = " + json.dumps(
                            boundaries[boundary_id]["call_pattern"]
                        )
                    elif line.lstrip().startswith("caller_markers = "):
                        lines[index] = f'caller_markers = ["{method}"]'
                    elif line.lstrip().startswith("required = "):
                        lines[index] = f'required = ["{method}"]'
                manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
                (root / "codex-rs/owner/src/lib.rs").write_text(
                    f"pub struct Gate; impl Gate {{ pub fn enter(&self) {{}} "
                    f"pub fn {method}(&self) {{}} }}\n",
                    encoding="utf-8",
                )
                parameters = f"{receiver}: &Gate" if separator == "." else ""
                call = f"fn use_gate({parameters}) {{ {receiver}\n {separator}{method}(); }}\n"
                (root / "codex-rs/caller/src/lib.rs").write_text(call, encoding="utf-8")
                receipt = MODULE.verify(root, manifest)
                self.assertEqual(
                    receipt["boundaries"][0]["productCallers"],
                    ["codex-rs/caller/src/lib.rs"],
                )
                extra = root / "codex-rs/unregistered/src"
                extra.mkdir(parents=True)
                (extra / "lib.rs").write_text(call, encoding="utf-8")
                with self.assertRaisesRegex(
                    MODULE.VerificationFailure,
                    "unexpected=.*codex-rs/unregistered/src/lib.rs",
                ):
                    MODULE.verify(root, manifest)

    def test_definition_only_effect_entrypoints_reject_new_product_callers(self) -> None:
        boundaries = {
            row["id"]: row
            for row in MODULE._load_manifest(ROOT / "CALLERS.toml")["boundary"]
        }
        cases = [
            ("final_use_enter_verified_use", "enter_verified_use", "FinalUseAuthority"),
            ("bao_authbus_final_use_consumer", "consume_kv_v2_with_authbus", "BaoClient"),
        ]
        for boundary_id, method, type_name in cases:
            with self.subTest(boundary=boundary_id):
                root = self.make_fixture(method_pattern=True)
                manifest = root / "CALLERS.toml"
                lines = manifest.read_text(encoding="utf-8").splitlines()
                for index, line in enumerate(lines):
                    if line.lstrip().startswith("call_pattern = "):
                        lines[index] = "call_pattern = " + json.dumps(
                            boundaries[boundary_id]["call_pattern"]
                        )
                    elif line.lstrip().startswith("product_callers = "):
                        lines[index] = "product_callers = []"
                    elif line.lstrip().startswith("caller_markers = "):
                        lines[index] = "caller_markers = []"
                manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
                receipt = MODULE.verify(root, manifest)
                self.assertEqual(receipt["boundaries"][0]["productCallers"], [])
                extra = root / "codex-rs/unregistered/src"
                extra.mkdir(parents=True)
                for call in (f"authority.{method}()", f"{type_name}::{method}()"):
                    (extra / "lib.rs").write_text(
                        f"fn bypass(authority: &Gate) {{ {call}; }}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        MODULE.VerificationFailure,
                        "unexpected=.*codex-rs/unregistered/src/lib.rs",
                    ):
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
