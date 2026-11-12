"""Keep cold C reads on the same actual Root and existing original signatures.

These source counterexamples are not a daemon-plus-Root cold execution result.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
CLIENT = A + "root_generation_current_client.rs"
HISTORY = A + "root_generation_current_history.rs"
STORE = A + "neuron_generation_current_store.rs"
OWNER = A + "neuron_generation_current_root.rs"
RECOVER = A + "cell_q24_publication_historical_recovery.rs"
LIVE = A + "neuron_generation_update_live.rs"
CAP = A + "circuit_feature_historical_source.rs"
DATA = A + "circuit_task_source_data.rs"
RECEIPT = A + "neuron_generation_receipt_owner.rs"
HANDOFF = A + "circuit_feature_historical_handoff.rs"
CONTINUATION = A + "production_post_a_continuation.rs"
CALLERS = {
    "root_successor_client_read": (STORE,), "root_successor_client_backend": (OWNER,),
    "root_successor_client_owner": (CAP,), "root_successor_live_current": (CAP,),
    "root_successor_canonical_data": (CAP,), "root_successor_cap_recover": (CONTINUATION,),
    "root_successor_cap_read": (), "root_successor_feature_binding": (RECEIPT,),
    "root_successor_feature_observation": (RECEIPT,),
    "root_successor_generation_owner_recover": (HANDOFF,),
    "root_successor_generation_install": (CONTINUATION,),
    "root_successor_generation_handoff_open": (),
    "root_current_recovery_intent_client": (STORE,),
    "root_current_recovery_intent_backend": (OWNER,),
    "root_current_recovery_intent_owner": (RECOVER,),
    "q24_current_recovery_intent": (CONTINUATION,),
}


def depth(body, marker, expected):
    matches = list(re.finditer(route.token_pattern(marker), body))
    if not matches:
        raise PROOF.VerificationFailure("required actual operation missing")
    actual = [body[:m.start()].count("{") - body[:m.start()].count("}") for m in matches]
    if actual != expected:
        raise PROOF.VerificationFailure("actual checks moved behind a different branch")


def require_structure(path, source):
    if path == STORE:
        for name in ("read_original_root_recovery_intent", "read_original_completed_successor"):
            body, _ = route.function(source, "fn " + name + "(")
            if re.findall(r"\bStore\s*::\s*(\w+)", body) != ["Root"]:
                raise PROOF.VerificationFailure("only the original Root backend can supply C recovery")
    if path == CAP:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name in ("OriginalHistoricalCircuitFeatureSource", "OriginalHistoricalCircuitFeatureSourcesV1"):
            start = code.index("struct " + name)
            end = code.index(";", start) if name.endswith("V1") else PROOF._rust_item_end(code, start)
            part = code[start + len("struct " + name):end]
            if re.search(r"\bpub\b", part):
                raise PROOF.VerificationFailure("untrusted data cannot construct a C capability")
            if re.search(r"#\[derive\([^\]]*(?:Deserialize|Serialize|Default)[^\]]*\)\]\s*(?:pub\(crate\)\s+)?struct " + name + r"\b", code):
                raise PROOF.VerificationFailure("historical C capability cannot be deserialized")
        body, _ = route.function(source, "fn read_original(")
        depth(body, "held.task.require_current()?", [2, 2])
        depth(body, "NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(", [2, 2])
        depth(body, "PublishedCircuitFeatureCompletionV1::read_original_historical_completion(", [2])
        depth(body, "NeuronGenerationCurrentOwnerV1::read_original_completed_successor(", [2])
        depth(body, "source.require_decision(&decision)", [2])
        depth(body, "self.0.failed.store(true, Ordering::Release)", [2])
    if path == RECEIPT:
        body, _ = route.function(source, "fn attest_original_completion(")
        start, end = route.original.span(body, "Err(Error::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {")
        missing = body[start:end]
        branch, done = route.original.span(missing, "if matches!(")
        if "OriginalLearningReceiptSourceV1::HistoricalFeature(_)" not in missing[:branch]:
            raise PROOF.VerificationFailure("existing historical evidence must not enter new signing")
        depth(missing, "if matches!(", [1])
        if "return Err(Error::Binding(" not in missing[branch:done]:
            raise PROOF.VerificationFailure("missing historical signature must fail closed")
        if not done < missing.index("let current = now()?") < missing.index("self.journal.commit_once"):
            raise PROOF.VerificationFailure("historical refusal must precede signing or commit")
    if path == CLIENT:
        body, _ = route.function(source, "fn read_original_completed_successor(")
        depth(body, "self.require_original_historical_receipt(original_a)?", [2, 2])
        depth(body, "self.exchange_response(command)?", [2])
    if path == HISTORY:
        body, _ = route.function(source, "fn read_original_recovery_intent(")
        depth(body, "self.require_original_historical_receipt(original)?", [2, 2])


class SuccessorHistoricalClientSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[key].definition_path for key in CALLERS}
        paths.update(p for callers in CALLERS.values() for p in callers)
        cls.sources = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text())) for p in paths}

    def mutate(self, path, change):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)
            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_continuation_and_every_internal_edge_are_closed(self):
        for key, callers in CALLERS.items():
            with self.subTest(boundary=key):
                row = self.boundaries[key]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(key, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                for caller in callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=tuple(p for p in callers if p != caller)), self.sources, ())
                rogue = dict(self.sources)
                rogue[A + "unregistered_historical_c.rs"] = f"fn bypass(actual: &{row.receiver_type}) {{ actual.{row.symbol.rsplit('::', 1)[-1]}(); }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, rogue, ())

    def test_intent_is_read_from_exact_published_root_state(self):
        self.check(HISTORY, "read_original_recovery_intent", ("self.version != PublicationVersion::DurableV2", "let before = self.observe()?", "before.published.as_ref().ok_or_else(uncertain)?", "before.current != self.profile.intent.target", "before.prepared.is_some()", "published.intent != self.profile.intent", "let digest = published.intent.digest()?", "digest.is_zero() || self.observe()? != before", "self.fence()"))
        for occurrence in (0, 1):
            self.reject(HISTORY, "read_original_recovery_intent", "self.require_original_historical_receipt(original)?", occurrence)
            self.reject(RECOVER, "read_original_recovery_intent", "OriginalDecision::require_current(original).await?", occurrence)
        self.check(RECOVER, "read_original_recovery_intent", ("original.decision.require_root_publication()?", "NeuronGenerationCurrentOwnerV1::require_original_root_selection(", "self.selected.observation().digest()", "NeuronGenerationCurrentOwnerV1::read_original_root_recovery_intent(", "NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt("))

    def test_host_or_initial_backend_cannot_supply_historical_c(self):
        for name in ("read_original_root_recovery_intent", "read_original_completed_successor"):
            def change(source, name=name):
                marker = "fn " + name + "("
                body, raw = route.function(source, marker)
                return source.replace(raw, raw.replace("Store::Root(client) =>", "Store::Host(_) => Ok(fabricated()), Store::Root(client) =>", 1), 1)
            self.mutate(STORE, change)

    def test_same_lane_sequence_profile_and_session_guard_all_commands(self):
        self.check(CLIENT, "exchange_response", ("self.fenced.load(Ordering::Acquire)", "self.lane.try_lock()", "held.take()", "request_id.checked_add(1)", "response.profile != self.profile", "validate_head(&self.profile, &response.head)?", "*held = Some(lane)"))
        for occurrence in (0, 1):
            self.reject(CLIENT, "exchange_response", "require_original_publication_session()", occurrence)
        self.check(CLIENT, "exchange", ("self.exchange_response(command)?", "response.successor.is_some()", "self.fence()"))

    def test_explicit_cold_phase_and_same_root_receipt_surround_physical_reply(self):
        self.check(CLIENT, "read_original_completed_successor", ("self.version != PublicationVersion::DurableV2", "if capture_retired", "Command::CaptureRetiredTask {}", "Command::ReadFinalizedTask {}", "self.exchange_response(command)?", "response.head.current != self.profile.intent.target", "response.successor.ok_or_else(uncertain)?", "digest.is_zero() || digest.to_string() != data.record_digest", "self.fence()"))
        for occurrence in (0, 1):
            self.reject(CLIENT, "read_original_completed_successor", "self.require_original_historical_receipt(original_a)?", occurrence)
        self.check(LIVE, "original_historical_successor_current", ("RetainedPublication::Update(_)", "NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(", "Ok(Arc::clone(&self.current))"))
        self.mutate(LIVE, lambda s: s.replace('#[cfg(target_os = "linux")]\n    pub(crate) fn original_historical_successor_current(', 'pub(crate) fn original_historical_successor_current(', 1))

    def test_original_task_and_full_a_completion_bind_the_opaque_c_source(self):
        self.check(CAP, "recover_original_completed_successor", ("LiveGenerationCurrent::original_historical_successor_current(", "NeuronGenerationCurrentOwnerV1::read_original_completed_successor(", "matches!(mode, OriginalSuccessorRecoveryModeV1::CaptureRetired)", "source.read_original()?"))
        self.check(CAP, "read_original", ("self.0.failed.load(Ordering::Acquire)", "Publication::Update { original, previous }", "PublishedCircuitFeatureCompletionV1::read_original_historical_completion(", "actual_a.binding != previous.binding", "actual_a.source != previous.source", "actual_a.receipt != previous.receipt", "data != held.data", "data.cut.definition", "RootHistoricalTaskPublicationDataV1::decode_original_successor_data(", "input != &source_input(held.task.source(), input.operation_id.clone())", "source.bundle_digest() != held.task.definition().bundle_digest", "data.cut.writer_epoch != original.target().writer_epoch()", "source.require_decision(&decision)", "self.0.failed.store(true, Ordering::Release)"))
        for occurrence in (0, 1):
            self.reject(CAP, "read_original", "held.task.require_current()?", occurrence)
            self.reject(CAP, "read_original", "NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(", occurrence)

    def test_raw_data_cannot_construct_owners_or_become_dataset_authority(self):
        self.mutate(CAP, lambda s: s.replace("    data: RootCompletedSuccessorDataV1,", "    pub(crate) data: RootCompletedSuccessorDataV1,", 1))
        self.mutate(CAP, lambda s: s.replace("#[derive(Clone)]\npub(crate) struct OriginalHistoricalCircuitFeatureSourcesV1", "#[derive(Clone, Deserialize)]\npub(crate) struct OriginalHistoricalCircuitFeatureSourcesV1", 1))
        for marker in ("File::open(path);", "DurableCircuitTaskSourceV1::recover(args);", "CellOwnerJournalV1::open(args);", "claim_final_use(args);", "HistoricalDatasetTaskV1::new(args);"):
            self.mutate(CAP, lambda s, marker=marker: s + "\nfn bypass() { " + marker + " }\n")

    def test_existing_feature_binding_and_each_observation_have_current_rereads(self):
        self.check(CAP, "require_original_feature_binding", ("previous.manifest.bundle_digest != baseline.into_array()", "original.publication_digest()?.as_array()", "source.publication_digest().as_array()", "previous.manifest.digest()"))
        self.check(CAP, "read_original_feature_observation", ("LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())", "self.read_selection(coordinator)?", "self.read_next_use(coordinator, &source, &decision)?"))
        for name in ("require_original_feature_binding", "read_original_feature_observation"):
            for occurrence in (0, 1):
                self.reject(CAP, name, "self.read_original()?", occurrence)

    def test_actual_next_use_requires_selection_partition_and_both_state_cuts(self):
        self.check(CAP, "read_next_use", ("coordinator.next_stage() != Some(LearningIterationStageV1::NextUse)", "prefix.head_digest = selection.predecessor", "let actual = self.read_selection(&prefix)?", "actual != selection.observation", "decision.bundle_digest != candidate_bundle", "previous.source.input().scope.run_id != coordinator.snapshot().request.source_run_id", "scope.principal_digest.to_string()", "agent_id: scope.agent_id.clone()", "cell_id: scope.cell_id.clone()", "run_id: scope.run_id.clone()", "source.publication_digest().as_array()", "crate::circuit_cell_output::encode_receipt(decision)", "previous.binding.digest()", "original.target().digest()", "previous.source.publication_digest().as_array()", "previous.receipt.checkpoint_after.as_array()", "decision.checkpoint_before.as_array()", "state_partition.digest().as_array()"))

    def test_missing_original_signature_cannot_sign_or_commit_a_replacement(self):
        self.check(RECEIPT, "recover_historical_feature", ("OriginalLearningReceiptSourceV1::HistoricalFeature(source)", "validate_config(&config, &key, &source)?", "LearningOwnerJournalV1::recover(file, witness, binding)?"))
        self.check(RECEIPT, "attest_original_completion", ("OriginalLearningReceiptSourceV1::HistoricalFeature(_)", "return Err(Error::Binding("))
        self.mutate(RECEIPT, lambda s: s.replace("if matches!(\n                    &self.source,\n                    OriginalLearningReceiptSourceV1::HistoricalFeature(_)\n                )", "if false && matches!(\n                    &self.source,\n                    OriginalLearningReceiptSourceV1::HistoricalFeature(_)\n                )", 1))

    def test_handoff_only_recovers_under_the_same_actual_scope_and_original_keys(self):
        self.check(HANDOFF, "open", ("initial: initial.clone()", "scope: scope.clone()", "signer: files.signer.clone()", "verifier: self.verifier.clone()", "self.selection.file,", "self.selection.witness,", "self.selection.key,", "self.next_use.file,", "self.next_use.witness,", "self.next_use.key,"))
        for occurrence in (0, 1):
            self.reject(HANDOFF, "open", "OriginalGenerationLearningReceiptOwnerV1::recover_historical_feature(", occurrence)
        self.check(HANDOFF, "install_historical_circuit_feature_generation", ("snapshot.request != initial.request || snapshot.owners != initial.owners", ".validate_snapshot(&snapshot)", "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?", "self.require_current().await?", "tokio::task::spawn_blocking(move || original.open(initial, scope))", "OriginalCellQ24LearningStageOwnersV1::install_generation(", "self, snapshot, selection, next_use,"))


if __name__ == "__main__":
    unittest.main()
