#!/usr/bin/env python3
"""Scoped source-contract regressions; native Rust checks remain required."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("authbus_projection", ROOT / "scripts/authbus-evidence-projection.py")
assert SPEC and SPEC.loader
PROJECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROJECTION)
BAO = "codex-rs/hepta-bao-adapter/src/durable_authbus.rs"
CONTRACT = "docs/modules/auth.authbus/PRODUCT_CALLER_CONTRACT.json"
MAPPING = {"productCallers": [{"name": "agentd_signed_text"}, {"name": "bao_kv_v2_read"}]}


class BaoInputContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / BAO).read_text()

    def test_real_receipt_identity_is_allowed(self):
        self.assertIn("pub operation_id: StableId", self.source)
        PROJECTION.validate_bao_input_surface(self.source)
        self.assertEqual(len(PROJECTION.validate_product_contract(MAPPING)["callers"]), 2)

    def test_multiline_comments_and_spacing_are_not_authority(self):
        source = self.source.replace("pub policy_revision: u64,", "pub /* policy { */\n policy_revision\n :\n u64\n ,")
        source = source.replace("operation: &EnteredAuthBusOperationHandle,", "operation /*nested /* } */ note*/ :\n & /* trusted */ EnteredAuthBusOperationHandle ,")
        PROJECTION.validate_bao_input_surface(source)

    def test_raw_operation_input_rejected_in_every_spelling(self):
        for field in ["pub operation_id: StableId,", "pub\n operation_id /* x */ :\n StableId,", "pub r#operation_id: StableId,", "operation_id: StableId,"]:
            with self.subTest(field=field):
                source = self.source.replace("pub struct BaoDurableAuthBusAdmission {", "pub struct BaoDurableAuthBusAdmission {\n" + field)
                with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_wrapped_raw_admission_input_rejected(self):
        source = self.source.replace("pub quota_key: StableId,", "pub metadata: BaoAuthBusAdmission,")
        with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_non_authority_metadata_and_benign_attributes_are_allowed(self):
        source = self.source.replace("pub struct BaoDurableAuthBusAdmission {", "#[non_exhaustive] pub struct BaoDurableAuthBusAdmission {\n pub request_label: Option<String>,")
        source = source.replace("impl BaoClient {", '#[allow(clippy::too_many_arguments)] impl BaoClient {')
        source = source.replace("operation: &EnteredAuthBusOperationHandle,", "request_label: &str, operation: &EnteredAuthBusOperationHandle,")
        PROJECTION.validate_bao_input_surface(source)

    def test_missing_or_wrong_sealed_handle_rejected(self):
        for replacement in ["", "operation: &StableId,", "operation_id: &EnteredAuthBusOperationHandle,", "operation: &AuthBusOperationHandle,"]:
            with self.subTest(replacement=replacement):
                source = self.source.replace("operation: &EnteredAuthBusOperationHandle,", replacement)
                with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_disabled_impl_or_method_is_not_a_sealed_entry(self):
        for source in [self.source.replace("impl BaoClient {", "#[cfg(any())] impl BaoClient {"), self.source.replace("    pub async fn consume_kv_v2_with_durable_authbus_operation", "    #[cfg(any())] pub async fn consume_kv_v2_with_durable_authbus_operation")]:
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_generic_cannot_shadow_sealed_handle_name(self):
        source = self.source.replace("E: BaoAuthBusEvidenceProvider,", "E: BaoAuthBusEvidenceProvider, EnteredAuthBusOperationHandle,")
        with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_generic_attributes_do_not_hide_authority_shadowing(self):
        source = self.source.replace("E: BaoAuthBusEvidenceProvider,", "E: BaoAuthBusEvidenceProvider, #[allow(unused)] EnteredAuthBusOperationHandle,")
        with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_known_raw_wrapper_cannot_be_added_as_parameter(self):
        for raw in ["&BaoAuthBusAdmission", "Option<BaoAuthBusAdmission>"]:
            source = self.source.replace("operation: &EnteredAuthBusOperationHandle,", "operation: &EnteredAuthBusOperationHandle, raw_admission: " + raw + ",")
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_valid_function_trait_bound_is_allowed(self):
        source = self.source.replace("E: BaoAuthBusEvidenceProvider,", "E: BaoAuthBusEvidenceProvider + Fn() -> (),")
        PROJECTION.validate_bao_input_surface(source)

    def test_raw_identifier_parameter_cannot_be_added(self):
        for argument in ["operation_id: StableId,", "mut operation_id: StableId,", "ref operation_id: StableId,", "r#operation_id: StableId,"]:
            source = self.source.replace("operation: &EnteredAuthBusOperationHandle,", "operation: &EnteredAuthBusOperationHandle,\n" + argument)
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(source)

    def test_lifetimes_mutable_bindings_and_benign_parameter_attributes(self):
        source = self.source.replace("E: BaoAuthBusEvidenceProvider,", "'a, E: BaoAuthBusEvidenceProvider,")
        source = source.replace("operation: &EnteredAuthBusOperationHandle,", "#[allow(unused_mut)] mut operation: &'a EnteredAuthBusOperationHandle,")
        PROJECTION.validate_bao_input_surface(source)

    def test_comment_and_raw_string_cannot_supply_missing_declaration(self):
        start = self.source.index("pub struct BaoDurableAuthBusAdmission {")
        end = self.source.index("\n}", start) + 2
        declaration = self.source[start:end]
        absent = self.source[:start] + "pub type BaoDurableAuthBusAdmission = BaoAuthBusAdmission;" + self.source[end:]
        for fake in ["/* " + declaration + " */", 'const SPOOF: &str = r###"' + declaration + '"###;']:
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(absent + fake)

    def test_nested_or_disabled_struct_cannot_mask_raw_admission_alias(self):
        start = self.source.index("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct BaoDurableAuthBusAdmission {")
        end = self.source.index("\n}", start) + 2
        declaration = self.source[start:end]
        absent = self.source[:start] + "pub type BaoDurableAuthBusAdmission = BaoAuthBusAdmission;" + self.source[end:]
        for decoy in ["macro_rules! unused { () => { " + declaration + " }; }", "#[cfg(any())] mod unused { " + declaration + " }", "#[cfg(any())] " + declaration, "unused!(; " + declaration + ");", "unused![; " + declaration + "];" ]:
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(absent + decoy)

    def test_optional_final_commas_are_allowed(self):
        source = self.source.replace("pub expires_at_ms: u64,\n}", "pub expires_at_ms: u64\n}")
        source = source.replace("consumer: impl FnOnce(&[u8]) -> Result<(), ()>,", "consumer: impl FnOnce(&[u8]) -> Result<(), ()>")
        PROJECTION.validate_bao_input_surface(source)

    def test_duplicate_declaration_is_not_an_allowlist(self):
        with self.assertRaises(ValueError):
            PROJECTION.validate_bao_input_surface(self.source + "\npub struct BaoDurableAuthBusAdmission {}")

    def test_unterminated_comment_or_literal_fails_closed(self):
        for suffix in ["/* unclosed", 'r###"unclosed', '"unclosed']:
            with self.assertRaises(ValueError): PROJECTION.validate_bao_input_surface(self.source + suffix)

    def test_actual_validator_retains_raw_store_and_required_marker_bans(self):
        contract = PROJECTION.load_json(ROOT / CONTRACT)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for caller in contract["callers"]:
                for name in [caller["sourcePath"], *caller["testPaths"]]:
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / name, target)
            (root / CONTRACT).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / CONTRACT, root / CONTRACT)
            with patch.object(PROJECTION, "ROOT", root), patch.object(PROJECTION, "PRODUCT_CONTRACT", root / CONTRACT):
                for malicious, expected in [(self.source + "\n// AuthBusAuthorityStore", "forbidden tokens"), (self.source.replace("validate_entered_authbus_operation", "unchecked_operation"), "missing required tokens")]:
                    (root / BAO).write_text(malicious)
                    with self.assertRaisesRegex(ValueError, expected): PROJECTION.validate_product_contract(MAPPING)

    def test_caller_mapping_drift_still_fails(self):
        with self.assertRaisesRegex(ValueError, "drift between map and contract"):
            PROJECTION.validate_product_contract({"productCallers": [{"name": "bao_kv_v2_read"}]})


if __name__ == "__main__": unittest.main()
