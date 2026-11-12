"""Bind deferred Trainer initialization to actual original Material results.

These code mutation checks qualify exact ownership and state transitions. The
six native mechanism cases separately use the original four Material services;
neither source checks nor same-UID fixtures prove deployed external role hosts.
"""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_training_bootstrap_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
ATTENUATION = AGENT + "cell_q24_material_dataset_readback.rs"
CONNECTION = AGENT + "cell_q24_material_source_connection.rs"
MAIN = AGENT + "cell_q24_training_bootstrap.rs"
BUILD = AGENT + "cell_q24_training_bootstrap_build.rs"
SERVICE = AGENT + "cell_q24_training_bootstrap_service.rs"
EXPECTED = {
    "learning_original_dataset_readback_attenuation": (),
    "learning_original_dataset_readback_current": (SERVICE,),
    "learning_original_dataset_readback_context": (MAIN, BUILD),
    "learning_original_dataset_readback_cut": (BUILD,),
    "learning_original_material_connection_create": (),
    "learning_original_material_connection_context": (MAIN,),
    "learning_original_material_connection_dataset": (BUILD,),
    "learning_original_training_bootstrap_create": (),
    "learning_original_training_bootstrap_recover": (),
    "learning_original_training_bootstrap_serve": (),
    "learning_original_training_bootstrap_evidence": (),
    "learning_original_training_receipt_create": (BUILD,),
    "learning_original_training_receipt_recover": (BUILD,),
    "learning_source_bound_training_owner_create": (BUILD,),
    "learning_source_bound_training_owner_recover": (BUILD,),
    "learning_original_training_stage_constructor": (BUILD,),
    "learning_source_bound_training_stage_constructor": (BUILD,),
    "learning_original_training_command_owner_create": (BUILD,),
    "learning_original_training_command_owner_recover": (BUILD,),
    "learning_original_training_command_owner_evidence": (SERVICE,),
    "learning_original_training_source_current": (
        AGENT + "cell_q24_training_source_owner.rs", BUILD,
    ),
    "learning_original_remote_training_source_capture": (BUILD,),
    "learning_original_material_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_material_dataset_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "original_pinned_stream_explicit_uid": (
        AGENT + "learning_iteration_evidence_client.rs",
        AGENT + "cell_q24_material_source.rs",
        CONNECTION,
    ),
    "learning_original_owner_command_channel": ("codex-rs/hepta-agentd/src/cell_q24_training_command.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command.rs", "codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_selection_command.rs", "codex-rs/hepta-agentd/src/circuit_selection_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs", "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs",),
}


class OriginalTrainingBootstrapClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def function(self, source, marker):
        code = self.code(source)
        self.assertEqual(code.count(marker), 1)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return code[start:end + 1]

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_only_actual_bootstrap_edges_open_and_host_factories_remain_closed(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_training_bootstrap.rs"] = f"fn unexpected({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_dataset_attenuation_keeps_role_full_context_peer_and_original_window(self):
        for function, markers in (
            ("fn into_original_dataset_readback(", (
                "self.role != Role::Dataset || self.binding != binding",
                "channel.peer.check_peer_lifetime()?",
                "fresh_now < started_at",
                "wire::context_binding(&self.config, fresh_now)? != binding",
                "channel.execution_requested = true",
            )),
            ("fn readback(", ("OriginalCellQ24MaterialCommandClientV1::readback(&self.original).await",)),
            ("fn verify_original_cut(", (
                "retained.as_ref() != Some(cut)",
                "wire::authenticate_cut(&self.original.config, Role::Dataset, cut.clone(), at)?",
            )),
            ("fn require_initial_context(", (
                "self.original.role != Role::Dataset",
                "wire::context_binding(&self.original.config, at)? != self.original.binding",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(ATTENUATION, function, marker)
        source = (ROOT / ATTENUATION).read_text()
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(ATTENUATION, source.replace("original: OriginalCellQ24MaterialCommandClientV1", "pub original: OriginalCellQ24MaterialCommandClientV1", 1))

    def require_single_prebound_transport(self, source):
        code = self.code(source)
        if len(re.findall(r"\bRootObservationStream\s*::\s*from_stream_for_uid\s*\(", code)) != 1:
            raise PROOF.VerificationFailure("exactly one original transport creation required")
        binding = self.function(source, "fn bind_original_dataset(")
        if "RootObservationStream" in binding or re.search(r"\b(?:timeout|lifetime)\b", binding):
            raise PROOF.VerificationFailure("Dataset finalization cannot create or renew a transport")

    def test_source_connection_retains_initial_peer_and_never_restarts_lifetime(self):
        source = (ROOT / CONNECTION).read_text()
        self.verifies(CONNECTION, source)
        self.require_single_prebound_transport(source)
        for function, markers in (
            ("fn from_original_stream(", (
                "scope.validate_snapshot(&initial)?",
                "coordinator.snapshot() != &initial",
                "peer.pid == std::process::id()",
                "peer.actor_id != initial.owners.dataset",
                "original_owner_pidfd,\n",
                "if now()? < started_at",
            )),
            ("fn bind_original_dataset(", (
                "verify_context(&config, now()?)?",
                "self.require_initial_context(initial.snapshot(), &config.scope, &self.baseline)?",
                "transport: self.transport",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(CONNECTION, function, marker)
        for call in (
            "RootObservationStream::from_stream_for_uid();",
            "RootObservationStream /* extra */ :: from_stream_for_uid ();",
        ):
            changed = source.replace("verify_context(&config, now()?)?;", call + "\n        verify_context(&config, now()?)?;", 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.require_single_prebound_transport(changed)

    def test_actual_dataset_and_request_are_checked_before_custody_is_consumed(self):
        for marker in (
            "snapshot.request != initial.request",
            "snapshot.owners != initial.owners",
            "snapshot.receipts.len() != 2",
            "cut.attestations().len() != 2",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Training)",
            "request.require_context(&context, context.binding()?, next_request_id)?",
            "self.require_fresh_cut(cut, started_at)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(BUILD, "fn actual_context(", marker)
        self.rejects(SERVICE, "fn command_response(", "self.actual_context(&cut, &request, request_id, started_at)?")
        for marker in (
            "digest(&request.binding)?",
            "digest(&request.dataset_head)?",
            "request.operation_id != initial.request.operation_id.as_str()",
            "request.actor_id != initial.owners.trainer.as_str()",
            "request.scope_binding != self.config.material.scope.binding().to_string()",
        ):
            self.rejects(SERVICE, "fn require_initial_request(", marker)

    def test_uninitialized_or_missing_material_never_claims_a_training_status(self):
        self.rejects(SERVICE, "fn command_response(", "wire::CommandResult::ReadbackRequired", "wire::CommandResult::Missing")
        source = (ROOT / SERVICE).read_text()
        for status in ("Missing", "Pending"):
            changed = source.replace("wire::CommandResult::Unavailable", "wire::CommandResult::" + status, 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(SERVICE, changed)
        for marker in ("matches!(self.origin, Origin::Recovered)", "request.action == wire::Action::Execute",
                       "matches!(self.origin, Origin::Fresh)", "request.action == wire::Action::Readback"):
            self.rejects(SERVICE, "fn command_response(", marker)
        self.rejects(MAIN, "fn recover_original_custody(", "Origin::Recovered", "Origin::Fresh")

    def require_current_first_in_writer_lane(self, source):
        body = self.function(source, "fn build_original_owner(")
        lane = re.search(r"\bspawn_blocking\s*\(\s*move\s*\|\s*\|\s*\{", body)
        current = re.search(r"OriginalCellQ24TrainingSourceV1\s*::\s*require_current_in_lane\s*\(\s*&source\s*\)\s*\?\s*;", body)
        if lane is None or current is None or body[lane.end():current.start()].strip():
            raise PROOF.VerificationFailure("actual CURRENT must be first inside the writer lane")

    def test_writer_lane_rereads_actual_source_then_checks_time_before_either_writer(self):
        source = (ROOT / BUILD).read_text()
        self.verifies(BUILD, source)
        self.require_current_first_in_writer_lane(source)
        marker = "OriginalCellQ24TrainingSourceV1::require_current_in_lane(&source)?;"
        for replacement in ("", "// " + marker, "if true { " + marker + " }"):
            changed = source.replace(marker, replacement, 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.require_current_first_in_writer_lane(changed)
        for marker in (
            "OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(",
            "OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(",
            "at < started_at",
            "at >= material_config.initial.request.envelope.expiry_unix_seconds",
            "LearningEvidenceRoleV1::Generator",
            "Origin::Recovered => CellQ24TrainingOwnerV1::recover_from_original_source(",
            "Origin::Recovered => OriginalCellQ24TrainingReceiptOwnerV1::recover(",
        ):
            self.rejects(BUILD, "fn build_original_owner(", marker)

    def require_no_custody_rearm(self, source):
        code = self.function(source, "fn command_response(")
        for match in re.finditer(r"\bState\s*::\s*Awaiting\s*\(", code):
            tail = code[match.end():]
            if re.match(r"\s*custody\s*\)\s*=>\s*custody\s*,", tail) is None:
                raise PROOF.VerificationFailure("Awaiting may only destructure the original custody")

    def test_ready_is_retained_before_work_and_failed_initialization_never_rearms(self):
        source = (ROOT / SERVICE).read_text()
        self.verifies(SERVICE, source)
        self.require_no_custody_rearm(source)
        for marker in (
            "self.bootstrap_lane.try_acquire()",
            "std::mem::replace(&mut *state, State::Starting)",
            "State::Ready(Arc::clone(&original))",
            "State::Fenced",
        ):
            self.rejects(SERVICE, "fn command_response(", marker)
        for replacement in ("State::Awaiting(custody)", "State /* restored */ :: Awaiting (custody)"):
            changed = source.replace("State::Fenced;", replacement + ";", 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.require_no_custody_rearm(changed)
        self.rejects(SERVICE, "fn serve_evidence_readback(", ".ready()?")
        self.rejects(SERVICE, "fn ready(", "State::Fenced => Err(Error::Uncertain)")

    def test_only_original_captured_native_and_generator_enter_the_same_stage(self):
        for marker in (
            "experience_evidence: cut.attestations()[0].clone()",
            "dataset_evidence: cut.attestations()[1].clone()",
            "freeze_evidence: self.config.material.freeze_evidence.clone()",
            "capture_original_remote_cell_q24_training_source_v1(",
            "OriginalCellQ24TrainingStageV1::from_original_owners(native, receipts)",
            "SourceBoundCellQ24TrainingStageV1::from_original_stage(original)",
            "OriginalCellQ24TrainingCommandOwnerV1::from_original_stage(",
            "OriginalCellQ24TrainingCommandOwnerV1::recover_original_stage(",
        ):
            with self.subTest(marker=marker):
                self.rejects(BUILD, "fn build_original_owner(", marker)
        self.rejects(MAIN, "fn bind_original_custody(", "custody.generator_key.verifying_key().to_bytes() != config.generator.verifying_key")
        self.rejects(MAIN, "fn bind_original_custody(", "LearningEvidenceRoleV1::Generator")
        source = (ROOT / MAIN).read_text()
        changed = source.replace("dataset: Arc<OriginalCellQ24DatasetCommandReadbackV1>", "pub dataset: Arc<OriginalCellQ24DatasetCommandReadbackV1>", 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(MAIN, changed)


if __name__ == "__main__":
    unittest.main()
