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
            self.assertEqual(rows[name]["product_callers"], [AGENT + "production_post_a_q24.rs"])
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
        for occurrence in (0, 1):
            self.reject_removal(FILES, "fn into_original_inputs(",
                                "OriginalPreparedReadV1::require_prepared(read, &prepared)", occurrence)
        self.check_markers(FILES, "fn into_original_inputs(", (
            ".with_original_prepared_operation(", "self.experience.open_original(",
            "self.dataset.open_original(",
            "JournalData::open(&self.training, files, objective, self.mode)?",
            "self.training_receipt.open_original(", "self.local\n                        .open_original(",
            ".map_err(refused)??;", "experience.open_witness()?", "dataset.open_witness()?",
            "training.open_witness()?", "receipts.open_witness()?", "local.open_witness()?",
            "prepared.revalidate_source()"))

    def test_stage_operation_cannot_initialize_a_witness_before_physical_postread(self):
        def check(source):
            code = component.PROOF._strip_rust_non_code(source)
            start = code.index("fn into_original_inputs(")
            end = component.PROOF._rust_item_end(code, start)
            self.assertIsNotNone(end)
            body = code[start:end + 1]
            self.assertEqual(body.count(".with_original_prepared_operation("), 1)
            self.assertEqual(body.count(".map_err(refused)??;"), 1)
            before, after = body.split(".map_err(refused)??;")
            self.assertEqual(before.count(
                "OriginalPreparedReadV1::require_prepared(read, &prepared)"), 2)
            self.assertNotIn(".open_witness(", before)
            self.assertEqual(after.count(".open_witness()?"), 5)
            self.assertEqual(after.count("prepared.revalidate_source()"), 1)
            self.assertLess(after.rindex(".open_witness()?"),
                            after.index("prepared.revalidate_source()"))
        source = (ROOT / FILES).read_text()
        check(source)
        marker = "                Ok(("
        self.assertEqual(source.count(marker), 1)
        for mutation in (
            source.replace(marker, "                experience.open_witness()?;\n" + marker, 1),
            source.replace(".map_err(refused)??;", ".map_err(refused)?;", 1),
            source.replace("prepared.revalidate_source().map_err(refused)?;", "", 1),
        ):
            with self.subTest(mutation=mutation != source):
                with self.assertRaises(AssertionError):
                    check(mutation)

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
