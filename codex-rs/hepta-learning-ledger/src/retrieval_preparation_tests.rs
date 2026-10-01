use super::*;
use crate as ledger;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn writer(root: &Path) -> ledger::LedgerWriter {
    let scope = digest("cognitive-delivery-test-scope");
    let key = SigningKey::from_bytes(&[11; 32]);
    let root_key = SigningKey::from_bytes(&[12; 32]);
    let root_trust = ledger::LearningTrustRootV1 {
        root_id: id("delivery-root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut distribution = ledger::SignedLearningTrustDistributionV1 {
        distribution: ledger::LearningTrustDistributionV1 {
            distribution_id: id("delivery-trust"),
            generation: 1,
            effective_at: 20,
            trust: ledger::LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: digest("delivery-objective"),
                authority_epoch: 7,
                signers: vec![ledger::TrustedLearningSignerV1 {
                    principal: ledger::AuthenticatedPrincipalV1 {
                        principal_id: id("delivery-generator"),
                        credential_chain_digest: digest("delivery-credential"),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: scope,
                        authority_epoch: 7,
                        authenticated_at: 10,
                        expires_at: 100,
                    },
                    controller_id: id("delivery-controller"),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![ledger::LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            },
        },
        root_id: root_trust.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    let previous = None;
    let now = 50;
    let trust = ledger::activate_learning_trust(&root_trust, distribution, previous, now).unwrap();
    let open = |name: &str| {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(root.join(name))
            .unwrap()
    };
    let binding = digest("delivery-ledger-binding");
    let capacity = 64;
    let durable =
        ledger::DurableLedger::create(open("learning.journal"), binding, capacity).unwrap();
    let witness = ledger::LedgerWitnessStore::create(open("learning.witness"), binding).unwrap();
    let directory = File::open(root).unwrap();
    ledger::LedgerWriter::from_durable(durable, witness, trust, &directory, &directory).unwrap()
}

fn assignment(record_id: StableId, episode_id: StableId) -> ledger::RetrievalAssignmentFact {
    ledger::RetrievalAssignmentFact {
        record_id,
        episode_id,
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-completeness"),
        candidate_union_digest: digest("candidate-union"),
        recall_packet_digest: digest("recall"),
        enumerated_candidate_digests: vec![digest("candidate")],
        legal_candidate_indices: vec![0],
        selected_candidate_indices: vec![0],
        delivered_candidate_indices: vec![0],
        context_exposed: true,
        published_context_digest: Some(digest("published-context")),
        omitted_by_policy_limits: 0,
        assignment_propensity: ProbabilityQ32::ONE,
        downstream_policy_digest: None,
        delivery_propensity: ProbabilityQ32::ONE,
        completeness: ledger::CandidateSetCompleteness::Complete,
        support_digest: digest("assignment-support"),
    }
}

struct Fixture(std::path::PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let sequence = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-retrieval-preparation-{}-{nanos}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn preparation_read_is_indexed_bound_and_non_mutating() {
    let fixture = Fixture::new();
    let mut writer = writer(&fixture.0);
    let value = assignment(id("assignment"), id("episode"));
    assert!(
        writer
            .read_current_retrieval_assignment(&value.record_id, &value.episode_id)
            .is_err()
    );
    writer
        .append_retrieval_assignment_current(value.clone())
        .unwrap();
    let before = writer.witness_frontier().unwrap();
    let record = writer
        .read_current_retrieval_assignment(&value.record_id, &value.episode_id)
        .unwrap();
    let indexed = writer
        .backend
        .core()
        .unwrap()
        .record_by_id(&value.record_id)
        .unwrap()
        .unwrap();
    assert!(std::ptr::eq(record, indexed));
    assert_eq!(
        &record.event,
        &ledger::LedgerEvent::RetrievalAssignment(value.clone())
    );
    assert_eq!(writer.witness_frontier().unwrap(), before);
    assert!(
        writer
            .read_current_retrieval_assignment(&value.record_id, &id("another-episode"))
            .is_err()
    );
}

#[test]
fn witness_lag_and_revocation_never_become_delivery_preparation() {
    let fixture = Fixture::new();
    let mut writer = writer(&fixture.0);
    let value = assignment(id("assignment"), id("episode"));
    // Simulate a committed ledger event whose independent witness was not advanced.
    writer
        .backend
        .append(
            Digest32::ZERO,
            ledger::LedgerEvent::RetrievalAssignment(value.clone()),
        )
        .unwrap();
    assert!(matches!(
        writer.read_current_retrieval_assignment(&value.record_id, &value.episode_id),
        Err(ProductionLedgerError::WitnessLag)
    ));
    assert!(matches!(
        writer.append_retrieval_assignment_preparation(value.clone()),
        Err(ProductionLedgerError::WitnessLag)
    ));
    // Only exact idempotent recovery may close the witness gap.
    let repaired = writer
        .append_retrieval_assignment_current(value.clone())
        .unwrap();
    assert!(
        writer
            .read_current_retrieval_assignment(&value.record_id, &value.episode_id)
            .is_ok()
    );
    writer
        .commit(
            repaired.chain_digest,
            ledger::LedgerEvent::Revocation(ledger::Revocation {
                record_id: id("revoke-assignment"),
                target_record_id: value.record_id.clone(),
                authority_id: id("privacy-owner"),
                reason_digest: digest("withdrawn"),
            }),
        )
        .unwrap();
    assert!(
        writer
            .read_current_retrieval_assignment(&value.record_id, &value.episode_id)
            .is_err()
    );
}

#[test]
fn preparation_identity_advances_with_the_durable_owner_after_reopen() {
    let fixture = Fixture::new();
    let mut writer = writer(&fixture.0);
    let explicit = assignment(id("assignment"), id("episode"));
    let first = writer
        .append_retrieval_assignment_preparation(explicit.clone())
        .unwrap();
    let anchor = writer.witness_frontier().unwrap().anchor;
    let binding = writer.backend.binding();
    let trust = writer.trust.clone();
    drop(writer);
    let file = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(fixture.0.join(name))
            .unwrap()
    };
    let durable = ledger::DurableLedger::recover(
        file("learning.journal"),
        binding,
        /*max_records*/ 64,
        ledger::LedgerRecovery::Acknowledged(anchor),
    )
    .unwrap();
    let witness = ledger::LedgerWitnessStore::recover(file("learning.witness"), binding).unwrap();
    let directory = File::open(&fixture.0).unwrap();
    let mut writer =
        ledger::LedgerWriter::from_durable(durable, witness, trust, &directory, &directory)
            .unwrap();
    let second = writer
        .append_retrieval_assignment_preparation(explicit.clone())
        .unwrap();
    assert_eq!(
        writer
            .read_current_retrieval_preparation(
                first.sequence,
                first.event_digest,
                first.chain_digest,
                &explicit.record_id,
                &explicit.episode_id,
            )
            .unwrap()
            .sequence,
        first.sequence,
    );
    assert_eq!(second.sequence.get(), first.sequence.get() + 1);
    assert_eq!(second.disposition, ledger::AppendDisposition::Appended);
    let snapshot = writer.snapshot().unwrap();
    let events = snapshot
        .records()
        .iter()
        .map(|record| match &record.event {
            ledger::LedgerEvent::RetrievalAssignment(value) => value,
            _ => panic!("unexpected event"),
        })
        .collect::<Vec<_>>();
    assert_ne!(events[0].record_id, events[1].record_id);
    assert_ne!(events[0].episode_id, events[1].episode_id);
    assert_eq!(events[0].support_digest, events[1].support_digest);
    assert!(
        writer
            .read_current_retrieval_assignment(&explicit.record_id, &explicit.episode_id)
            .is_err()
    );
    // Explicit stable-operation retries retain their distinct existing API.
    let stable = writer
        .append_retrieval_assignment_current(explicit.clone())
        .unwrap();
    let replay = writer
        .append_retrieval_assignment_current(explicit)
        .unwrap();
    assert_eq!(
        replay.disposition,
        ledger::AppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.sequence, stable.sequence);
    assert_eq!(replay.event_digest, stable.event_digest);
}

#[test]
fn owner_preparation_receipt_requires_exact_namespace_witness_and_activity() {
    let fixture = Fixture::new();
    let mut writer = writer(&fixture.0);
    let namespace = assignment(id("namespace-record"), id("namespace-episode"));
    let receipt = writer
        .append_retrieval_assignment_preparation(namespace.clone())
        .unwrap();
    let read = |writer: &ledger::LedgerWriter,
                sequence,
                event_digest,
                chain_digest,
                record_id: &StableId| {
        writer
            .read_current_retrieval_preparation(
                sequence,
                event_digest,
                chain_digest,
                record_id,
                &namespace.episode_id,
            )
            .map(|record| record.event.record_id().clone())
    };
    let issued_id = read(
        &writer,
        receipt.sequence,
        receipt.event_digest,
        receipt.chain_digest,
        &namespace.record_id,
    )
    .unwrap();
    assert!(
        read(
            &writer,
            LogicalSequence::new(receipt.sequence.get() + 1).unwrap(),
            receipt.event_digest,
            receipt.chain_digest,
            &namespace.record_id
        )
        .is_err()
    );
    assert!(
        read(
            &writer,
            receipt.sequence,
            digest("different-event"),
            receipt.chain_digest,
            &namespace.record_id
        )
        .is_err()
    );
    assert!(
        read(
            &writer,
            receipt.sequence,
            receipt.event_digest,
            digest("different-chain"),
            &namespace.record_id
        )
        .is_err()
    );
    assert!(
        read(
            &writer,
            receipt.sequence,
            receipt.event_digest,
            receipt.chain_digest,
            &id("different-owner-namespace")
        )
        .is_err()
    );
    let pending = assignment(id("pending-record"), id("pending-episode"));
    writer
        .backend
        .append(
            receipt.chain_digest,
            ledger::LedgerEvent::RetrievalAssignment(pending.clone()),
        )
        .unwrap();
    assert!(matches!(
        read(
            &writer,
            receipt.sequence,
            receipt.event_digest,
            receipt.chain_digest,
            &namespace.record_id
        ),
        Err(ProductionLedgerError::WitnessLag)
    ));
    let explicit = writer
        .append_retrieval_assignment_current(pending.clone())
        .unwrap();
    assert!(
        writer
            .read_current_retrieval_preparation(
                explicit.sequence,
                explicit.event_digest,
                explicit.chain_digest,
                &pending.record_id,
                &pending.episode_id
            )
            .is_err()
    );
    writer
        .commit(
            explicit.chain_digest,
            ledger::LedgerEvent::Revocation(ledger::Revocation {
                record_id: id("revoke-owner-preparation"),
                target_record_id: issued_id,
                authority_id: id("privacy-owner"),
                reason_digest: digest("withdrawn"),
            }),
        )
        .unwrap();
    assert!(
        read(
            &writer,
            receipt.sequence,
            receipt.event_digest,
            receipt.chain_digest,
            &namespace.record_id
        )
        .is_err()
    );
}
