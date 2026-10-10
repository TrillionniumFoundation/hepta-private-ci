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
