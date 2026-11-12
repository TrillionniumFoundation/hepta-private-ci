"""Mutation guards for original B custody, signed ingress and data release."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
SPEC = importlib.util.spec_from_file_location("original_b_custody_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

CASES = (
    ("root_independent_b_connection", "fn capture_original_b_connection(", (
        "RootGenerationPublicationConnectionV1::require_original_publication_session(self)?",
        "original: self.original.clone()", "identity: self.identity.clone()",
        "authority: self.authority.clone()", "verifier: Arc::clone(&self.verifier)",
        "RootGenerationPublicationConnectionV1::require_original_publication_session(&original)?",
        "Ok(OriginalRootBEvaluationConnectionV1 { original })",
    )),
    ("authority_host_q24_evaluation_record", "fn register<T>(", (
        "phase: Phase::Registering", "HostAuthorityFrontierStore::initialize(",
        "let (enrollment, result) = action()?", "Instant::now() >= end",
        "enrollment.admitted_source.is_some()", "ready.phase = Phase::Ready",
        ".compare_and_set(&held.owner, &armed, &ready)",
        "held.store.load(&held.owner).map_err(io::Error::other)? != ready", "Ok((held, result))",
    )),
    ("authority_host_q24_evaluation_record", "fn inspect<T>(", (
        ".try_lock()", "let before = self.load_ready()?", ".checked_add(1)",
        "armed.phase = Phase::Inspecting", ".compare_and_set(&self.owner, &before, &armed)",
        "let value = action(&mut enrollment)?", "if &immutable != original",
        ".is_some_and(|old| enrollment.admitted_source.as_ref() != Some(old))",
        "self.poisoned.load(Ordering::Acquire)", "Instant::now() >= end",
        "ready.phase = Phase::Ready", ".compare_and_set(&self.owner, &armed, &ready)",
        "self.store.load(&self.owner).map_err(io::Error::other)? != ready",
        "if result.is_err()", "self.poisoned.store(true, Ordering::Release)",
    )),
    ("authority_host_q24_evaluation_record", "fn load_ready(", (
        "if self.poisoned.load(Ordering::Acquire)", "match self.store.load(&self.owner)",
        "Err(error) =>", "self.poisoned.store(true, Ordering::Release)",
        "loaded.initial_head != self.initial_head", "loaded.phase != Phase::Ready",
        ".is_none_or(|entry| entry.initial_head != self.initial_head)", "Ok(loaded)",
    )),
    ("authority_host_q24_evaluation_registration", "fn register_original_b(", (
        "request_end > session_end", "OriginalBRecord::register(root, initial, request_end,",
        "service.with_learning_profile(", "require_learning(initial, &actual, learning)?",
        "snapshot != &actual", "OriginalBInputs::open(path)?", "files.admitted_protocol(&actual, now)?",
        "files.require_empty_reservation()?", "authorities.original_key(&files.evaluator_key)?",
        "registered_at_seconds: now", "admitted_source: None",
        "result.1.require_empty_reservation()?", "Ok(result)", "end: session_end",
    )),
    ("authority_host_q24_evaluation_admission", "fn activate(", (
        "self.original.activate_pinned_genesis(now)?", "signer.controller_id == self.evaluator.controller_id",
        "selected.next().is_some()", "verifier.trust_digest() != initial.owners.evidence_trust_digest",
        "generator.principal.principal_id != initial.owners.trainer",
        "evaluator.principal.principal_id != initial.owners.evaluator",
        ".require_signer_binding(LearningEvidenceRoleV1::Evaluator, &evaluator, now)",
        "verify_independent_roles(&left.principal, &right.principal, now)",
        "left.controller_id == right.controller_id", "Ok(OriginalBAuthorities",
    )),
    ("authority_host_q24_evaluation_admission", "fn original_key(", (
        "file.read_stable(32)?", "SigningKey::from_bytes(&secret)",
        "key.verifying_key().to_bytes() != self.evaluator.verifying_key",
        "file.require_original()?", "Ok(key)",
    )),
    ("authority_host_q24_evaluation_admission", "fn require_source(", (
        "source.read_stable(1_048_576)?", "OriginalHoldoutSourceData::decode(&bytes)?",
        "LearningEvidenceRoleV1::Observer", "data.policy_payload()?", "LearningEvidenceRoleV1::Generator",
        "data.require_original_times(registered_at, policy.issued_at, observed.issued_at, now)?",
        "source.read_stable(1_048_576)? != bytes", "Ok(OriginalBAdmittedSource",
    )),
    ("authority_host_q24_evaluation_provider", "fn release_after_original_consumption(", (
        "if self.attempted", "self.attempted = true", "consumed.with_current_consumption(",
        "namespace != self.namespace || plan != &self.plan.product_plan().frozen_plan",
        "self.admitted.require_original(self.files)?", "self.authorities.require_source(",
        "data.unit_profile != self.unit_profile.into_array()", "data.original_dataset != plan.dataset_digest.into_array()",
        "data.candidate_bundle != self.plan.record().candidate.manifest.bundle_digest",
        "data.manifest_digest()? != plan.final_holdout_digest", "let inputs = data.inputs()?",
        "original.require_original(self.files)?", "if &original != self.admitted",
        "self.released = Some(original)", "ProductProviderErrorV1::Indeterminate",
    )),
    ("authority_host_q24_evaluation_ingress", "fn retain_original_signed_source(", (
        "let end = self.end.min(frame_end)", "OriginalBRecord::inspect(&self.record, end,",
        "request.binding != self.original_binding().to_string()", "service.with_learning_profile(",
        "actual != self.initial || source_peer.lifetime != files.source_peer",
        "files.admitted_protocol(&actual, now)?", "current.training_no_update_v2().is_some()",
        "digest(&request.source_digest)? != source_digest", "LearningEvidenceRoleV1::Observer",
        "LearningEvidenceRoleV1::Generator", "policy.issued_at < enrollment.registered_at_seconds",
        "observed.issued_at <= policy.issued_at", "observed.issued_at > now",
        "enrollment.released_source.is_some()", ".write_original_signed_input_once(&request.observed_statement)?",
        ".write_original_signed_input_once(&request.policy_statement)?", "enrollment.admitted_source = Some(cut)",
        "files.source.read_stable(SOURCE_BOUND)? != source", "Ok(bytes)",
        "owner_alive(owner, end)?", "source_peer.require_live()?",
        "require_files(files, enrollment, service.original_learning_unix_seconds()?)?", "Ok(response)",
    )),
    ("authority_host_q24_evaluation_ingress", "fn require_statement_bytes(", (
        "bytes.is_empty() || bytes.len() > FRAME_BOUND", "crate::learning_owner_evidence::decode(bytes)",
        "crate::learning_owner_evidence::encode(&payload, &signed)",
        "expected.is_some_and(|expected| expected != payload)", "!payload.starts_with(POLICY_DOMAIN)",
        ".verify(role, &signed, &payload, now)", "verified.principal() != &signer.principal",
        "verified.controller_id() != &signer.controller_id", "Ok(signed)",
    )),
    ("authority_host_q24_evaluation_source_route", "fn prepare(", (
        "let mode = if no_update", "SourceMode::NoUpdate", "enrollment.admitted_source",
        "cut.require_original(files)?", "SourceMode::Retained", "SourceMode::FreshInput\n        };",
        "files.source.require_empty()?", "OriginalBSourcePeer::capture(",
        "Some(files.source.take_original_writer()?)", "files.source.relinquish_writer_for_observation()?",
        "(None, None)", "absolute_end_monotonic_ns: seal_original_end(original_end)?",
        "crate::authority_host_bootstrap_seal::seal_bytes(", "files.require_original_files()?",
    )),
    ("root_independent_b_source_client", "fn submit_original_root_b_source(", (
        "submit_original_root_b_source_with_candidate(handoff, |_| read_original()).await",
    )),
    ("root_independent_b_source_client", "fn submit_original_root_b_source_with_candidate(", (
        "validate_sealed(&handoff.bootstrap, length)?;\n    handoff.bootstrap.rewind()?",
        ".read_to_end(&mut bytes)?", "validate_sealed(&handoff.bootstrap, length)?",
        "let bootstrap: SourceBootstrap = serde_json::from_slice(&bytes)?",
        "serde_json::to_vec(&bootstrap)? != bytes", "bootstrap.frame_timeout_ms > 500",
        "(bootstrap.mode == SourceMode::FreshInput) != handoff.source.is_some()", "require_process(&bootstrap.root)?",
        "check_lifetime(&handoff.root_pidfd)", "receive_original_end(bootstrap.absolute_end_monotonic_ns)?",
        "SourceMode::Retained => return Ok(OriginalBSourceIngressStatusV1::AlreadyRetained)",
        "SourceMode::NoUpdate => return Ok(OriginalBSourceIngressStatusV1::NoUpdate)",
        "bootstrap.source_peer.uid == bootstrap.learner.uid", "require_process(&bootstrap.source_peer)?",
        "let original = read_original(&candidate)?", "request.len() > FRAME_BOUND",
        "data::write_original_source(file, &bootstrap, &original.source, end)?",
        "OriginalPublicationStream::from_stream_until(", "let bytes = stream.exchange(&request)?",
        "serde_json::to_vec(&response)? != bytes", "response.source_digest != source_digest.to_string()",
        "response.observed_digest != observed_digest.to_string()", "response.policy_digest != policy_digest.to_string()",
        "Instant::now() >= end", "require_process(&bootstrap.root)?",
    )),
    ("root_independent_b_source_data", "fn write_original_source(", (
        "require_original_source_file(&file, bootstrap)?", "bytes.len() > SOURCE_BOUND || Instant::now() >= end",
        "file.try_lock()", "file.metadata()?.len() != 0", "file.write_all_at(bytes,",
        "file.sync_all()?", "for _ in 0..2", "file.read_exact_at(&mut observed,",
        "if observed != bytes", "stamp(&before) != stamp(&after)", "Instant::now() >= end",
        "let unlocked = file.unlock()", "drop(file)", "written?",
    )),
    ("root_independent_b_source_data", "fn require_original_source_file(", (
        "libc::fcntl(file.as_raw_fd(), libc::F_GETFL)", "if flags < 0",
        "flags & libc::O_ACCMODE != libc::O_RDWR", "flags & (libc::O_PATH | libc::O_APPEND) != 0",
        "metadata.uid() != 0", "metadata.mode() & 0o7777 != 0o600", "metadata.nlink() != 1",
        "metadata.dev() != bootstrap.source_device", "metadata.ino() != bootstrap.source_inode",
        "metadata.len() > SOURCE_BOUND as u64",
    )),
    ("authority_host_q24_evaluation_source_serve", "fn serve_until(", (
        "let Some(listener) = &bound.source_listener else", "return original()", "std::thread::scope(",
        "let worker = scope.spawn(", "exchange_with_original_deadline(",
        "OriginalRootIndependentBEvaluationFilesV1::retain_original_signed_source(",
        "let result = original()", "stop.store(true, Ordering::Release)",
        "stream.shutdown(Shutdown::Both)", "let served = worker", ".join()", "result.and(served)",
    )),
    ("root_independent_b_training", "fn complete_from_original_training(", (
        "original.require_current_training_source()?", "self.prepare_from_original_training(original, scope)?",
        "let statement = sign_original(&challenge)?", "challenge.require_original_training(original, scope)?",
        "self.original_training(", "TrainingMode::Complete", "let after = original.require_current_training_source()",
        "result.is_err() || after.is_err()", "self.refused.store(true, Ordering::Release)", "after?",
    )),
    ("root_independent_b_training", "fn read_from_original_training(", (
        "original.require_current_training_source()?", "self.original_training(", "TrainingMode::Readback",
        "if let Err(error) = original.require_current_training_source()", "self.refused.store(true, Ordering::Release)",
    )),
    ("cell_q24_training_b_plan", "fn attest_original_root_b_plan(", (
        "self.read_original_training_evidence()?", "challenge.require_original_training(&original, &scope)?",
        "validate_config(&owner.config, &owner.key)", "original.snapshot().head_digest.as_array()",
        "binding.as_array()", ".commit_once(&key,",
        "config.verifier.require_signer_binding(\n                        LearningEvidenceRoleV1::Generator,", "signed.signature = signing.sign(&signed.signing_bytes()).to_bytes()",
        "saved_payload != payload.as_array()", "verified.controller_id() != &config.signer.controller_id",
        "owner.journal.read(&key).map_err(owner_error)? != encoded", "let after = self.read_original_training_evidence()?",
        "after.attestation() != original.attestation()", "challenge.require_original_training(&after, &scope)? != payload",
        "Ok(signed)",
    )),
)


class OriginalBCustodySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def test_original_guards_are_valid(self):
        paths = {AGENT + stem + ".rs" for stem, _, _ in CASES}
        rows = [row for row in self.manifest["protected_file"] if row["path"] in paths]
        self.assertEqual({row["path"] for row in rows}, paths)
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})

    def test_each_custody_check_cannot_be_removed_or_commented_out(self):
        for stem, function, markers in CASES:
            path = AGENT + stem + ".rs"
            original = (ROOT / path).read_text()
            code = PROOF._strip_rust_non_code(original)
            self.assertEqual(code.count(function), 1)
            start = code.index(function)
            end = PROOF._rust_item_end(code, start)
            self.assertIsNotNone(end)
            body = code[start:end + 1]
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(original)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                cursor = len(function)
                for marker in markers:
                    # Composite ordering independently protects repeated pre/post reads.
                    position = body.index(marker, cursor)
                    cursor = position + len(marker)
                    offset = start + position
                    with self.subTest(function=function, marker=marker):
                        for replacement in ("", "/*" + marker + "*/"):
                            target.write_text(original[:offset] + replacement + original[offset + len(marker):])
                            with self.assertRaises(PROOF.VerificationFailure):
                                PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
