"""Source-only closure for original evaluated-retention Observer receipts.

These adversarial mutations protect the original five/six cuts, live T/B/S,
last actual Source/Cell observation, readonly Selector service and permanent
recovery attenuation. They do not qualify an ordinary daemon/Root loop.
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
    "evaluated_next_use_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "circuit_next_use_receipt_owner.rs"
BINDING = AGENT + "circuit_next_use_receipt_binding.rs"
EVALUATED = AGENT + "circuit_evaluated_next_use_receipt.rs"
SELECTION = AGENT + "circuit_evaluated_selection_receipt.rs"
CONTEXT = AGENT + "circuit_evaluated_retention_context.rs"
HOST = AGENT + "circuit_evaluated_selection_readback_owner.rs"
CLIENT = AGENT + "learning_iteration_evidence_client.rs"
COMMAND = AGENT + "circuit_next_use_command.rs"
NATIVE = AGENT + "circuit_evaluated_next_use_receipt_tests.rs"
BOUNDARIES = {
    "learning_original_evaluated_next_use_create": (),
    "learning_original_evaluated_next_use_recover": (),
    "learning_original_evaluated_next_use_attest": (),
    "learning_original_evaluated_next_use_readback": (),
    "learning_original_evaluated_selection_readback_transfer": (),
    "learning_original_evaluated_selection_readback_factory": (SELECTION,),
    "learning_original_evaluated_selection_readback_serve": (),
    "learning_original_evaluated_selection_readback": (HOST,),
}


def code(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


def bounds(source, function):
    masked = code(source)
    assert masked.count(function) == 1, function
    start = masked.index(function)
    end = PROOF._rust_item_end(masked, start)
    assert end is not None
    return start, end + 1


def locate(source, needle, start=0, end=None, occurrence=0):
    """Only layout is ignored; mutation replaces the actual audited span."""
    end = len(source) if end is None else end
    positions = [i for i in range(start, end) if not source[i].isspace()]
    compact = "".join(source[i] for i in positions)
    wanted = re.sub(r"\s+", "", needle)
    matches = list(re.finditer(re.escape(wanted), compact))
    assert len(matches) > occurrence, (needle, len(matches), occurrence)
    offset = matches[occurrence].start()
    return positions[offset], positions[offset + len(wanted) - 1] + 1


class EvaluatedNextUseClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        begin, end = bounds(source, function)
        start, stop = locate(source, marker, begin, end, occurrence)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, function, marker)):
            self.verifies(path, source[:start] + replacement + source[stop:])

    def rejects_hidden(self, path, function, marker, occurrence=0, asynchronous=False):
        source = (ROOT / path).read_text()
        begin, end = bounds(source, function)
        start, _ = locate(source, marker, begin, end, occurrence)
        stop = PROOF._rust_item_end(code(source), start)
        self.assertIsNotNone(stop)
        original = source[start:stop + 1]
        if asynchronous:
            wrapped = "let _ = async {\n" + original + "\nOk::<(), Error>(())\n};"
        else:
            wrapped = "let _ = || -> Result<(), Error> {\n" + original + "\nOk(())\n};"
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, marker)):
            self.verifies(path, source[:start] + wrapped + source[stop + 1:])


    def test_opaque_result_and_readonly_host_custody_fields_cannot_become_writable(self):
        profiles = (
            (EVALUATED, "pub struct OriginalCircuitEvaluatedNextUseReceiptV1 {",
             ("selection", "snapshot", "receipt", "attestation")),
            (HOST, "pub struct OriginalCircuitEvaluatedSelectionReadbackOwnerV1<",
             ("owner", "cell", "trainer", "evaluator", "selection", "initial_head",
              "binding", "runtime", "connections")),
        )
        for path, declaration, fields in profiles:
            source = (ROOT / path).read_text()
            start, stop = bounds(source, declaration)
            body = source[start:stop]
            self.verifies(path, source)
            for field in fields:
                marker = "    " + field + ":"
                self.assertEqual(body.count(marker), 1, (path, field))
                for visibility in ("pub", "pub(crate)", "pub(super)"):
                    with self.subTest(path=path, field=field, visibility=visibility):
                        changed_body = body.replace(
                            marker, "    " + visibility + " " + field + ":", 1
                        )
                        changed = source[:start] + changed_body + source[stop:]
                        with self.assertRaises(PROOF.VerificationFailure):
                            self.verifies(path, changed)
                        # The old private declaration in a comment cannot
                        # stand in for the actual now-writable capability.
                        with self.assertRaises(PROOF.VerificationFailure):
                            self.verifies(path, changed + "\n/*\n" + body + "\n*/\n")

    def test_all_complete_product_rows_remain_valid(self):
        for path in (OWNER, BINDING, EVALUATED, SELECTION, CONTEXT, HOST, CLIENT, COMMAND):
            with self.subTest(path=path):
                self.verifies(path, (ROOT / path).read_text())

    def test_actual_readonly_calls_are_closed_and_no_effect_caller_is_claimed(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        sources = {path: code((ROOT / path).read_text())
                   for path in (OWNER, EVALUATED, SELECTION, HOST, CLIENT)}
        for identifier, expected in BOUNDARIES.items():
            with self.subTest(identifier=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, inventory)
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[1]
                for call in (f"owner.{method}()", row.symbol + "()"):
                    changed = dict(sources)
                    changed[AGENT + "unregistered_evaluated_c.rs"] = (
                        f"fn unexpected(owner: &{row.receiver_type}) {{ {call}; }}"
                    )
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, changed, ())
        row = self.boundaries["circuit_feature_original_next_use_observation"]
        self.assertEqual(row.product_callers, (
            OWNER, EVALUATED,
        ))
        sources = {path: code((ROOT / path).read_text())
                   for path in (row.definition_path, *row.product_callers)}
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[AGENT + "unregistered_evaluated_cell.rs"] = (
            "fn unexpected(cell: &PublishedCircuitCellOwnerV1) { cell.read_learning_next_use(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_recovery_permanently_attenuates_fresh_s_and_never_claims_missing_c(self):
        for path, function, marker in (
            (SELECTION, "fn into_original_receipt_readback(", "self.context = self.context.into_original_receipt_readback();"),
            (CONTEXT, "fn into_original_receipt_readback(", "self.origin = Origin::Readback;"),
            (EVALUATED, "fn from_evaluated_custody(", "CommandOrigin::Recovered => config.selection.into_original_receipt_readback()"),
            (EVALUATED, "fn recover_evaluated(", "CommandOrigin::Recovered"),
            (EVALUATED, "fn from_evaluated_custody(", "LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?"),
            (EVALUATED, "fn attest_original_evaluated_completion(", "CommandOrigin::Recovered => self.readback_source(source).await?"),
            (EVALUATED, "fn readback_evaluated_completion(", "self.readback_source(source).await?"),
            (EVALUATED, "fn completed_evaluated_next_use(", "selection: selection.clone()"),
            (OWNER, "fn readback_source(", "let bytes = self.journal.read(&self.saved)?;"),
        ):
            self.rejects(path, function, marker)
        self.rejects(EVALUATED, "fn attest_original_evaluated_completion(",
                     "CommandOrigin::Recovered => self.readback_source(source).await?",
                     "CommandOrigin::Recovered => self.attest_source(source).await?")
        self.rejects(EVALUATED, "fn from_evaluated_custody(",
                     "config.selection.into_original_receipt_readback()", "config.selection")
        self.rejects(CONTEXT, "fn into_original_receipt_readback(", "Origin::Readback", "Origin::Fresh")

    def test_new_work_checks_cannot_be_deferred_into_uninvoked_closures(self):
        for path, function, marker in (
            (EVALUATED, "fn require_new(", "if let Self::Evaluated(selection) = self"),
            (EVALUATED, "fn from_evaluated_custody(", "if matches!(&command_origin, CommandOrigin::FreshCreate)"),
            (EVALUATED, "fn from_evaluated_custody(", "if key.verifying_key().to_bytes() != config.signer.verifying_key"),
            (OWNER, "fn prepare(", "if source.snapshot().request != self.config.selection.request"),
            (EVALUATED, "fn authenticate_predecessors(", "if selection.snapshot() != &config.selection"),
            (SELECTION, "fn original_receipt_predecessors(", "if original.snapshot() != &self.snapshot"),
            (HOST, "fn from_original_receipt_owner(", "if config.decision != *selection.original_context().snapshot()"),
            (HOST, "fn evidence_response(", "if request.schema != 1"),
            (HOST, "fn evidence_response(", "if current < started_at"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects_hidden(path, function, marker)

    def test_private_source_profile_prevents_legacy_or_remote_downgrade(self):
        self.rejects(OWNER, "fn prepare(", "(Profile::Evaluated(_), ObservationLocation::EvaluatedOwner)",
                     "(Profile::Evaluated(_), ObservationLocation::LocalOwner)")
        self.rejects(OWNER, "fn prepare(", "match (&self.profile, source.location())")
        self.rejects(EVALUATED, "fn location(", "ObservationLocation::EvaluatedOwner", "ObservationLocation::RemoteOwner")
        self.rejects(EVALUATED, "fn evaluated_owners(", "Some((self.trainer, self.evaluator))", "None")
        for function in ("fn create(", "fn recover("):
            self.rejects(OWNER, function, "profile: Profile::Legacy")

    def test_full_original_s_cut_and_signature_cannot_be_replaced_by_metadata(self):
        for marker in (
            "self.context.original_receipt_predecessors(current)?", "self.context.receipt_configuration()",
            "LearningIterationCoordinatorV1::from_snapshot(self.context.snapshot().clone())?",
            "original.record(self.receipt.clone(), self.receipt.observed_unix_seconds)?",
            "scope.validate_snapshot(&self.snapshot)?", "original.snapshot() != &self.snapshot",
            "self.snapshot.receipts.len() != 5", "original.next_stage() != Some(LearningIterationStageV1::NextUse)",
            "self.receipt.actor_id != self.snapshot.owners.selector", "self.receipt.observed_unix_seconds > self.attestation.issued_at",
            "self.attestation.issued_at > current", "verifier.verify(", "LearningEvidenceRoleV1::Selector",
            "&learning_iteration_receipt_signing_bytes_v1(&self.receipt)?",
            "selection.principal().principal_id != self.receipt.actor_id",
            "verify_signed_actor_separation(&training, &selection, current)?",
            "verify_signed_actor_separation(&evaluation, &selection, current)?",
        ):
            self.rejects(SELECTION, "fn original_receipt_predecessors(", marker)
        for before, after in (("receipts.len() != 5", "receipts.len() != 4"),
                              ("original.snapshot() != &self.snapshot", "original.snapshot() == &self.snapshot")):
            self.rejects(SELECTION, "fn original_receipt_predecessors(", before, after)

    def test_c_full_same_prefix_is_checked_before_readonly_s_io(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(source.snapshot().clone())?",
            "self.config.scope.validate_snapshot(source.snapshot())?",
            "source.snapshot().request != self.config.selection.request",
            "source.snapshot().owners != self.config.selection.owners",
            ".starts_with(&self.config.selection.receipts)",
            'OwnerError::Binding("original Selection prefix")',
        ):
            self.rejects(OWNER, "fn prepare(", marker)
        self.rejects(OWNER, "fn prepare(", ".starts_with(&self.config.selection.receipts)",
                     ".ends_with(&self.config.selection.receipts)")
        self.rejects(OWNER, "fn attest_source(",
                     "source.snapshot().receipts.len() > self.config.selection.receipts.len()",
                     "source.snapshot().receipts.len() < self.config.selection.receipts.len()")
        self.rejects(EVALUATED, "fn completed_evaluated_next_use(", "coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?")

    def test_both_live_predecessors_and_readonly_original_s_are_mandatory(self):
        for marker in (
            "let training = match &self.profile", "Profile::Legacy =>",
            "let trainer: &LearningIterationEvidenceClientV1 = source.trainer()",
            '.ok_or(OwnerError::Binding("original C Trainer source"))?',
            "LearningIterationEvidenceClientV1::readback(trainer,",
            "prior(&self.config, LearningIterationStageV1::Training)?",
            "Profile::Evaluated(selection) =>", "source.evaluated_owners()",
            ".require_original_receipt_owners(trainer, evaluator)",
            "let selector: &LearningIterationEvidenceClientV1 = source.selector();",
            ".readback(source.snapshot(), prior(&self.config, LearningIterationStageV1::Selection)?,)",
            "Ok([training, selection])",
        ):
            self.rejects(OWNER, "fn predecessors(", marker)
        for marker in ("OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?",
                       "if training != self.training", "OriginalCellEvaluationCommandClientV1::readback(evaluator).await?",
                       "if evaluation != self.evaluation"):
            self.rejects(CONTEXT, "fn require_current(", marker)

    def test_final_source_cell_fence_follows_every_awaited_t_b_s_response(self):
        for marker in ("ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner =>",
                       "let evidence = self.predecessors(source).await?;",
                       "if self.prepare(source).await? != *observed", "if self.journal.read(&self.saved)? != bytes"):
            self.rejects(OWNER, "fn finish_original_readback(", marker)
        self.rejects_hidden(OWNER, "fn finish_original_readback(",
                            "if self.prepare(source).await? != *observed", asynchronous=True)
        source = (ROOT / OWNER).read_text()
        begin, end = bounds(source, "fn finish_original_readback(")
        first_start, first_end = locate(source, "let evidence = self.predecessors(source).await?;", begin, end)
        second_start, _ = locate(source, "if self.prepare(source).await? != *observed", first_end, end)
        second_end = PROOF._rust_item_end(code(source), second_start) + 1
        changed = (source[:first_start] + source[second_start:second_end]
                   + source[first_end:second_start] + source[first_start:first_end] + source[second_end:])
        self.verifies(OWNER, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(OWNER, changed)
        for marker in ("LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?",
                       "self.cell.read_learning_next_use(&coordinator, self.source, self.identity)"):
            self.rejects(EVALUATED, "fn observe(", marker)

    def test_claim_and_readback_failures_keep_fence_and_original_journal(self):
        for function in ("fn attest_source(", "fn readback_source("):
            for marker in ("if self.completion_fenced", "let result = self", ".finish_original_readback(",
                           "if result.is_err()", "self.completion_fenced = true;"):
                self.rejects(OWNER, function, marker)
            self.rejects(OWNER, function, "if result.is_err()", "if result.is_ok()")
        for marker in ("ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner",
                       "let before = self.predecessors(&source).await?;",
                       "evaluated::authenticate_predecessors(&self.config, &self.profile, &before, now()?)?"):
            self.rejects(OWNER, "fn readback_source(", marker)
        for marker in ("learning_owner_evidence::decode(bytes)?", "signed.issued_at",
                       "payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?",
                       ".get(self.config.selection.receipts.len())", ".is_some_and(|saved| saved != &receipt)"):
            self.rejects(OWNER, "fn decode_completed(", marker)

    def test_all_t_b_s_and_observer_roles_remain_independent_and_current(self):
        for marker in ("scope.binding() != config.scope.binding()", "verifier.trust_digest() != config.verifier.trust_digest()",
                       "verifier.scope_digest() != config.verifier.scope_digest()", "verifier.objective_digest() != config.verifier.objective_digest()",
                       "training != config.training_evidence", "selection.attestation() != &config.selection_evidence",
                       "evidence != &[config.training_evidence.clone(), config.selection_evidence.clone(),]",
                       "config.verifier.require_signer_binding(", "LearningEvidenceRoleV1::Observer",
                       "selection.original_receipt_predecessors(current)?", "for original in &originals",
                       "verify_independent_roles(original.principal(), &config.signer.principal, current)",
                       "original.controller_id() == &config.signer.controller_id"):
            self.rejects(EVALUATED, "fn authenticate_predecessors(", marker)
        for marker in ("selection.original_receipt_predecessors(current)?",
                       "verify_signed_actor_separation(&predecessor, signed, current)?"):
            self.rejects(EVALUATED, "fn require_signed_separation(", marker)
        self.rejects_hidden(EVALUATED, "fn require_signed_separation(", "if let Self::Evaluated(selection) = self")
        for function, marker in (("fn attest_source(", ".require_signed_separation(&verified, issued_at)"),
                                 ("fn authenticate_completed(", "self.profile.require_signed_separation(&verified, current)?"),
                                 ("fn authenticate_completed(", "if current < started_at")):
            self.rejects(OWNER, function, marker)

    def test_bindings_include_full_original_t_b_s_and_no_timestamp_refresh(self):
        for marker in ("self.context.receipt_context_binding().as_array()", "self.snapshot.head_digest.as_array()",
                       "&self.attestation.signing_bytes()", "&self.attestation.signature"):
            self.rejects(SELECTION, "fn original_receipt_binding(", marker)
        for marker in ("&self.training.attestation().signing_bytes()", "&self.training.attestation().signature",
                       "&self.evaluation.attestation().signing_bytes()", "&self.evaluation.attestation().signature"):
            self.rejects(CONTEXT, "fn receipt_context_binding(", marker)
        for marker in ("selection.original_receipt_binding()", "binding.as_array()", "&config.signer.verifying_key",
                       "&config.maximum_signature_lifetime_seconds.to_be_bytes()"):
            self.rejects(EVALUATED, "fn from_evaluated_custody(", marker)
        for marker in ("self.profile.require_new(started_at)?", "profile.require_new(issued_at)?",
                       "require_new_attestation(config, started_at, issued_at)?"):
            self.rejects(OWNER, "fn attest_source(", marker)
        self.rejects(BINDING, "fn require_new_attestation(", "current >= config.selection.request.envelope.expiry_unix_seconds")

    def test_private_receipt_helper_accepts_only_actual_retained_c(self):
        function = "pub(super) fn receipt("
        self.rejects(EVALUATED, function, "let Profile::Evaluated(_) = profile else")
        self.rejects(EVALUATED, function, "LearningIterationObservationV1::RetainedModelNextUse { .. }",
                     "LearningIterationObservationV1::NextUse { .. }")
        self.rejects_hidden(EVALUATED, function, "if !matches!(")
        for marker in ("if committed.is_zero()", "predecessor: config.selection.head_digest",
                       "actor_id: config.selection.owners.next_use_observer.clone()",
                       "coordinator.record(receipt.clone(), observed_unix_seconds)?",
                       "config.scope.validate_snapshot(coordinator.snapshot())?"):
            self.rejects(BINDING, "fn receipt_with_domain(", marker)

    def test_generic_transfer_and_duplicate_receipt_name_guards_are_top_level(self):
        # The unchanged manifest scanner accepts unique fn name( only. These
        # two bodies are therefore frozen as complete actual-code sequences,
        # and their essential checks are also verified directly at depth one.
        for path, function, marker in (
            (SELECTION, "fn into_evaluated_readback_owner<", "if context.receipt_context_binding()"),
            (EVALUATED, "pub(super) fn receipt(", "if !matches!("),
        ):
            source = (ROOT / path).read_text()
            start, end = bounds(source, function)
            masked = code(source)
            guard, _ = locate(masked, marker, start, end)
            prefix = masked[start:guard]
            self.assertEqual(prefix.count("{") - prefix.count("}"), 1)
            self.rejects_hidden(path, function, marker)

    def test_distinct_signature_domains_are_actual_code_and_not_comment_decoys(self):
        domains = (
            (SELECTION, "fn original_receipt_binding(",
             r'b"hepta.agentd.original-evaluated-selection-receipt-context.v1\0"'),
            (EVALUATED, "fn from_evaluated_custody(",
             r'b"hepta.agentd.original-circuit-evaluated-next-use-receipt.v1\0"'),
            (EVALUATED, "pub(super) fn receipt(",
             r'b"hepta.agentd.original-circuit-evaluated-next-use-evidence.v1\0"'),
            (BINDING, "fn receipt(",
             r'b"hepta.agentd.original-circuit-next-use-evidence.v1\0"'),
            (BINDING, "fn evidence_id(",
             'format!("original-circuit-next-use:{identity}")'),
        )

        def actual_literal(source, function, literal):
            start, end = bounds(source, function)
            masked = code(source)
            expected = PROOF._strip_rust_non_code(literal)
            self.assertTrue(expected.strip())
            locations = [match.start() + start for match in
                         re.finditer(re.escape(literal), source[start:end])]
            actual = [offset for offset in locations
                      if masked[offset:offset + len(literal)] == expected]
            self.assertEqual(len(actual), 1)

        for path, function, literal in domains:
            with self.subTest(path=path, literal=literal):
                source = (ROOT / path).read_text()
                actual_literal(source, function, literal)
                start, end = bounds(source, function)
                offset = source.index(literal, start, end)
                rewritten = literal.replace("original-", "wrong-", 1)
                # Retain the raw required marker as a comment in the same
                # function; only the real byte-string/call must count.
                changed = (source[:offset] + rewritten + " /* " + literal + " */"
                           + source[offset + len(literal):])
                with self.assertRaises(AssertionError):
                    actual_literal(changed, function, literal)

    def test_host_fixed_context_cannot_be_swapped_or_faked_by_future_head(self):
        for marker in ("selection.original_receipt_predecessors(now()?)?", "owner.original_command_profile()",
                       "config.decision != *selection.original_context().snapshot()", "config.scope.binding() != scope.binding()",
                       "config.verifier.trust_digest() != verifier.trust_digest()", "config.verifier.scope_digest() != verifier.scope_digest()",
                       "config.verifier.objective_digest() != verifier.objective_digest()", "config.training_evidence != training",
                       "config.signer.principal.principal_id != selection.receipt().actor_id",
                       "selection.snapshot().request.clone()", "selection.snapshot().owners.clone()",
                       "initial_head: initial.snapshot().head_digest", "selection.original_receipt_binding()"):
            self.rejects(HOST, "fn from_original_receipt_owner(", marker)
        for marker in ("let Profile::Evaluated(context) = &self.profile else",
                       "context.receipt_context_binding() != selection.original_context().receipt_context_binding()",
                       "self.config.decision != *selection.original_context().snapshot()",
                       "self.config.signer.principal.principal_id != selection.receipt().actor_id",
                       "self, selection, cell, trainer, evaluator,"):
            self.rejects(SELECTION, "fn into_evaluated_readback_owner<", marker)
        self.rejects_hidden(SELECTION, "fn into_evaluated_readback_owner<", "if context.receipt_context_binding()")

    def test_host_checks_each_correlated_readonly_request_before_original_io(self):
        for marker in ("request.schema != 1", "request.operation != wire::OPERATION", "request.request_id != request_id",
                       "!(1..=128).contains(&request_id)", "request.binding != self.initial_head.to_string()",
                       "request.operation_id != self.selection.snapshot().request.operation_id.as_str()",
                       "request.actor_id != self.selection.snapshot().owners.selector.as_str()",
                       "request.predecessor != self.selection.receipt().predecessor.to_string()",
                       "request.receipt_digest != self.selection.attestation().payload_digest.to_string()",
                       "snapshot_head.is_zero()", "request.snapshot_head != snapshot_head.to_string()",
                       "self.selection.original_receipt_predecessors(started_at)?",
                       "OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_selection("):
            self.rejects(HOST, "fn evidence_response(", marker)
        self.rejects(HOST, "fn evidence_response(", "request.operation != wire::OPERATION", "request.operation == wire::OPERATION")
        self.rejects(HOST, "fn evidence_response(", "request.binding != self.initial_head.to_string()",
                     "request.binding != request.snapshot_head")

    def test_host_response_is_exact_original_s_and_never_new_signing(self):
        for marker in ("snapshot: self.selection.snapshot()", "cell: &self.cell", "trainer: &self.trainer", "evaluator: &self.evaluator",
                       "original.original_receipt_predecessors(current)?", "current < started_at",
                       "original.snapshot() != self.selection.snapshot()", "original.receipt() != self.selection.receipt()",
                       "original.attestation() != self.selection.attestation()", "original.original_receipt_binding() != self.binding",
                       "wire::Evidence::from_original(original.attestation())"):
            self.rejects(HOST, "fn evidence_response(", marker)
        source = (ROOT / HOST).read_text()
        for marker in ("SigningKey", "UnixStream::connect(", "File::open(", "attest_original_evaluated_selection(",
                       "attest_source(", "commit_once(", "sign_original(", "execute(", "serve_execute(", "pub owner:"):
            with self.subTest(marker=marker), self.assertRaises(PROOF.VerificationFailure):
                self.verifies(HOST, source + "\n" + marker + "\n")
        self.assertEqual(re.findall(r"\bpub\s+(?:async\s+)?fn\s+(\w+)", code(source)), ["serve_readback"])

    def test_host_keeps_original_custody_session_and_finite_exchange_budgets(self):
        for marker in ("timeout.is_zero()", "timeout > Duration::from_millis(500)", ".try_acquire_owned()",
                       "tokio::task::spawn_blocking(", "original_owner_command_channel_v1(",
                       "stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,"):
            self.rejects(HOST, "fn serve_readback(", marker)
        self.rejects_hidden(HOST, "fn serve_readback(", "if timeout.is_zero()")
        self.rejects(HOST, "fn from_original_receipt_owner(", "Semaphore::new(4)", "Semaphore::new(128)")
        self.rejects(HOST, "fn serve_channel(", "1..=128_u64", "1..=u64::MAX")
        self.rejects(HOST, "fn serve_channel(", "self.evidence_response(bytes, request_id)")

    def test_mechanical_binding_extraction_preserves_legacy_profile_and_commands(self):
        for function in ("fn create(", "fn recover("):
            self.rejects(OWNER, function, "validate_config(&config, &key)?")
        for marker in ("if config.selection.receipts.len() == 5", "&& coordinator.candidate().is_some()",
                       "disposition: LearningEvaluationDispositionV1::NoUpdate", "Some(LearningIterationObservationV1::Selection { .. })"):
            self.rejects(BINDING, "fn validate_config(", marker)
        self.rejects_hidden(BINDING, "fn validate_config(", "if config.selection.receipts.len() == 5")
        source = (ROOT / BINDING).read_text()
        self.assertEqual(sorted(re.findall(r"pub\(super\) fn (\w+)\(", code(source))), sorted((
            "validate_config", "prior", "authenticate_predecessors", "receipt", "receipt_with_domain",
            "sign_original", "require_new_attestation", "evidence_id", "now",
        )))
        for marker in ("pub fn sign_original(", "pub(crate) fn sign_original(", "LearningOwnerJournalV1::create(", "commit_once("):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(BINDING, source + "\n" + marker + "\n")
        for marker in ("self.selection.receipts.len() != 4", "LearningIterationObservationV1::TrainingNoUpdateV2(_)"):
            self.rejects(COMMAND, "fn authenticate(", marker)

    def test_native_mechanisms_cover_real_source_failure_cold_missing_and_full_read_counts(self):
        source = (ROOT / NATIVE).read_text()
        for name in ("evaluated_c_reads_original_t_b_s_and_recovers_exact_baseline_completion",
                     "evaluated_c_recovery_of_missing_receipt_never_claims_or_signs"):
            self.assertIn("async fn " + name, source)
        for marker in ("ProductEvaluationExecutionStoreErrorV1::Missing", "[26, 26]", "[12, 12]",
                       "[7, 6]", "[7, 7]", "[8, 8]", "RetainedModelNextUse", "require_new_original_receipt",
                       "assert_eq!(files.bytes()?, untouched)", "NextUseError::Observation(_)", "NextUseError::Owner(OwnerError::CommitUncertain)"):
            self.assertIn(marker, source)
        parent = (ROOT / (AGENT + "circuit_evaluated_retention_receipt_tests.rs")).read_text()
        self.assertIn('#[path = "circuit_evaluated_next_use_receipt_tests.rs"]', parent)
        for path in (EVALUATED, HOST):
            self.assertNotIn("LearningIterationStageOwnerPortsV1 for", code((ROOT / path).read_text()))


if __name__ == "__main__":
    unittest.main()
