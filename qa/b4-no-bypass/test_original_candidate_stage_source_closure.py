"""Keep the concrete Candidate branch on actual E/D/T and original material.

A Candidate readback is not independent B execution, a retention result, Model,
adoption or FinalUse. The original NoUpdate chain remains the shared route.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_candidate_stage_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CORE = AGENT + "cell_q24_candidate_stage_owners.rs"
INPUTS = AGENT + "cell_q24_candidate_stage_inputs.rs"
READBACK = AGENT + "cell_q24_candidate_stage_readback.rs"
EXPECTED = {
    "learning_original_no_update_stage_create": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_no_update_stage_recover": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_no_update_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_no_update_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_training_initial_connection_create": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_training_initial_connection_recover": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_material_initial_context_check": ('codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs'),
    "learning_original_candidate_initial_binding": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "root_resident_gate_effect_current": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs",),
    "learning_original_candidate_stage_create": (),
    "learning_original_candidate_stage_recover": (),
    "learning_original_candidate_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "learning_original_candidate_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "learning_original_candidate_stage_current_material": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
}


class OriginalCandidateStageClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["required"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            offset = source.index(marker, offset, end + 1)
            selected = offset
            offset += len(marker)
        self.verifies(path, source)
        changed = source[:selected] + replacement + source[selected + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_actual_candidate_and_shared_original_edges_remain_exact(self):
        paths = {
            path for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_candidate_stage.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_initial_handoff_pins_panel_profile_baseline_actor_and_original_time(self):
        for marker in (
            "OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)",
            "material.initial.request.evaluation_profile != protocol.evaluation_profile()",
            "baseline.components() != &material.initial.request.selected_bundle.components",
            "peer.peer.actor_id != material.initial.owners.trainer",
            "peer.timeout.is_zero()",
            "peer.timeout > Duration::from_secs(30)",
            "peer.lifetime.is_zero()",
            "peer.lifetime > Duration::from_secs(300)",
            "admitted_at.checked_add(peer.lifetime)",
            "OriginalCellQ24NoUpdateStageOwnersV1::from_original_streams(",
            "OriginalCellQ24NoUpdateStageOwnersV1::recover_original_streams(",
            "OriginalCellQ24TrainingCommandConnectionV1::from_original_stream(",
            "OriginalCellQ24TrainingCommandConnectionV1::recover_from_original_stream(",
            "let end = end.min(common.end)",
            "common.end = end",
            "auth::require_clock(started_at, fresh)?",
            "Instant::now() >= end",
        ):
            self.rejects(INPUTS, "fn bind(", marker)
        self.rejects(CORE, "fn from_original_streams(", "Origin::Fresh")
        self.rejects(CORE, "fn recover_original_streams(", "Origin::Recovered")
        self.rejects(CORE, "fn require_initial(", "OriginalCellQ24NoUpdateStageOwnersV1::require_initial(")
        self.rejects(CORE, "fn require_initial(", "initial.request.evaluation_profile != self.protocol.evaluation_profile()")

    def test_actual_prefix_and_candidate_pages_cannot_be_replaced_by_cached_material(self):
        source = self.code((ROOT / READBACK).read_text())
        self.assertEqual(source.count("state.read_prefix(&self.common, snapshot).await?"), 2)
        for marker in (
            "auth::require_snapshot(&self.common.material, snapshot)?",
            "snapshot.receipts.len() != 3",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)",
            "snapshot.training_no_update_v2().is_some()",
            "coordinator.candidate().ok_or(Error::WrongScope)?",
            "state.original_dataset.as_ref()",
            "state.original_training.as_ref()",
            "snapshot.receipts.get(2) != Some(training.receipt())",
            "lane.initial.take()",
            "OriginalCellQ24TrainingCommandConnectionV1::bind_original_candidate_material(",
            "OriginalCellQ24CandidateReadbackClientV1::readback(client)",
            "material.bundle() != expected_bundle",
            "material.model().components() != &expected_bundle.components",
            "material.authority() != AuthorityPosture::DENY_ALL",
        ):
            self.rejects(READBACK, "fn read_original_candidate(", marker)
        for occurrence in (0, 1):
            self.rejects(
                READBACK, "fn read_original_candidate(",
                "state.read_prefix(&self.common, snapshot).await?", occurrence=occurrence,
            )

    def test_last_root_and_source_io_precede_fresh_full_original_signature_checks(self):
        source = self.code((ROOT / READBACK).read_text())
        self.assertEqual(source.count("RootResidentLearningEffectGateV3::require_current("), 2)
        for occurrence in (0, 1):
            self.rejects(
                READBACK, "fn read_original_candidate(",
                "RootResidentLearningEffectGateV3::require_current(", occurrence=occurrence,
            )
        for marker in (
            "material.receipt() != training.receipt()",
            "material.attestation() != training.attestation()",
            "let fresh = auth::require_material(",
            "auth::require_clock(started_at, fresh)?",
            "auth::verify_prefix(&self.common.material, snapshot, &state, fresh)?",
            "material.receipt() != current.receipt()",
            "material.attestation() != current.attestation()",
            "auth::verify_receipt(",
            "attestation: material.attestation().clone()",
            "lane.retained.as_ref().is_some_and(|prior| prior != &identity)",
        ):
            self.rejects(READBACK, "fn read_original_candidate(", marker)

    def test_unknown_cancel_or_recovery_cannot_restore_dispatch_or_cached_success(self):
        for marker in (
            "if lane.failed",
            "lane.failed = true",
            "lane.retained = Some(identity)",
            "lane.failed = false",
        ):
            self.rejects(READBACK, "fn read_original_candidate(", marker)
        self.rejects(
            READBACK, "fn read_original_candidate(", "lane.failed = true",
            "lane.failed = false",
        )
        for marker in ("tokio::time::timeout_at(self.end.into()", "self.require_live_deadline()?"):
            for function in ("fn validate_recovery<'a>", "fn execute_stage<'a>", "fn receipt_attestation<'a>"):
                self.rejects(CORE, function, marker)
        self.rejects(CORE, "fn validate_recovery<'a>", "self.common.origin == Origin::Recovered")
        self.rejects(CORE, "fn execute_stage<'a>", "self.common.origin != Origin::Fresh")
        self.rejects(CORE, "fn install_fresh_resident_gate(", "OriginalCellQ24NoUpdateStageOwnersV1::install_fresh_resident_gate(")

    def test_unavailable_b_and_adoption_capabilities_cannot_become_no_update_or_authority(self):
        self.rejects(CORE, "fn execute_stage<'a>", "OriginalCellQ24CandidateStageOwnersV1::read_original_candidate(")
        self.rejects(CORE, "fn execute_stage<'a>", "snapshot.training_no_update_v2().is_none()")
        self.rejects(
            CORE, "fn execute_stage<'a>",
            "LearningIterationStageOwnerPortsV1::execute_stage(&self.common, snapshot, stage).await",
        )
        self.rejects(CORE, "fn prepare_proposal<'a>", "Err(Error::OwnerUnavailable(")
        for path, body in (
            (CORE, "fn forge() { LearningIterationObservationV1::TrainingNoUpdateV2 {}; }"),
            (CORE, "fn authority() { RootResidentLearningEffectGateV3::new(); }"),
            (READBACK, "fn cached() { read_cached(); }"),
            (READBACK, "fn effects() { execute_training(); }"),
            (INPUTS, "fn replace() { UnixStream::connect(); }"),
        ):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(path, source + "\n" + body + "\n")


if __name__ == "__main__":
    unittest.main()
