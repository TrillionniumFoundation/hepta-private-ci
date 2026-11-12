"""Original keys/files are bound to actual current Root-selected owner roles."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
FILES = AGENT + "production_post_a_q24_owners.rs"


class PostAOwnerFilesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_only_real_file_loader_calls_original_freezer(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for name in ("cell_q24_original_dataset_freeze_create", "cell_q24_original_dataset_freeze_recover",
                     "q24_historical_freeze_signing_config"):
            self.assertIn(FILES, rows[name]["product_callers"])
        for name in ("post_a_original_freeze_files", "post_a_original_stage_authorities", "post_a_original_stage_files"):
            self.assertEqual(rows[name]["product_callers"], [])
            self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])

    def test_roles_are_from_original_request_not_descriptor_fields(self):
        self.check_markers(AGENT + "root_historical_learning_trust_client.rs", "fn original_stage_authorities(", (
            "self.with_current_trust(", "&self.initial_snapshot().owners", "signer.principal_id == principal.as_str()",
            "matches.next().ok_or_else(refused)?", "matches.next().is_some()", "signer.original_signer()?",
            "require_signer_binding(role, &signer, now)",
            "select(&owners.experience, LearningEvidenceRoleV1::Observer)?",
            "select(&owners.dataset, LearningEvidenceRoleV1::Observer)?",
            "select(&owners.trainer, LearningEvidenceRoleV1::Generator)?",
            "select(&owners.selector, LearningEvidenceRoleV1::Selector)?"))

    def test_exact_key_and_actual_writer_drop_surround_original_freezer(self):
        self.check_markers(FILES, "fn open_original(", (
            "files.read(&self.key)?", "file.metadata()?.len() != 32", "file.read_exact(&mut before)?",
            "file.rewind()?", "file.read_exact(&mut after)?", "before != after",
            "key.verifying_key().to_bytes() != signer.verifying_key"))
        self.check_markers(FILES, "fn freeze_original(", (
            "original_historical_freeze_config(self.signature_lifetime_seconds)", "&config.signer",
            "config.verifier.objective_digest()", "journal.open_witness()?",
            "OriginalCellQ24DatasetFreezeOwnerV1::create(", "OriginalCellQ24DatasetFreezeOwnerV1::recover(",
            "phase\n            .authorize_and_materialize(&mut owner)", "drop(owner)"))

    def test_all_new_stage_files_are_checked_before_witnesses_initialize(self):
        for occurrence in (0, 1, 2):
            self.reject_removal(FILES, "fn into_original_inputs(", "prepared.revalidate_source()", occurrence)
        self.check_markers(FILES, "fn into_original_inputs(", (
            "self.experience\n                .open_original(", "self.dataset\n                .open_original(",
            "self.training.open(files, objective, self.mode)?", "self.training_receipt.open_original(",
            "self.local\n                .open_original(", "experience.open_witness()?", "dataset.open_witness()?",
            "training.open_witness()?", "receipts.open_witness()?", "local.open_witness()?"))

    def test_deployment_cannot_supply_current_request_or_model_bytes(self):
        path = AGENT + "production_post_a_q24_deployment.rs"
        self.check_markers(path, "fn preparation_config(", (
            "crate::LoadedCellQ24ModelV1::open_files(",
            "baseline.components() != &initial.request.selected_bundle.components",
            "baseline_bundle: initial.request.selected_bundle.digest()",
            "request: initial.request.clone()", "owners: initial.owners.clone()"))
        for occurrence in (0, 1):
            self.reject_removal(path, "fn read(",
                                "crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?", occurrence)


if __name__ == "__main__":
    unittest.main()
