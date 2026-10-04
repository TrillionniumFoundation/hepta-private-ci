"""Source-audit regressions; these checks never certify installed host trust."""

import copy
import dataclasses
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "authority_inventory_verifier", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class AuthorityInventoryRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = VERIFIER._load_manifest(ROOT / "CALLERS.toml")
        self.rows = VERIFIER._boundary_rows(self.data)
        self.by_id = {row.identifier: row for row in self.rows}

    def code(self, raw: str) -> str:
        return VERIFIER._strip_cfg_test_items(VERIFIER._strip_rust_non_code(raw))

    def check(self, row, index):
        return VERIFIER._verify_boundary(
            ROOT, row, index, ("/tests/", "/examples/", "_tests.rs")
        )

    def test_alias_and_async_receivers_reject_unlisted_caller(self) -> None:
        cases = {
            "final_use_claim_raw": "final_use.claim(signed, binding)",
            "final_use_delivery_raw": "final_use.with_verified_use(token, binding, effect)",
            "final_use_guarded_effect": "authority.with_verified_effect(token, binding, effect)",
            "final_use_async_dispatch_fence": "authority.with_verified_use_async(token, binding, effect)",
        }
        for identifier, call in cases.items():
            with self.subTest(identifier=identifier):
                row = self.by_id[identifier]
                index = {path: self.code(f"fn consume() {{ {call}; }}") for path in row.product_callers}
                self.check(row, index)
                index["codex-rs/unapproved/src/lib.rs"] = self.code(f"fn bypass() {{ {call}; }}")
                with self.assertRaisesRegex(VERIFIER.VerificationFailure, "unapproved"):
                    self.check(row, index)

    def test_qualified_async_syntax_remains_covered(self) -> None:
        row = self.by_id["final_use_async_dispatch_fence"]
        call = "FinalUseAuthority::with_verified_use_async(authority, token, binding, effect)"
        index = {path: self.code(f"fn consume() {{ {call}; }}") for path in row.product_callers}
        self.check(row, index)
        index["codex-rs/unapproved/src/lib.rs"] = self.code(f"fn bypass() {{ {call}; }}")
        with self.assertRaisesRegex(VERIFIER.VerificationFailure, "unapproved"):
            self.check(row, index)

    def test_receiver_decoys_do_not_become_product_callers(self) -> None:
        row = self.by_id["final_use_async_dispatch_fence"]
        call = "authority.with_verified_use_async(token, binding, effect)"
        index = {path: self.code(f"fn consume() {{ {call}; }}") for path in row.product_callers}
        index["codex-rs/decoys/src/lib.rs"] = self.code(
            f'// {call};\n/* {call}; */\nconst TEXT: &str = "{call}";\n'
            f"#[cfg(all(test, unix))] mod tests {{ fn probe() {{ {call}; }} }}"
        )
        index["codex-rs/decoys/tests/probe.rs"] = self.code(f"fn probe() {{ {call}; }}")
        self.check(row, index)

    def test_missing_fence_or_zero_caller_api_remains_a_failure(self) -> None:
        for identifier in (
            "final_use_guarded_effect", "final_use_async_dispatch_fence",
            "final_use_async_entry", "bao_authbus_final_use_consumer",
        ):
            with self.subTest(identifier=identifier):
                rows = tuple(row for row in self.rows if row.identifier != identifier)
                with self.assertRaisesRegex(VERIFIER.VerificationFailure, identifier):
                    VERIFIER._verify_privileged_inventory(self.data, rows)

    def test_zero_product_caller_does_not_make_privileged_api_unrestricted(self) -> None:
        cases = {
            "final_use_async_entry": "authority.enter_verified_use(token, binding)",
            "bao_authbus_final_use_consumer": "client.consume_kv_v2_with_authbus(args)",
        }
        for identifier, call in cases.items():
            with self.subTest(identifier=identifier):
                row = self.by_id[identifier]
                self.check(row, {})
                with self.assertRaisesRegex(VERIFIER.VerificationFailure, "unapproved"):
                    self.check(row, {"codex-rs/unapproved/src/lib.rs": self.code(f"fn invoke() {{ {call}; }}")})

    def test_stale_expected_caller_does_not_pass(self) -> None:
        row = self.by_id["final_use_async_entry"]
        stale = dataclasses.replace(row, product_callers=("codex-rs/stale/src/lib.rs",))
        with self.assertRaisesRegex(VERIFIER.VerificationFailure, "missing=.*stale"):
            self.check(stale, {})

    def test_malformed_receiver_pattern_fails_before_scanning(self) -> None:
        data = copy.deepcopy(self.data)
        row = next(row for row in data["boundary"] if row["id"] == "final_use_async_dispatch_fence")
        row["call_pattern"] = r"authority\\s*\\("
        with self.assertRaisesRegex(VERIFIER.VerificationFailure, "invalid call_pattern"):
            VERIFIER._boundary_rows(data)

    def test_inventory_cannot_promote_compatibility_to_authority(self) -> None:
        # A cataloged caller, including compatibility constructors, is never an
        # authority grant. Exercise rejection, not a static flag assertion.
        original = (ROOT / "CALLERS.toml").read_text(encoding="utf-8")
        for flag in self.data["authority"]:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "CALLERS.toml"
                path.write_text(original.replace(f"{flag} = false", f"{flag} = true"), encoding="utf-8")
                with self.assertRaisesRegex(VERIFIER.VerificationFailure, "grants authority"):
                    VERIFIER._load_manifest(path)


if __name__ == "__main__":
    unittest.main()
