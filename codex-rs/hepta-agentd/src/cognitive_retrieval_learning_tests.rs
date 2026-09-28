use super::*;

use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000141").expect("owner")
}

fn trusted(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn activated_trust() -> ActivatedLearningTrustV1 {
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                "observer",
                "observer-controller",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            trusted(
                "allocator",
                "allocator-controller",
                3,
                LearningEvidenceRoleV1::CreditAllocator,
            ),
            trusted(
                "evaluator",
                "evaluator-controller",
                4,
                LearningEvidenceRoleV1::Evaluator,
            ),
            trusted(
                "privacy-owner",
                "privacy-controller",
                5,
                LearningEvidenceRoleV1::UnlearningAuthority,
            ),
        ],
    };
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-distribution"),
            generation: 1,
            effective_at: 20,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key
        .sign(&signed.signing_bytes().expect("signing bytes"))
        .to_bytes();
    activate_learning_trust(&root, signed, None, 50).expect("activate trust")
}

fn observation(label: &str) -> RetrievalAssignmentObservationV1 {
    let candidate = RetrievalCandidateIdentityV1 {
        record_id: id("memory:1"),
        record_revision: Revision::new(1).expect("revision"),
        record_digest: digest("record"),
    };
    let mut value = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-complete"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest(label),
        enumerated_candidates: vec![candidate.clone()],
        legal_candidates: vec![candidate.clone()],
        selected_candidates: vec![candidate],
        omitted_by_policy_limits: 0,
        completeness: RetrievalAssignmentCompletenessV1::Complete,
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.observation_digest = value.compute_observation_digest();
    value.validate().expect("observation");
    value
}

fn sink() -> (tempfile::TempDir, CognitiveRetrievalLearningSink) {
    let temp = tempfile::tempdir().expect("temp");
    let binding = digest("agentd-retrieval-learning");
    let ledger_path = temp.path().join("learning.ledger");
    let witness_path = temp.path().join("learning.witness");
    let ledger_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("ledger file");
    let witness_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&witness_path)
        .expect("witness file");
    let ledger = DurableLedger::create(ledger_file, binding, 128).expect("ledger");
    let witness = LedgerWitnessStore::create(witness_file, binding).expect("witness");
    let ledger_directory = File::open(temp.path()).expect("ledger directory");
    let witness_directory = File::open(temp.path()).expect("witness directory");
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        activated_trust(),
        &ledger_directory,
        &witness_directory,
    )
    .expect("product writer");
    (temp, CognitiveRetrievalLearningSink::new(writer))
}

#[test]
fn same_rpc_and_observation_replays_idempotently() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    let first = sink
        .append(&owner(), 1, 77, &observation)
        .expect("first append");
    let second = sink.append(&owner(), 1, 77, &observation).expect("replay");
    assert_eq!(first.disposition, AppendDisposition::Appended);
    assert_eq!(second.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first.event_digest, second.event_digest);
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn same_rpc_with_different_assignment_is_identity_conflict() {
    let (_temp, sink) = sink();
    sink.append(&owner(), 1, 88, &observation("packet-a"))
        .expect("first append");
    assert!(
        sink.append(&owner(), 1, 88, &observation("packet-b"))
            .is_err()
    );
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn different_rpc_ids_create_distinct_assignment_records() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    sink.append(&owner(), 1, 1, &observation).expect("first");
    sink.append(&owner(), 1, 2, &observation).expect("second");
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 2);
}

#[test]
fn historical_assignment_retry_keeps_original_predecessor_after_later_appends() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    let first = sink.append(&owner(), 1, 1, &observation).expect("first");
    for request in 2..=64 {
        sink.append(&owner(), 1, request, &observation)
            .expect("later");
    }
    let before = sink
        .writer
        .lock()
        .expect("lock")
        .witness_frontier()
        .expect("frontier");
    let retry = sink
        .append(&owner(), 1, 1, &observation)
        .expect("historical retry");
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.sequence, first.sequence);
    assert_eq!(retry.event_digest, first.event_digest);
    assert_eq!(retry.chain_digest, first.chain_digest);
    let writer = sink.writer.lock().expect("lock");
    assert_eq!(writer.witness_frontier().expect("frontier"), before);
    assert_eq!(writer.snapshot().expect("snapshot").records().len(), 64);
}

#[test]
fn indexed_historical_identity_does_not_accept_changed_assignment() {
    let (_temp, sink) = sink();
    sink.append(&owner(), 1, 1, &observation("packet-a"))
        .expect("first");
    sink.append(&owner(), 1, 2, &observation("packet-b"))
        .expect("later");
    let before = sink
        .writer
        .lock()
        .expect("lock")
        .witness_frontier()
        .expect("frontier");
    assert!(
        sink.append(&owner(), 1, 1, &observation("replacement"))
            .is_err()
    );
    let writer = sink.writer.lock().expect("lock");
    assert_eq!(writer.witness_frontier().expect("frontier"), before);
    assert_eq!(writer.snapshot().expect("snapshot").records().len(), 2);
}

#[test]
fn product_sink_nonempty_context_is_a_preparation_not_an_exposure() {
    let (_temp, sink) = sink();
    let observation = observation("prepared-packet");
    sink.append_preparation(
        &owner(),
        1,
        707,
        &observation,
        &observation.selected_candidates,
        Some(digest("exact-response")),
        None,
        ProbabilityQ32::ONE,
    )
    .expect("prepare");
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    let LedgerEvent::RetrievalPrepared(prepared) = &snapshot.records()[0].event else {
        panic!("product sink emitted a legacy exposure event");
    };
    assert!(!prepared.assignment.context_exposed);
    assert!(prepared.assignment.delivered_candidate_indices.is_empty());
    assert!(prepared.assignment.published_context_digest.is_none());
    assert_eq!(prepared.prepared_candidate_indices, vec![0]);
    assert_eq!(
        prepared.prepared_context_digest,
        Some(digest("exact-response"))
    );
}

#[test]
fn durable_native_reopen_never_promotes_write_ahead_dispatch_to_exposure() {
    use crate::retrieval_delivery::RetrievalDeliveryStageV1;
    use crate::retrieval_delivery::RetrievalNativeBindingV1;
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use serde_json::json;

    let (temp, sink) = sink();
    let observation = observation("durable-reconciliation");
    let context = digest("exact-response");
    let first = sink
        .append_preparation(
            &owner(),
            1,
            707,
            &observation,
            &observation.selected_candidates,
            Some(context),
            None,
            ProbabilityQ32::ONE,
        )
        .expect("durable preparation");
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    let preparation_id = snapshot.records()[0].event.record_id().clone();
    let binding = RetrievalNativeBindingV1 {
        request_id: "native-request".to_string(),
        principal_id: "principal".to_string(),
        worker_generation: 7,
    };
    let journal_path = temp.path().join("native.journal");
    let mut native = DurableInferenceControl::open(&journal_path, 16).expect("native owner");
    let prepared = sink
        .native_delivery_receipt(&preparation_id, &binding, &native)
        .expect("prepared");
    assert_eq!(prepared.stage, RetrievalDeliveryStageV1::AssignmentPrepared);
    native
        .reserve_native(
            NativeRequest {
                request_id: binding.request_id.clone(),
                principal_id: binding.principal_id.clone(),
                worker_generation: binding.worker_generation,
                model: "model".to_string(),
                payload_digest: digest("payload").to_string(),
            },
            2,
        )
        .expect("reserve");
    let dispatch: NativeDispatch = serde_json::from_value(json!({
        "thread_id": "thread", "model_provider": "provider",
        "context_digest": digest("additional-context").to_string(),
        "owner_context_digest": context.to_string(),
    }))
    .expect("dispatch");
    native
        .dispatch_native(&binding.request_id, dispatch)
        .expect("write-ahead dispatch");
    let before_crash = sink
        .native_delivery_receipt(&preparation_id, &binding, &native)
        .expect("WAL");
    assert_eq!(
        before_crash.stage,
        RetrievalDeliveryStageV1::AssignmentPrepared
    );
    drop(native);
    let mut native = DurableInferenceControl::open(&journal_path, 16).expect("reopen");
    let after_crash = sink
        .native_delivery_receipt(&preparation_id, &binding, &native)
        .expect("reconcile");
    assert_eq!(after_crash, before_crash);
    native
        .native_started(&binding.request_id, "turn".to_string())
        .expect("durable native start");
    let started = sink
        .native_delivery_receipt(&preparation_id, &binding, &native)
        .expect("start");
    assert_eq!(started.stage, RetrievalDeliveryStageV1::NativeStarted);
    drop(native);
    let native = DurableInferenceControl::open(&journal_path, 16).expect("reopen started");
    assert_eq!(
        sink.native_delivery_receipt(&preparation_id, &binding, &native)
            .expect("stable"),
        started
    );
    let replay = sink
        .append_preparation(
            &owner(),
            1,
            707,
            &observation,
            &observation.selected_candidates,
            Some(context),
            None,
            ProbabilityQ32::ONE,
        )
        .expect("idempotent retry");
    assert_eq!(replay.event_digest, first.event_digest);
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(
        sink.writer
            .lock()
            .expect("lock")
            .snapshot()
            .expect("snapshot")
            .records()
            .len(),
        1
    );
    assert!(
        sink.native_delivery_receipt(&id("absent"), &binding, &native)
            .is_err()
    );
    let wrong = RetrievalNativeBindingV1 {
        principal_id: "another-principal".to_string(),
        ..binding
    };
    assert!(
        sink.native_delivery_receipt(&preparation_id, &wrong, &native)
            .is_err()
    );
}

#[test]
fn busy_product_writer_fails_before_another_append_can_wait() {
    let (_temp, sink) = sink();
    let _held = sink.writer.lock().expect("hold offline reconciliation");
    assert!(sink.append(&owner(), 3, 91, &observation("busy")).is_err());
}

#[test]
fn expired_or_wrong_owner_host_admission_never_appends() {
    let (_temp, mut sink) = sink();
    sink.admission = Some(RetrievalLearningAdmission {
        owner: owner(), body_generation: 3, expires_at_unix_s: 0,
        expires_at: std::time::Instant::now() + std::time::Duration::from_secs(60),
    });
    assert!(sink.append(&owner(), 3, 92, &observation("expired")).is_err());
    sink.admission.as_mut().expect("admission").expires_at_unix_s = u64::MAX;
    assert!(sink.append(&owner(), 4, 92, &observation("wrong-body")).is_err());
    sink.admission.as_mut().expect("admission").expires_at = std::time::Instant::now();
    assert!(sink.append(&owner(), 3, 92, &observation("monotonic-expiry")).is_err());
    assert!(sink.writer.lock().expect("writer").records().expect("records").is_empty());
}
