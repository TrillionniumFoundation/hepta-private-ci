"""Source mutations for the original Root terminal data handoff.

These check executable guards and fixed caller edges, not Rust execution,
authenticated experience, retirement, a new recipient or cold recovery.
"""

import re
import tomllib
import unittest

import test_root_historical_capture_source_closure as component


ROOT = component.ROOT
PROOF = component.PROOF
AGENT = component.AGENT
HANDOFF = component.HANDOFF
TRANSPORT = component.TRANSPORT
DEPLOYMENT = component.DEPLOYMENT
INITIAL = AGENT + "authority_host_generation_initial_transport.rs"
DATA = AGENT + "authority_host_historical_source_deployment_data.rs"
CELL = AGENT + "authority_host_historical_source_deployment_cell.rs"


def require_read_only_handoff(source):
    for name in ("open_record", "open_finalized"):
        code = component.function_code(source, name)
        if re.search(
            r"\b(?:initialize|initialize_bounded|create_pending|begin|acknowledge|"
            r"finalize_after_verified_context|compare_and_set|fence|write_all|set_len)\s*\(", code
        ):
            raise PROOF.VerificationFailure("handoff recovery must not create or confirm state")


def require_one_durable_transition_per_request(source):
    code = component.function_code(source, "exchange")
    for method in ("begin", "acknowledge", "finalize_after_verified_context", "open_finalized"):
        marker = "RootHistoricalSourceHandoffV1::" + method + "("
        if code.count(marker) != 1:
            raise PROOF.VerificationFailure("one original durable transition site required")


class RootHistoricalHandoffClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    rejects_removal = component.RootHistoricalSourceCaptureClosureTests.rejects_removal

    def check_mutation(self, path, mutate):
        component.RootHistoricalSourceCaptureClosureTests.check_mutation(self, path, mutate)
        if path == HANDOFF:
            original = (ROOT / path).read_text()
            require_read_only_handoff(original)

    def test_only_a_real_original_receipt_and_matching_pin_can_create_pending(self):
        self.rejects_removal(HANDOFF, "begin", (
            "original_root()?", "receipt.require_original_capture_session()?",
            "slot.mode != RootGenerationInitialModeV1::Reserve",
            "RootHistoricalSourcePinV1::open_existing(",
            "pin.require_original_registration(&slot.profile, config, registration)?",
            "pin.readback_digest()? != receipt.pin_digest()",
            "pin: receipt.pin_digest()", "initial_profile: slot.profile.binding.clone()",
            "publisher_epoch: registration.publisher_epoch", "publisher: CognitiveCheckpointPeerLifetime {",
            "target: slot.profile.deployment.target.clone()", "phase: HandoffPhase::Pending",
        ))
        self.rejects_removal(component.PIN, "require_original_registration", (
            "self.readback_digest()?", "pin.initial_profile != profile.binding",
            "pin.identity != profile.identity", "pin.writer != profile.writer",
            "pin.target != profile.deployment.target", "pin.target_files != profile.target_files",
            "pin.publisher_epoch != registration.publisher_epoch", "pin.publisher",
            "uid: config.peer_uid", "pid: registration.peer_pid",
            "process_start_ticks: registration.process_start_ticks",
        ))

    def test_missing_pending_fenced_and_wrong_pin_cannot_be_recovered_as_finalized(self):
        self.rejects_removal(HANDOFF, "open_record", (
            "original_root()?", "HostAuthorityFrontierStore::open(root, owner.clone())",
            "store.load(&owner)", "expected.schema != 1", "expected.purpose != HANDOFF_PURPOSE",
            "&expected.target != target",
        ))
        self.rejects_removal(HANDOFF, "open_finalized", (
            "retained.require_finalized()?", "RootHistoricalSourcePinV1::open_existing(root, target)?",
            "pin.readback_digest()?.to_string() != retained.expected.pin",
        ))
        self.rejects_removal(HANDOFF, "require_finalized", (
            "self.require_exact()?", "self.expected.phase != HandoffPhase::Finalized",
        ))
        original = (ROOT / HANDOFF).read_text()
        require_read_only_handoff(original)
        for name in ("open_record", "open_finalized"):
            code = component.function_code(original, name)
            start = original.index(code.split("{")[0])
            brace = original.index("{", start)
            changed = original[:brace + 1] + "\nSelf::create_pending(root, fake);" + original[brace + 1:]
            with self.subTest(function=name):
                with self.assertRaises(PROOF.VerificationFailure):
                    require_read_only_handoff(changed)

    def test_ack_is_exact_pending_cas_and_conflict_stays_poisoned(self):
        self.rejects_removal(HANDOFF, "acknowledge", (
            "self.require_exact()?", "self.expected.phase != HandoffPhase::Pending",
            "next.phase = HandoffPhase::PeerAcknowledged",
            "compare_and_set(&self.owner, &self.expected, &next)",
            "self.expected = next", "self.require_exact()",
        ))
        self.rejects_removal(HANDOFF, "require_exact", (
            "original_root()?", "if self.poisoned", "record == self.expected", "self.poisoned = true",
        ))
        self.rejects_removal(HANDOFF, "fence", (
            "self.poisoned = true", "same_binding.phase = self.expected.phase",
            "if same_binding != self.expected", "observed.phase == HandoffPhase::Fenced",
            "next.phase = HandoffPhase::Fenced", "compare_and_set(&self.owner, &observed, &next)",
        ))

    def test_terminal_requests_have_no_material_payload(self):
        for variant in ("CaptureSource", "CaptureAck"):
            with self.subTest(variant=variant):
                self.check_mutation(INITIAL, lambda source: source.replace(
                    "    " + variant + ",", "    " + variant + " { pin: String },", 1
                ))
        self.rejects_removal(TRANSPORT, "exchange", (
            "self.begun = true", "if self.acknowledged", "request.schema != 1",
            "request.purpose != SOURCE_CAPTURE_PURPOSE", "request.profile != self.slot.profile.binding",
            "request.request_id != *sequence", ".checked_add(1)", ".try_lock()", ".take()",
            "Command::CaptureSource if self.receipt.is_none()",
            "Command::CaptureAck if self.receipt.is_some()",
        ))

    def test_capture_wait_occurs_after_original_context_has_returned(self):
        self.rejects_removal(TRANSPORT, "exchange", (
            "self.with_original_context(|| Ok(()))?", "self.receipt = Some(capability.capture()?)",
            "receipt.require_original_capture_session()?", "retained.readback_digest()? != receipt.pin_digest()",
        ))
        self.rejects_removal(TRANSPORT, "with_original_context", (
            "self.service.with_initial_publication_context(", "self.owner",
            "self.slot.mode != RootGenerationInitialModeV1::Reserve", "self.slot.profile.writer != proof",
            "self.slot.profile.identity", "self.slot.require_profile()?", "self.slot.require_selection(",
            "original_initial_record(", "require_observation(self.slot, Some(&head)", "action()",
        ))

    def test_durable_ack_precedes_completion_and_failed_ack_fences_before_data(self):
        self.rejects_removal(TRANSPORT, "exchange", (
            "RootHistoricalSourceHandoffV1::begin(",
            "RootHistoricalSourceHandoffV1::acknowledge(&mut handoff)",
            "RootHistoricalSourceHandoffV1::finalize_after_verified_context(",
            "RootHistoricalSourceHandoffV1::open_finalized(", "self.acknowledged = true",
        ))
        def early_ack(source):
            source = source.replace("self.acknowledged = true;", "", 1)
            return source.replace("let result = self.with_original_context(|| {\n                    RootHistoricalSourceHandoffV1::acknowledge", "self.acknowledged = true;\n                let result = self.with_original_context(|| {\n                    RootHistoricalSourceHandoffV1::acknowledge", 1)
        self.check_mutation(TRANSPORT, early_ack)
        self.rejects_removal(TRANSPORT, "finish", (
            "if self.begun && !self.acknowledged", "RootHistoricalSourceHandoffV1::fence",
            "RootHistoricalSourcePinV1::open_existing(", "pin.fence()",
            "handoff_fence.is_err() || pin_fence.is_err()", "return Err(refused)",
        ))

    def test_peer_ack_cannot_skip_original_context_postchecks_or_durable_finalization(self):
        self.rejects_removal(HANDOFF, "finalize_after_verified_context", (
            "self.require_exact()?", "self.expected.phase != HandoffPhase::PeerAcknowledged",
            "next.phase = HandoffPhase::Finalized", "compare_and_set(&self.owner, &self.expected, &next)",
            "self.expected = next", "self.require_finalized()",
        ))
        self.check_mutation(TRANSPORT, lambda source: source.replace(
            "self.handoff = Some(handoff);\n                result?;",
            "self.handoff = Some(handoff);\n                result;", 1
        ))
        original = (ROOT / TRANSPORT).read_text()
        require_one_durable_transition_per_request(original)
        changed = original.replace("self.begun = true;", "self.begun = true;\n"
            "RootHistoricalSourceHandoffV1::finalize_after_verified_context(fake);", 1)
        with self.assertRaises(PROOF.VerificationFailure):
            require_one_durable_transition_per_request(changed)

    def test_root_deployment_retains_original_files_in_the_same_unique_runtime(self):
        self.rejects_removal(DEPLOYMENT, "enable_initial_source_capture_from_deployment", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "data.schema_version != 1",
            "data.purpose != DEPLOYMENT_PURPOSE", "OriginalFile::open_original(&data.source_journal)?",
            "OriginalFile::open_original(&data.source_witness)?", "self.registration.registered_identity.identity()?",
            "descriptor.require_metadata_unchanged()?", "journal.require_original_file()?",
            "witness.require_original_file()?", "self.enable_initial_source_capture(inputs)?",
            "Arc::ptr_eq(&source.phase, &capability.phase)", "Arc::ptr_eq(&source.end, &capability.end)",
            "retained.is_some()", "*retained = Some(capability)", "source.close()",
        ))
        self.rejects_removal(DATA, "into_inputs", (
            "self.definition.into_definition()?", "program.program_id == self.circuit.entry_program",
            "node_id: program.entry_node.clone()", "CircuitCellRegistryV1::new(self.circuit, vec![binding])",
            "TaskFlowFence::new(", "identity.agent_id.clone()", "agent_id: StableId::new(identity.agent_id.as_str())",
        ))
        self.rejects_removal(CELL, "into_definition", (
            "Generation::new(self.native.generation)", "Generation::new(runtime.generation)",
            "Generation::new(calibration.generation)", "definition.semantic_digest().map_err(io::Error::other)?",
        ))

    def test_cli_requires_the_original_initial_route_before_exposing_the_offer(self):
        path = AGENT + "bin/hepta-authority-host.rs"
        for marker in (
            "if source_deployment.is_some() && initial_deployment.is_none()",
            "prepared.enable_initial_source_capture_from_deployment(&path)?",
        ):
            with self.subTest(marker=marker):
                self.check_mutation(path, lambda source: source.replace(
                    marker, "/* " + marker + " */", 1
                ))


if __name__ == "__main__":
    unittest.main()
