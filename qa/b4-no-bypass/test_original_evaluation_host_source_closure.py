"""Original Evaluator host and concrete Candidate edges retain actual custody.

These mutation gates preserve source boundaries; they are not deployment,
ordinary-task, scientific-gain or native execution evidence.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_host_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_receipt_owner.rs"
HOST = AGENT + "neuron_cell_evaluation_host.rs"
OPERATION = AGENT + "neuron_cell_evaluation_receipt_operation.rs"
FACTORY = AGENT + "neuron_cell_evaluation_host_training_readback.rs"
CONTRACT = AGENT + "neuron_cell_evaluation_host_contract.rs"
COMMAND = AGENT + "neuron_cell_evaluation_host_command.rs"
WIRE = AGENT + "neuron_cell_evaluation_host_wire.rs"
SERVICE = AGENT + "neuron_cell_evaluation_host_service.rs"
EVALUATION = AGENT + "cell_q24_candidate_stage_evaluation.rs"
CORE = AGENT + "cell_q24_candidate_stage_owners.rs"
READBACK = AGENT + "cell_q24_candidate_stage_readback.rs"
AUTH = AGENT + "authority_host_learning_resident_auth.rs"
EXPECTED = {
    "learning_original_evaluation_host_consume": (),
    "learning_original_evaluation_host_profile": (HOST, FACTORY),
    "learning_original_evaluation_host_receipt_current": ("codex-rs/hepta-agentd/src/neuron_cell_evaluation_host.rs",),
    "learning_original_evaluation_host_constructor": (OWNER, FACTORY),
    "learning_original_evaluation_host_serve": (),
    "learning_original_evaluation_connection_create": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_evaluation_connection_recover": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs",),
    "learning_original_evaluation_connection_training": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs",),
    "learning_original_evaluation_connection_recovery": (),
    "learning_original_evaluation_command_execute": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs",),
    "learning_original_evaluation_command_readback": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs",),
    "learning_original_evaluation_command_attestation": (),
}


class OriginalEvaluationHostClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
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
            selected = source.index(marker, offset, end + 1)
            offset = selected + len(marker)
        self.verifies(path, source)
        changed = source[:selected] + replacement + source[selected + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_only_actual_concrete_consumers_and_readback_edges_are_admitted(self):
        paths = {
            path for identifier in EXPECTED for path in (
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
                changed = dict(sources)
                changed[AGENT + "unregistered_evaluation_host.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_original_brand_and_all_current_reads_precede_final_full_authentication(self):
        self.rejects(OWNER, "fn create(", "host_origin: HostOrigin::FreshCreate")
        self.rejects(OWNER, "fn recover(", "host_origin: HostOrigin::ReadbackOnly")
        self.rejects(OPERATION, "fn attest_with_training<", "self.host_origin = HostOrigin::ReadbackOnly")
        for marker in (
            "receipt.training != primary.training", "receipt.scope != primary.scope",
            "receipt.plan != primary.plan",
            "receipt.signing.execution_namespace != primary.execution_namespace",
            "receipt.signing.signer.principal != primary.context.evaluator",
            "execution_requested: AtomicBool::new(readback_only)",
        ):
            self.rejects(HOST, "fn from_original_receipt_owner(", marker)
        for marker in (
            "let before = self.read_panel(training).await?",
            "before.training_evidence() != &context.training_evidence",
            "qualification: before.primary().qualification()",
            "OriginalCellEvaluationReceiptOwnerV1::attest_with_training(",
            "OriginalCellEvaluationReceiptOwnerV1::readback_with_training(",
            "let after = self.read_panel(training).await?", "if before != after",
        ):
            self.rejects(HOST, "fn read_original_completion(", marker)
        for marker in (
            "OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(",
            "self.authenticate_panel(after, current)?",
            "config.signing.verifier.require_signer_binding(",
            "contract::authenticate_receipt(",
            "self\n            .retained\n            .as_ref()\n            .is_some_and(|previous| previous != &original)",
        ):
            self.rejects(HOST, "fn finish_original_completion(", marker)
        self.rejects(HOST, "fn fence_result<T>", "self.fenced = true")
        self.rejects(OWNER, "fn require_original_host_completed(", "self.journal.read(&self.saved)? != expected")

    def test_initial_original_connection_cannot_renew_or_promote_recovery(self):
        for marker in (
            "&initial != expected.snapshot()", "peer.actor_id != initial.owners.evaluator",
            "initial.request.evaluation_profile != registration.evaluation_profile()",
            "original_owner_command_channel_v1(",
            "peer.uid,\n            original_owner_pidfd,\n            timeout,\n            lifetime",
            "require_clock(started_at, observed_at)?",
        ):
            self.rejects(COMMAND, "fn bind_initial(", marker)
        self.rejects(COMMAND, "fn recover_from_original_stream(", "Origin::ReadbackOnly")
        self.rejects(COMMAND, "fn bind_original_training(", "let origin = self.origin")
        self.rejects(COMMAND, "fn bind_recovered_training(", "Origin::ReadbackOnly")
        for marker in (
            "context.initial()? != self.initial", "context.registration != self.registration",
            "self.origin == Origin::ReadbackOnly && origin != Origin::ReadbackOnly",
            "self.channel.check_peer_lifetime()?", "let current = now()?",
            "require_clock(self.observed_at, current)?", "context.binding(current)?",
            "expected.snapshot.clone(),\n                expected.attestation.clone(),\n                current",
            "execution_requested: origin == Origin::ReadbackOnly",
        ):
            self.rejects(COMMAND, "fn finish_binding(", marker)

    def test_wrong_context_queued_cancellation_and_completed_regression_never_rearm(self):
        for marker in (
            "request.require_context(&self.context, self.binding, request_id)?",
            "self.execution_requested.swap(true, Ordering::AcqRel)",
            "wire::Outcome::ReadbackRequired", "self.original_response(wire::Action::Readback)?",
            "encoded.len() > 16_384",
        ):
            self.rejects(SERVICE, "fn command_response(", marker)
        self.rejects(COMMAND, "fn drop(", "self.0.store(true, Ordering::Release)")
        for marker in (
            "slot.take().ok_or(Error::Unavailable)?", "channel.execution_requested = true",
            "QueuedCancellation(Arc::new(AtomicBool::new(false)))",
            "action == wire::Action::Execute && queued.load(Ordering::Acquire)",
            "channel\n                .peer\n                .request(&encoded)", "response.require_request(&request)?",
            "channel.peer.check_peer_lifetime()?", "self.context.authenticate(current)?",
            "retained.as_ref().is_some_and(|saved| saved != &original)",
            "wire::Outcome::Missing | wire::Outcome::Pending",
            "self\n                    .retained\n                    .try_lock()\n                    .map_err(|_| Error::Unavailable)?\n                    .is_some()",
            "wire::Outcome::Uncertain => return Err(Error::CommitUncertain)",
        ):
            self.rejects(COMMAND, "fn exchange(", marker)
        for marker in (
            "self.schema != 1", "self.purpose != PURPOSE", "self.binding != binding.to_string()",
            "self.training_head != context.training.head_digest.to_string()",
            "self.evaluator != context.training.owners.evaluator.as_str()",
        ):
            self.rejects(WIRE, "fn require_context(", marker)
        for marker in (
            "snapshot.receipts.len() != context.training.receipts.len() + 1",
            "!snapshot.receipts.starts_with(&context.training.receipts)",
            "result.snapshot != snapshot",
        ):
            self.rejects(WIRE, "fn authenticate_completed(", marker)

    def test_readonly_and_future_cut_do_not_turn_into_fresh_dispatch(self):
        self.rejects(CORE, "fn validate_recovery<'a>", "self.read_original_evaluation(snapshot).await?")
        self.rejects(CORE, "fn validate_recovery<'a>", "snapshot.receipts.len() != 4")
        self.rejects(EVALUATION, "fn read_original_evaluation(", "Action::Readback")
        for marker in (
            "self.common.origin != Origin::Fresh", "snapshot.receipts.len() != 3",
            "self.original_evaluation(snapshot, Action::Execute).await?",
        ):
            self.rejects(EVALUATION, "fn execute_original_evaluation(", marker)
        for occurrence in (0, 1):
            self.rejects(
                READBACK, "fn read_original_candidate(",
                "if mode == CandidateRead::Dispatch", occurrence=occurrence,
            )
        for marker in (
            "lane.failed = true", "CandidateRead::Dispatch", "CandidateRead::Readback",
            "lane.initial.take()", "OriginalCellEvaluationCommandConnectionV1::bind_original_training(",
            "OriginalCellEvaluationCommandClientV1::execute_evaluation(client).await",
            "OriginalCellEvaluationCommandClientV1::readback(client).await",
            "before.heads() != after.heads()",
            "self.verify_original_evaluation(snapshot, &training_cut, &training, &original, fresh)?",
            "lane\n            .retained\n            .as_ref()\n            .is_some_and(|saved| saved != &original)",
        ):
            self.rejects(EVALUATION, "fn original_evaluation(", marker)
        for occurrence in (0, 1, 2):
            self.rejects(
                EVALUATION, "fn original_evaluation(",
                "gate,\n                &training_cut,\n                &self.common.material.scope",
                "gate,\n                snapshot,\n                &self.common.material.scope", occurrence=occurrence,
            )

    def test_full_evaluator_role_payload_and_original_generator_separation_remain_required(self):
        for marker in (
            "receipt.observed_unix_seconds > signed.issued_at",
            "*candidate_bundle == candidate",
            "*evaluation_profile == context.registration.evaluation_profile()",
            "LearningEvidenceRoleV1::Evaluator,\n        &signed",
            "learning_iteration_receipt_signing_bytes_v1(&receipt)?",
            "verify_signed_actor_separation(&generator, &evaluator, current)?",
        ):
            self.rejects(CONTRACT, "fn authenticate_receipt(", marker)
        for marker in (
            "original.training_attestation() != training.attestation()",
            "original.authority() != AuthorityPosture::DENY_ALL",
            "supplied\n                .receipts\n                .get(3)\n                .is_some_and(|saved| saved != receipt)",
            "*evaluation_profile == self.protocol.evaluation_profile()",
            "LearningEvidenceRoleV1::Evaluator,\n                signed",
            "verify_signed_actor_separation(&generator, &evaluator, current)",
        ):
            self.rejects(EVALUATION, "fn verify_original_evaluation(", marker)
        for marker in (
            "LearningIterationStageV1::Proposal =>",
            "snapshot.receipts.get(3) != Some(receipt)",
            "*candidate_bundle == candidate",
            "*evaluation_profile == profile.initial.request.evaluation_profile",
            "LearningEvidenceRoleV1::Evaluator",
            "LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training]",
            "verify_signed_actor_separation(&previous.1, current, now)",
        ):
            self.rejects(AUTH, "fn verify_non_model_attestations(", marker)
        for path, addition in (
            (HOST, "fn bypass() { SigningKey::generate(); }"),
            (COMMAND, "fn reconnect() { UnixStream::connect(); }"),
            (EVALUATION, "fn adopt() { publish(); }"),
            (WIRE, "struct CallerRows { pub rows: Vec<Row> }"),
        ):
            source = (ROOT / path).read_text()
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(path, source + "\n" + addition + "\n")


if __name__ == "__main__":
    unittest.main()
