//! All credentials/data below are local deterministic TEST FIXTURES.
//! No original IB PAPER event is claimed source-time escrowed; no production
//! RecoveryAuthority controller/root is installed.
use super::*;
use crate::AppendDisposition;
use crate::AuthenticatedDecisionRecordV2;
use crate::LedgerEvent;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::{Signer, SigningKey};
use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT: AtomicU64 = AtomicU64::new(1);
const NOW: u64 = 100_000;
fn id(s: &str) -> StableId {
    StableId::new(s.to_owned()).unwrap()
}
fn dg(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
fn new_file(dir: &Path, name: &str) -> File {
    let path = dir.join(name);
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap()
}
fn actor_auth() -> Digest32 {
    dg("fictional-source-SignedLearningEvidenceV1-authentication")
}
fn synthetic_decision(episode: &str, controller: &str) -> LedgerEvent {
    LedgerEvent::AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2 {
        record_id: id(&format!("decision-{episode}")),
        episode_id: id(episode),
        run_snapshot_digest: dg("synthetic-run"),
        objective_digest: dg("synthetic-objective"),
        policy_digest: dg("new-synthetic-no-order"),
        generator_id: id("old-generator"),
        generator_controller_id: id(controller),
        generator_credential_chain_digest: dg("old-generator-credential"),
        generator_signing_key_digest: dg("old-generator-key"),
        generator_scope_digest: dg("synthetic-ledger-scope"),
        generator_authority_epoch: 3,
        candidate_ids: vec![id("abstain"), id("lab.action")],
        selected_candidate_id: id("abstain"),
        selected_propensity: ProbabilityQ32::ONE,
        candidate_completeness_digest: dg("synthetic-closed-candidate-set"),
        support_digest: dg("synthetic-support-not-real-market"),
        authentication_digest: actor_auth(),
    })
}
struct Fixture {
    dir: PathBuf,
    ledger: DurableLedger,
    witness: LedgerWitnessStore,
    root: AckOnlyRootPinV1,
    delegation: AckOnlyRootDelegationV1,
    cut: AckOnlyCurrentRevocationCutV1,
    escrow: AckOnlySourceEscrowV1,
    grant: AckOnlyRecoveryGrantV1,
    escrow_archive: Vec<u8>,
    root_key: SigningKey,
    recovery_key: SigningKey,
    escrow_key: SigningKey,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}
impl Fixture {
    fn new() -> Self {
        Self::new_event(false)
    }
    fn new_event(legacy: bool) -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "hepta-ackonly-root-test-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&dir).unwrap();
        let binding = dg("test-only-ackonly-ledger-binding");
        let mut ledger = DurableLedger::create(new_file(&dir, "ledger"), binding, 16).unwrap();
        let witness = LedgerWitnessStore::create(new_file(&dir, "witness"), binding).unwrap();
        let event = if legacy {
            LedgerEvent::Decision(crate::EpisodeDecision {
                record_id: id("legacy-decision"),
                episode_id: id("episode-1"),
                objective_digest: dg("synthetic-objective"),
                policy_id: id("synthetic-old-policy"),
                candidate_ids: vec![id("abstain")],
                selected_candidate_id: id("abstain"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: crate::CandidateSetCompleteness::Complete,
                support_digest: dg("test-only-legacy-support"),
            })
        } else {
            synthetic_decision("episode-1", "original-generator.controller")
        };
        let receipt = ledger.append(Digest32::ZERO, event).unwrap();
        assert_eq!(receipt.disposition, AppendDisposition::Appended);
        let prev = LedgerAnchor {
            sequence: 0,
            chain_digest: Digest32::ZERO,
        };
        let next = LedgerAnchor {
            sequence: 1,
            chain_digest: receipt.chain_digest,
        };
        let root_key = SigningKey::from_bytes(&[7; 32]);
        let recovery_key = SigningKey::from_bytes(&[8; 32]);
        let escrow_key = SigningKey::from_bytes(&[9; 32]);
        let root = AckOnlyRootPinV1 {
            root_id: id("TEST-ONLY.product.pinned.root"),
            ledger_binding: binding,
            objective_digest: dg("synthetic-objective"),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 200_000,
            revoked_at: None,
        };
        let mut delegation = AckOnlyRootDelegationV1 {
            root_id: root.root_id.clone(),
            authority_epoch: 11,
            authority_id: id("test.recovery.authority"),
            authority_controller_id: id("RECOVERY.CONTROLLER"),
            recovery_verifying_key: recovery_key.verifying_key().to_bytes(),
            escrow_id: id("test.independent.escrow"),
            escrow_controller_id: id("ESCROW.CONTROLLER"),
            escrow_verifying_key: escrow_key.verifying_key().to_bytes(),
            effective_at: 2,
            expires_at: 190_000,
            root_signature: [0; 64],
        };
        delegation.root_signature = root_key.sign(&delegation.signing_bytes(&root)).to_bytes();
        let mut cut = AckOnlyCurrentRevocationCutV1 {
            root_id: root.root_id.clone(),
            delegation_digest: delegation.digest(&root),
            authority_epoch: 11,
            cut_id: dg("current-separately-root-signed-revocation-cut"),
            issued_at: 99_000,
            expires_at: 101_000,
            recovery_authority_current: true,
            escrow_authority_current: true,
            original_event_not_revoked: true,
            root_signature: [0; 64],
        };
        cut.root_signature = root_key.sign(&cut.signing_bytes()).to_bytes();
        let mut escrow = AckOnlySourceEscrowV1 {
            escrow_id: delegation.escrow_id.clone(),
            authority_epoch: 11,
            ledger_binding: binding,
            objective_digest: root.objective_digest,
            original_record_id: if legacy {
                id("legacy-decision")
            } else {
                id("decision-episode-1")
            },
            original_authentication_digest: actor_auth(),
            previous_witness: prev,
            target_anchor: next,
            target_event_digest: receipt.event_digest,
            original_actor_evidence_issued_at: 31_000,
            escrow_held_at: 32_000,
            original_append_started_at: 33_000,
            unique_intent_digest: dg("original-test-only-preappend-intent-not-IB"),
            escrow_signature: [0; 64],
        };
        escrow.escrow_signature = escrow_key.sign(&escrow.signing_bytes()).to_bytes();
        let escrow_archive = escrow.receipt_bytes();
        let mut grant = AckOnlyRecoveryGrantV1 {
            grant_id: id("recover-only-this-original-frame"),
            grant_nonce: dg("test-only-never-repeat-nonce"),
            delegation_digest: delegation.digest(&root),
            current_cut_digest: cut.digest(),
            authority_epoch: 11,
            ledger_binding: binding,
            objective_digest: root.objective_digest,
            source_escrow_receipt_digest: escrow.digest(),
            original_record_id: escrow.original_record_id.clone(),
            original_authentication_digest: actor_auth(),
            previous_witness: prev,
            target_anchor: next,
            target_event_digest: receipt.event_digest,
            issued_at: 99_500,
            expires_at: 100_500,
            recovery_signature: [0; 64],
        };
        grant.recovery_signature = recovery_key.sign(&grant.signing_bytes()).to_bytes();
        Self {
            dir,
            ledger,
            witness,
            root,
            delegation,
            cut,
            escrow,
            grant,
            escrow_archive,
            root_key,
            recovery_key,
            escrow_key,
        }
    }
    fn resign_root_delegation(&mut self) {
        self.delegation.root_signature = self
            .root_key
            .sign(&self.delegation.signing_bytes(&self.root))
            .to_bytes();
        self.cut.delegation_digest = self.delegation.digest(&self.root);
        self.resign_cut();
    }
    fn resign_cut(&mut self) {
        self.cut.root_signature = self.root_key.sign(&self.cut.signing_bytes()).to_bytes();
        self.grant.current_cut_digest = self.cut.digest();
        self.grant.delegation_digest = self.delegation.digest(&self.root);
        self.resign_grant();
    }
    fn resign_escrow(&mut self) {
        self.escrow.escrow_signature = self
            .escrow_key
            .sign(&self.escrow.signing_bytes())
            .to_bytes();
        self.escrow_archive = self.escrow.receipt_bytes();
        self.grant.source_escrow_receipt_digest = self.escrow.digest();
        self.grant.original_record_id = self.escrow.original_record_id.clone();
        self.grant.original_authentication_digest = self.escrow.original_authentication_digest;
        self.grant.previous_witness = self.escrow.previous_witness;
        self.grant.target_anchor = self.escrow.target_anchor;
        self.grant.target_event_digest = self.escrow.target_event_digest;
        self.resign_grant();
    }
    fn resign_grant(&mut self) {
        self.grant.recovery_signature = self
            .recovery_key
            .sign(&self.grant.signing_bytes())
            .to_bytes();
    }
    fn try_repair(&mut self, now: u64) -> Result<AckOnlyTestReceiptV1, AckOnlyRecoveryError> {
        reconcile_one_existing_ack_qualification(
            &self.ledger,
            &mut self.witness,
            &AckOnlyRecoveryProofV1 {
                root: &self.root,
                delegation: &self.delegation,
                cut: &self.cut,
                escrow: &self.escrow,
                independent_source_escrow_readback: &self.escrow_archive,
                grant: &self.grant,
                current_host_time_ms: now,
            },
        )
    }
}

#[test]
fn synthetically_root_delegated_ack_only_repairs_one_preexisting_record_without_ledger_append() {
    let mut f = Fixture::new();
    let before = fs::read(f.dir.join("ledger")).unwrap();
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    let receipt = f.try_repair(NOW).unwrap();
    assert_eq!(receipt.previous_witness.sequence, 0);
    assert_eq!(receipt.acknowledged_witness.sequence, 1);
    assert!(receipt.witness_synced);
    assert!(receipt.ledger_record_count_unchanged);
    assert!(receipt.qualification_only_no_product_authority);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
    assert_eq!(before, fs::read(f.dir.join("ledger")).unwrap());
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 1);
}
#[test]
fn exact_duplicate_recovery_grant_can_never_append_a_second_record() {
    let mut f = Fixture::new();
    let first = f.try_repair(NOW).unwrap();
    let after = fs::read(f.dir.join("witness")).unwrap();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::AlreadyAcknowledged)
    );
    assert_eq!(f.ledger.records().unwrap().len(), 1);
    assert_eq!(after, fs::read(f.dir.join("witness")).unwrap());
    assert_eq!(first.acknowledged_witness.sequence, 1);
}
#[test]
fn originally_root_signed_current_revocation_cut_is_required() {
    let mut f = Fixture::new();
    f.cut.root_signature[0] ^= 1;
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidCurrentRevocationCut)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn stale_or_revoked_root_cut_denies_even_signed_complete_escrow() {
    let mut f = Fixture::new();
    f.cut.issued_at = NOW - 31_000;
    f.resign_cut();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidCurrentRevocationCut)
    );
    f.cut.issued_at = NOW - 1_000;
    f.cut.original_event_not_revoked = false;
    f.resign_cut();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidCurrentRevocationCut)
    );
}
#[test]
fn expired_current_recovery_grant_denies_without_an_expired_actor_clock_rewind() {
    let mut f = Fixture::new();
    f.grant.expires_at = NOW - 1;
    f.resign_grant();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidRecoveryGrant)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn new_recovery_authority_must_be_separate_from_original_event_and_escrow() {
    let mut f = Fixture::new();
    f.delegation.authority_controller_id = f.delegation.escrow_controller_id.clone();
    f.resign_root_delegation();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidDelegation)
    );
    f.delegation.authority_controller_id = id("original-generator.controller");
    f.resign_root_delegation();
    // The now-independent delegation is still the same original actor
    // controller, which must never self-issue its own witness-repair grant.
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::ActorControllerNotIndependent)
    );
}
#[test]
fn source_time_escrow_must_precede_the_original_append_even_with_valid_signature() {
    let mut f = Fixture::new();
    f.escrow.escrow_held_at = f.escrow.original_append_started_at + 1;
    f.resign_escrow();
    assert_eq!(f.try_repair(NOW), Err(AckOnlyRecoveryError::InvalidEscrow));
}
#[test]
fn missing_or_modified_independent_source_time_escrow_archive_denied() {
    let mut f = Fixture::new();
    f.escrow_archive.clear();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::MissingIndependentEscrowReadback)
    );
    f.escrow_archive = f.escrow.receipt_bytes();
    f.escrow_archive[5] ^= 1;
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::MissingIndependentEscrowReadback)
    );
}
#[test]
fn root_forgery_and_root_expiration_denied() {
    let mut f = Fixture::new();
    f.root.verifying_key = SigningKey::from_bytes(&[77; 32]).verifying_key().to_bytes();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidDelegation)
    );
    f.root.verifying_key = f.root_key.verifying_key().to_bytes();
    f.root.expires_at = NOW - 1;
    assert_eq!(f.try_repair(NOW), Err(AckOnlyRecoveryError::InvalidRootPin));
}
#[test]
fn mismatched_original_durable_event_digest_rejected_without_any_witness_change() {
    let mut f = Fixture::new();
    f.escrow.target_event_digest = dg("forged-original-native-record");
    f.resign_escrow();
    // All test signers re-signed a forged grant. Exact durable original
    // record verification, not merely signature validity, must still refuse.
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn wrong_binding_or_wrong_expected_previous_frontier_denied() {
    let mut f = Fixture::new();
    f.root.ledger_binding = dg("another-user-ledger-binding");
    assert!(f.try_repair(NOW).is_err());
    f.root.ledger_binding = f.ledger.binding_digest();
    f.escrow.previous_witness.chain_digest = dg("different-original-predecessor");
    f.resign_escrow();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord)
    );
}
#[test]
fn a_legacy_unauthenticated_original_event_is_not_recoverable_through_this_qualification() {
    let mut f = Fixture::new_event(true);
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::UnsupportedOriginalEventKind)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn two_unwitnessed_native_events_cannot_be_repaired_with_one_grant() {
    let mut f = Fixture::new();
    let first = f.ledger.records().unwrap()[0].chain_digest;
    let second = synthetic_decision("episode-2", "original-generator.controller");
    f.ledger.append(first, second).unwrap();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn switched_signed_grant_nonce_refused_even_when_all_other_fields_match() {
    let mut f = Fixture::new();
    f.grant.grant_nonce = dg("unapproved-different-one-time-nonce");
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidRecoveryGrant)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
#[test]
fn real_original_product_key_enrollment_is_not_conferred_by_local_test_root() {
    let mut f = Fixture::new();
    let r = f.try_repair(NOW).unwrap();
    assert!(r.qualification_only_no_product_authority);
}
