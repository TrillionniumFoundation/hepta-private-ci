"""Keep ordinary Training on sealed source custody and original role owners.

These mutation checks are a regression gate, not evidence of a running loop.
The native tests separately exercise actual source withdrawal and job bytes.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_capture_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
SOURCE = AGENT + "cell_q24_training_source.rs"
OWNER = AGENT + "cell_q24_training_source_owner.rs"
NATIVE = AGENT + "cell_composed_q24_training_owner.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
STAGE = AGENT + "cell_q24_training_stage.rs"
MODEL = AGENT + "cell_q24_training_model_lane.rs"
EXPECTED = {
    "learning_original_training_source_capture": (),
    "learning_original_remote_training_source_capture": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    "learning_source_bound_training_owner_create": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    "learning_source_bound_training_owner_recover": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    **{"learning_source_bound_training_stage_" + name: () for name in (
        "attestation",
        "model_create", "model_recover", "model_commit",
    )},
    "learning_source_bound_training_stage_constructor": (AGENT + "cell_q24_training_bootstrap_build.rs",),
    "learning_source_bound_training_stage_execute": (AGENT + "cell_q24_training_command_service.rs",),
    "learning_source_bound_training_stage_readback": (AGENT + "cell_q24_training_command_service.rs",),
    "learning_source_bound_training_stage_model_readback": (AGENT + "circuit_model_selection_receipt_sources.rs",),
    "learning_original_training_source_current": (OWNER, AGENT + "cell_q24_training_bootstrap_build.rs"),
    "learning_original_training_source_inputs": (OWNER,),
    "learning_original_training_source_identity": (OWNER,),
    "learning_source_bound_training_admission": (),
    "learning_source_bound_training_live_check": (NATIVE, STAGE),
    "learning_source_bound_training_work_deadline": (NATIVE,),
}


class OriginalTrainingSourceCaptureClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_actual_original_read_edges_open_and_new_authority_stays_closed(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                extra = dict(sources)
                extra[AGENT + "unregistered_capture.rs"] = f"fn unexpected({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_live_material_and_full_original_signatures_cannot_be_detached(self):
        checks = (
            ("fn current_material(", "self.read_original_evidence(config).await?"),
            ("fn current_material(", "let before = self"),
            ("fn current_material(", "let after = self"),
            ("fn current_material(", "verify_original_evidence(config, fresh_now)?"),
            ("fn require_observations(", "config.dataset.receipts[0].evidence_digest != material.provenance_digest()"),
            ("fn require_observations(", "config.dataset.receipts[1].evidence_digest != material.provenance_digest()"),
            ("fn capture_binding(", "experience.extend_from_slice(&config.experience_evidence.signature)"),
            ("fn capture_binding(", "dataset.extend_from_slice(&config.dataset_evidence.signature)"),
            ("fn capture_original_remote_cell_q24_training_source_v1(", "OriginalCellQ24RemoteMaterialClientV1::require_source_binding("),
            ("fn read_current_material(", "OriginalCellQ24RemoteMaterialClientV1::read_current(original)"),
            ("fn capture_live_original_source(", "material.training_plan("),
        )
        for function, marker in checks:
            with self.subTest(function=function, marker=marker):
                self.rejects(SOURCE, function, marker)

    def test_source_domain_does_not_replace_frozen_data_or_original_missing(self):
        for function, marker in (
            ("fn create_from_original_source(", "source.native_inputs()?"),
            ("fn recover_from_original_source(", "source.native_inputs()?"),
            ("fn captured_job_key(", "let original = job_key(plan, batch, rule)?"),
            ("fn captured_job_key(", "source.source_capture_binding().as_array()"),
            ("fn require_original_source_capture(", "ordinary Training requires original source capture"),
            ("fn require_original_source_capture(", "self.fenced = true"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(OWNER, function, marker)
        self.rejects(BOUND, "fn from_original_stage(", "SourceLaneProof::require_original(source, &mut owners.training)?")
        self.rejects(NATIVE, "fn fit_or_readback(", "Ok(state) => return self.decode_state(state)")
        self.rejects(NATIVE, "fn fit_or_readback(", "Err(ProductEvaluationExecutionStoreErrorV1::Missing)")

    def test_existing_native_and_model_lanes_keep_live_checks_before_return(self):
        self.rejects(NATIVE, "fn fit_or_readback(", "self.require_live_source_if_captured()?")
        self.rejects(STAGE, "fn require_captured_tail_current(", "self.read_original_completion()?")
        self.rejects(STAGE, "fn require_captured_tail_current(", "self.require_retained_attestation_current(&completed)?")
        self.rejects(STAGE, "fn require_retained_attestation_current(", "super::now()")
        self.rejects(STAGE, "fn execute_training(", "training.require_live_source_if_captured()?")
        self.rejects(STAGE, "fn execute_training(", "fresh_now >= dataset.request.envelope.expiry_unix_seconds")
        for path, function in ((STAGE, "fn in_lane<"), (MODEL, "fn in_model_lane<")):
            for marker in (
                "OriginalCellQ24TrainingSourceV1::begin_source_operation(source)",
                "OriginalCellQ24TrainingSourceOperationV1::read_after_native(",
                "OriginalCellQ24TrainingSourceOperationV1::finish(operation, source)",
            ):
                with self.subTest(path=path, marker=marker):
                    self.rejects(path, function, marker)


if __name__ == "__main__":
    unittest.main()
