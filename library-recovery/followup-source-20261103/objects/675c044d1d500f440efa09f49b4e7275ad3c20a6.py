"""Offline regression harness for pure Hepta type/facade source-custody rules.

The full source checkout is unavailable here. This validates the new source-only
rule on synthetic Rust text; it is NOT a native Rust compile or running CI.
"""
import re
import unittest

# Exact public native ABI identifiers exported by codex-hepta-types, source
# snapshot be8d81a878b3c408ac89a550e914cdaf2a15d39f.
PURE_NATIVE_EXPORTS = (
    "EXECUTION_CONTRACT_VERSION_V1",
    "CellExecutionIntentV1",
    "CodexTurnBindingV1",
    "ExecutionContractError",
    "ExecutionIntentKindV1",
    "ExecutionReceiptV1",
    "ExecutionStatusV1",
    "FinalPayloadDigestV1",
    "GenerationFenceWitnessV1",
    "NativeExecutionAdapter",
    "RecoveryDispositionV1",
    "RuntimeExecutionError",
    "RuntimeReceiptV1",
    "RuntimeToolIntentV1",
    "ToolOutcomeV1",
)


def check_native_facade_exports(facade_source: str) -> list[str]:
    """Source-only check of facade exports (not a Rust parser or security proof)."""
    errors: list[str] = []
    for name in PURE_NATIVE_EXPORTS:
        if not re.search(rf"\bpub\s+use\s+codex_hepta_types\s*::\s*{re.escape(name)}\s*;", facade_source):
            errors.append(f"hepta-codex-adapter: missing direct pure ABI re-export {name}")
    names = "|".join(map(re.escape, PURE_NATIVE_EXPORTS))
    declarations = re.compile(
        rf"\b(?:pub(?:\s*\([^)]*\))?\s+)?(?:struct|enum|trait|type|union|const|static)\s+(?:{names})\b"
    )
    if declarations.search(facade_source):
        errors.append("hepta-codex-adapter: duplicate execution contract definition")
    return errors


VALID = "\n".join(f"pub use codex_hepta_types::{s};" for s in PURE_NATIVE_EXPORTS)


class CheckFacade(unittest.TestCase):
    def test_all_direct_canonical_exports_are_allowed(self):
        self.assertEqual(check_native_facade_exports(VALID), [])

    def test_each_export_cannot_be_dropped_or_renamed(self):
        for name in PURE_NATIVE_EXPORTS:
            with self.subTest(name=name):
                tampered = VALID.replace(f"pub use codex_hepta_types::{name};", "")
                self.assertTrue(any(name in e for e in check_native_facade_exports(tampered)))

    def test_noncanonical_type_alias_fails(self):
        errors = check_native_facade_exports(VALID + "\npub type RuntimeToolIntentV1 = codex_hepta_types::RuntimeToolIntentV1;")
        self.assertTrue(any("duplicate" in e for e in errors), errors)

    def test_noncanonical_private_struct_fails(self):
        errors = check_native_facade_exports(VALID + "\npub(crate) struct GenerationFenceWitnessV1;")
        self.assertTrue(any("duplicate" in e for e in errors), errors)

    def test_unexported_equally_named_enum_fails(self):
        errors = check_native_facade_exports(VALID + "\nenum ToolOutcomeV1 { Unknown }")
        self.assertTrue(any("duplicate" in e for e in errors), errors)

    def test_shim_cannot_only_export_one_type(self):
        errors = check_native_facade_exports("pub use codex_hepta_types::ExecutionReceiptV1;")
        self.assertEqual(len(errors), len(PURE_NATIVE_EXPORTS) - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
