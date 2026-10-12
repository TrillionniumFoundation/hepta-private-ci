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
// Only synthetic local typed V2 Outcome; no broker price or execution PnL.
fn synthetic_terminal_outcome() -> LedgerEvent {
    LedgerEvent::AuthenticatedOutcomeV2(crate::AuthenticatedOutcomeRecordV2 {
        record_id: id("outcome-episode-1"),
        outcome_id: id("outcome-label-test-only"),
        episode_id: id("episode-1"),
        observer_id: id("synthetic-obs"),
        observer_controller_id: id("original-observer.controller"),
        observer_credential_chain_digest: dg("observer-credential"),
        observer_signing_key_digest: dg("observer-key"),
        observer_scope_digest: dg("synthetic-ledger-scope"),
        observer_authority_epoch: 3,
        observed_at: Some(40_000),
        value: Some(codex_hepta_types::FixedQ32::ONE),
        unit_profile_digest: dg("PRICE_BPS_SYNTHETIC_NOT_NET_PNL"),
        support_digest: dg("synthetic-outcome-support"),
        latest_observable_at: 41_000,
        expected_delay_profile_digest: dg("synthetic-horizon"),
        terminality: crate::AuthenticatedOutcomeTerminality::Terminal,
        censoring_reason: None,
        correction_predecessor: None,
        finalized_at: Some(41_500),
        authentication_digest: dg("independent-observer-authentication"),
    })
}

struct Fixture {
    dir: PathBuf,
    ledger: DurableLedger,
    witness: LedgerWitnessStore,
    nonce_journal: crate::AckOnlyGrantNonceJournalV1,
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
        let nonce_dir = dir.join("owner-nonce-journal");
        fs::create_dir(&nonce_dir).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&nonce_dir, fs::Permissions::from_mode(0o700)).unwrap();
        }
        let nonce_journal =
            crate::AckOnlyGrantNonceJournalV1::open_preexisting(&nonce_dir).unwrap();
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
            nonce_journal,
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
    fn prepare_one_unacknowledged_terminal_outcome(&mut self) {
        let first = self.ledger.records().unwrap()[0].clone();
        let prior = LedgerAnchor {
            sequence: first.sequence.get(),
            chain_digest: first.chain_digest,
        };
        let before = self.witness.frontier().unwrap();
        self.witness
            .advance(
                before,
                LedgerWitnessFrontier {
                    anchor: prior,
                    segment: None,
                    sealed: false,
                },
            )
            .unwrap();
        let receipt = self
            .ledger
            .append(first.chain_digest, synthetic_terminal_outcome())
            .unwrap();
        assert_eq!(receipt.sequence.get(), 2);
        self.escrow.previous_witness = prior;
        self.escrow.target_anchor = LedgerAnchor {
            sequence: 2,
            chain_digest: receipt.chain_digest,
        };
        self.escrow.target_event_digest = receipt.event_digest;
        self.escrow.original_record_id = id("outcome-episode-1");
        self.escrow.original_authentication_digest = dg("independent-observer-authentication");
        self.escrow.original_actor_evidence_issued_at = 42_000;
        self.escrow.escrow_held_at = 43_000;
        self.escrow.original_append_started_at = 44_000;
        self.resign_escrow();
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
            &mut self.nonce_journal,
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
    assert!(!receipt.reserved_event_target_and_nonce_receipt.is_zero());
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

#[test]
fn exact_authenticated_terminal_outcome_ack_only_never_appends_new_ledger_event() {
    let mut f = Fixture::new();
    f.prepare_one_unacknowledged_terminal_outcome();
    assert_eq!(f.ledger.records().unwrap().len(), 2);
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 1);
    let original_bytes = fs::read(f.dir.join("ledger")).unwrap();
    let receipt = f.try_repair(NOW).expect("exact original typed Outcome ACK");
    assert_eq!(receipt.previous_witness.sequence, 1);
    assert_eq!(receipt.acknowledged_witness.sequence, 2);
    assert!(receipt.ledger_record_count_unchanged);
    assert_eq!(original_bytes, fs::read(f.dir.join("ledger")).unwrap());
    assert_eq!(f.ledger.records().unwrap().len(), 2);
    let witnessed = fs::read(f.dir.join("witness")).unwrap();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::AlreadyAcknowledged)
    );
    assert_eq!(witnessed, fs::read(f.dir.join("witness")).unwrap());
}

#[test]
fn previously_acknowledged_terminal_outcome_cold_reopens_new_native_file_handles() {
    let mut f = Fixture::new();
    f.prepare_one_unacknowledged_terminal_outcome();
    let binding = f.ledger.binding_digest();
    let escrowed = f.try_repair(NOW).unwrap();
    assert_eq!(escrowed.acknowledged_witness.sequence, 2);
    let ledger = fs::read(f.dir.join("ledger")).unwrap();
    let witness = fs::read(f.dir.join("witness")).unwrap();
    let serial = NEXT.fetch_add(1, Ordering::Relaxed);
    let recovered_dir = std::env::temp_dir().join(format!(
        "hepta-ackonly-outcome-cold-files-{}-{serial}",
        std::process::id()
    ));
    fs::create_dir(&recovered_dir).unwrap();
    fs::write(recovered_dir.join("ledger"), &ledger).unwrap();
    fs::write(recovered_dir.join("witness"), &witness).unwrap();
    drop(f);
    let witnessed = LedgerWitnessStore::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(recovered_dir.join("witness"))
            .unwrap(),
        binding,
    )
    .unwrap();
    let anchor = witnessed.frontier().unwrap().anchor;
    assert_eq!(anchor.sequence, 2);
    let recovered = DurableLedger::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(recovered_dir.join("ledger"))
            .unwrap(),
        binding,
        16,
        crate::LedgerRecovery::Acknowledged(anchor),
    )
    .unwrap();
    assert_eq!(recovered.records().unwrap().len(), 2);
    assert_eq!(
        recovered.records().unwrap()[1].chain_digest,
        anchor.chain_digest
    );
    assert!(matches!(
        &recovered.records().unwrap()[1].event,
        LedgerEvent::AuthenticatedOutcomeV2(_)
    ));
    assert_eq!(fs::read(recovered_dir.join("ledger")).unwrap(), ledger);
    assert_eq!(fs::read(recovered_dir.join("witness")).unwrap(), witness);
    drop(recovered);
    drop(witnessed);
    fs::remove_dir_all(recovered_dir).unwrap();
}

#[test]
fn terminal_outcome_recovery_authority_cannot_share_decision_generator_controller() {
    let mut f = Fixture::new();
    f.prepare_one_unacknowledged_terminal_outcome();
    f.delegation.authority_controller_id = id("original-generator.controller");
    f.resign_root_delegation();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::ActorControllerNotIndependent)
    );
    f.delegation.authority_controller_id = id("RECOVERY.CONTROLLER");
    f.delegation.escrow_controller_id = id("original-generator.controller");
    f.resign_root_delegation();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::ActorControllerNotIndependent)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 1);
}

#[test]
fn different_original_policy_objective_cannot_receive_recovery_ack() {
    let mut f = Fixture::new();
    f.root.objective_digest = dg("new-different-objective-not-source");
    f.resign_root_delegation();
    f.escrow.objective_digest = f.root.objective_digest;
    f.resign_escrow();
    f.grant.objective_digest = f.root.objective_digest;
    f.resign_grant();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[test]
fn recovery_nonce_is_durable_before_witness_advances_and_cannot_be_reused() {
    let mut f = Fixture::new();
    let folder = f.dir.join("owner-nonce-journal");
    assert!(fs::read_dir(&folder).unwrap().next().is_none());
    f.try_repair(NOW).unwrap();
    let entries = fs::read_dir(&folder)
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(entries.len(), 2, "target and nonce both durably reserved");
    let names = entries
        .iter()
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect::<Vec<_>>();
    assert_eq!(names.iter().filter(|x| x.starts_with("target-")).count(), 1);
    assert_eq!(names.iter().filter(|x| x.starts_with("nonce-")).count(), 1);
    for item in &entries {
        assert!(!fs::read(item.path()).unwrap().is_empty());
    }
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 1);
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::AlreadyAcknowledged)
    );
    assert_eq!(entries.len(), fs::read_dir(&folder).unwrap().count());
}

#[test]
fn interrupted_nonce_reservation_must_hold_instead_of_late_witness_ack() {
    let mut f = Fixture::new();
    // Simulates a crash AFTER the nonce reservation file was fsynced
    // and BEFORE the independent Witness was permitted to advance.
    f.nonce_journal.reserve(&f.grant).unwrap();
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[test]
fn same_grant_nonce_in_another_clone_with_same_owner_store_is_rejected() {
    let mut f = Fixture::new();
    let original = f.nonce_journal.reserve(&f.grant).unwrap();
    let folder = f.dir.join("owner-nonce-journal");
    let mut opened = crate::AckOnlyGrantNonceJournalV1::open_preexisting(&folder).unwrap();
    assert_eq!(
        opened.reserve(&f.grant),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert!(!original.is_zero());
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[test]
fn invalid_signature_cannot_consume_an_owner_held_nonce_or_write_witness() {
    let mut f = Fixture::new();
    f.grant.recovery_signature[13] ^= 1;
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::InvalidRecoveryGrant)
    );
    assert!(
        fs::read_dir(f.dir.join("owner-nonce-journal"))
            .unwrap()
            .next()
            .is_none()
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[cfg(unix)]
#[test]
fn nonce_directory_must_preexist_be_owner_private_and_not_symlink() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let f = Fixture::new();
    let path = f.dir.join("too-open-dir");
    fs::create_dir(&path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(matches!(
        crate::AckOnlyGrantNonceJournalV1::open_preexisting(&path),
        Err(AckOnlyRecoveryError::NonceStoreUnavailable)
    ));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let alias = f.dir.join("symlink-to-owner-nonce");
    symlink(f.dir.join("owner-nonce-journal"), &alias).unwrap();
    assert!(matches!(
        crate::AckOnlyGrantNonceJournalV1::open_preexisting(&alias),
        Err(AckOnlyRecoveryError::NonceStoreUnavailable)
    ));
}

#[test]
fn child_only_readonly_original_native_ledger_recovery() {
    // Spawned by the parent test using the separately launched Rust test
    // executable as a REAL new process. No production source is read.
    let Ok(root) = std::env::var("HEPTA_ACKONLY_CHILD_TEST_DIR") else {
        return;
    };
    let path = PathBuf::from(root);
    let mode = std::env::var("HEPTA_ACKONLY_CHILD_TEST_MODE").unwrap();
    assert!(["pending", "acked"].contains(&mode.as_str()));
    let binding = dg("test-only-ackonly-ledger-binding");
    let witness_bytes = fs::read(path.join("witness")).unwrap();
    let ledger_bytes = fs::read(path.join("ledger")).unwrap();
    let witness = LedgerWitnessStore::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path.join("witness"))
            .unwrap(),
        binding,
    )
    .unwrap();
    let anchor = witness.frontier().unwrap().anchor;
    assert_eq!(anchor.sequence, if mode == "pending" { 1 } else { 2 });
    let recovered = DurableLedger::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path.join("ledger"))
            .unwrap(),
        binding,
        16,
        crate::LedgerRecovery::Acknowledged(anchor),
    )
    .unwrap();
    let records = recovered.records().unwrap();
    assert_eq!(records.len(), 2);
    assert_eq!(records[1].sequence.get(), 2);
    assert!(matches!(
        &records[1].event,
        LedgerEvent::AuthenticatedOutcomeV2(_)
    ));
    if mode == "acked" {
        assert_eq!(anchor.chain_digest, records[1].chain_digest);
    } else {
        assert_eq!(anchor.chain_digest, records[0].chain_digest);
    }
    assert_eq!(fs::read(path.join("ledger")).unwrap(), ledger_bytes);
    assert_eq!(fs::read(path.join("witness")).unwrap(), witness_bytes);
}

fn new_process_readback(mode: &str) {
    let mut f = Fixture::new();
    f.prepare_one_unacknowledged_terminal_outcome();
    if mode == "acked" {
        f.try_repair(NOW).unwrap();
    }
    let seq = if mode == "pending" { 1 } else { 2 };
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, seq);
    let id = NEXT.fetch_add(1, Ordering::Relaxed);
    let dir = std::env::temp_dir().join(format!(
        "hepta-ackonly-native-subproc-{}-{id}",
        std::process::id()
    ));
    fs::create_dir(&dir).unwrap();
    let original_ledger = fs::read(f.dir.join("ledger")).unwrap();
    let original_witness = fs::read(f.dir.join("witness")).unwrap();
    fs::write(dir.join("ledger"), &original_ledger).unwrap();
    fs::write(dir.join("witness"), &original_witness).unwrap();
    drop(f);
    let result = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "ack_only_recovery::tests::child_only_readonly_original_native_ledger_recovery",
            "--nocapture",
        ])
        .env("HEPTA_ACKONLY_CHILD_TEST_DIR", &dir)
        .env("HEPTA_ACKONLY_CHILD_TEST_MODE", mode)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(String::from_utf8_lossy(&result.stdout).contains("1 passed"));
    assert_eq!(fs::read(dir.join("ledger")).unwrap(), original_ledger);
    assert_eq!(fs::read(dir.join("witness")).unwrap(), original_witness);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn genuine_second_native_process_recovers_one_outcome_unwitnessed_without_changing_source() {
    new_process_readback("pending");
}

#[test]
fn genuine_second_native_process_recovers_acked_terminal_outcome_from_separate_files() {
    new_process_readback("acked");
}

#[test]
fn simultaneous_claims_for_same_nonce_only_one_wins_in_one_owner_directory() {
    let f = Fixture::new();
    let grant = f.grant.clone();
    let owner_dir = f.dir.join("owner-nonce-journal");
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
    // Eagerly start both threads before releasing the barrier.
    // A lazy iterator here would deadlock with a 3-party barrier.
    let mut tasks = Vec::with_capacity(2);
    for _ in 0..2 {
        let dir = owner_dir.clone();
        let same_grant = grant.clone();
        let start = barrier.clone();
        tasks.push(std::thread::spawn(move || {
            let mut store = crate::AckOnlyGrantNonceJournalV1::open_preexisting(&dir).unwrap();
            start.wait();
            store.reserve(&same_grant)
        }));
    }
    barrier.wait();
    let results = tasks
        .into_iter()
        .map(|t| t.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|r| matches!(
                r,
                Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
            ))
            .count(),
        1
    );
    assert_eq!(fs::read_dir(owner_dir).unwrap().count(), 2);
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[test]
fn existing_indeterminate_reservation_is_never_cleared_by_new_store_open() {
    let mut f = Fixture::new();
    let dir = f.dir.join("owner-nonce-journal");
    let token = f.nonce_journal.reserve(&f.grant).unwrap();
    assert!(!token.is_zero());
    // The prior actor's reservation file was synced, and another
    // process opens the original owner-pinned directory after restart.
    let mut next = crate::AckOnlyGrantNonceJournalV1::open_preexisting(&dir).unwrap();
    assert_eq!(
        next.reserve(&f.grant),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[cfg(unix)]
#[test]
fn replaced_owner_nonce_path_is_not_an_authorized_reservation_store() {
    use std::os::unix::fs::symlink;
    let mut f = Fixture::new();
    let old = f.dir.join("owner-nonce-journal");
    let renamed = f.dir.join("owner-nonce-journal-original");
    fs::rename(&old, &renamed).unwrap();
    let attacker = f.dir.join("new-root-not-original-owner");
    fs::create_dir(&attacker).unwrap();
    symlink(&attacker, &old).unwrap();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::NonceStoreUnavailable)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(fs::read_dir(&renamed).unwrap().count(), 0);
    assert_eq!(fs::read_dir(&attacker).unwrap().count(), 0);
}

#[test]
fn child_only_fsync_nonce_then_deliberately_terminate_before_any_witness_write() {
    let Ok(dir) = std::env::var("HEPTA_ACKONLY_CHILD_NONCE_DIR") else {
        return;
    };
    // Entirely separate process reserves the SAME original synthetic
    // grant nonce. The child then exits without giving the parent a
    // witness ACK. Not a physical hardware power-loss test.
    let f = Fixture::new();
    let mut store = crate::AckOnlyGrantNonceJournalV1::open_preexisting(Path::new(&dir)).unwrap();
    store.reserve(&f.grant).unwrap();
    drop(f);
    std::process::exit(47);
}

#[test]
fn another_native_process_exits_after_nonce_fsync_then_parent_must_hold() {
    let mut f = Fixture::new();
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    let dir = f.dir.join("owner-nonce-journal");
    let report=std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact",
            "ack_only_recovery::tests::child_only_fsync_nonce_then_deliberately_terminate_before_any_witness_write",
            "--nocapture"])
        .env("HEPTA_ACKONLY_CHILD_NONCE_DIR",&dir)
        .output().unwrap();
    assert_eq!(
        report.status.code(),
        Some(47),
        "{}",
        String::from_utf8_lossy(&report.stderr)
    );
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 2);
    // Child died after durable grant reservation: reusing the same
    // original proof is not automatically permitted to finish an ACK.
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[cfg(unix)]
#[test]
fn atomic_openat_dirfd_blocks_exact_between_check_and_open_path_race() {
    use std::os::unix::fs::PermissionsExt;
    let mut f = Fixture::new();
    let path = f.dir.join("owner-nonce-journal");
    let saved = f.dir.join("owner-nonce-journal-RENAMED-ORIGINAL");
    let replacement = path.clone();
    let grant = f.grant.clone();
    let result = f.nonce_journal.reserve_with_test_rebind(&grant, move || {
        // Controlled deterministic TOCTOU that happens AFTER the live
        // owner directory identity check and BEFORE the file open.
        fs::rename(&replacement, &saved).unwrap();
        fs::create_dir(&replacement).unwrap();
        fs::set_permissions(&replacement, fs::Permissions::from_mode(0o700)).unwrap();
    });
    assert_eq!(result, Err(AckOnlyRecoveryError::NonceStoreUnavailable));
    assert_eq!(
        fs::read_dir(&path).unwrap().count(),
        0,
        "path-swapped replacement never receives a signed nonce"
    );
    let kept = f.dir.join("owner-nonce-journal-RENAMED-ORIGINAL");
    assert_eq!(
        fs::read_dir(&kept).unwrap().count(),
        2,
        "pinned original openat dirfd receives both target and nonce reservations"
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[cfg(unix)]
#[test]
fn preexisting_nonce_filename_symlink_is_not_followed_or_overwritten() {
    use std::os::unix::fs::symlink;
    let mut f = Fixture::new();
    let mut filename = String::from("nonce-");
    for byte in f.grant.grant_nonce.as_array() {
        use std::fmt::Write as _;
        write!(filename, "{byte:02x}").unwrap();
    }
    let trap = f.dir.join("attacker-controlled-file");
    let nonce_path = f.dir.join("owner-nonce-journal").join(&filename);
    symlink(&trap, &nonce_path).unwrap();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate)
    );
    assert!(
        !trap.exists(),
        "O_EXCL + NOFOLLOW must not follow nonce symlink"
    );
    assert!(nonce_path.is_symlink());
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[test]
fn second_distinct_signed_nonce_for_same_durable_event_is_denied_before_ack() {
    let mut f = Fixture::new();
    let first = f.nonce_journal.reserve(&f.grant).unwrap();
    assert!(!first.is_zero());
    let original_ledger = fs::read(f.dir.join("ledger")).unwrap();
    let original_witness = fs::read(f.dir.join("witness")).unwrap();

    // A test RecoveryAuthority signs a genuinely different, valid nonce
    // for the same record/previous Witness. Prior nonce-only journal
    // incorrectly considered this independent event recovery eligible.
    f.grant.grant_nonce = dg("second-authenticated-grant-nonce-same-original-event");
    f.resign_grant();
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert_eq!(
        fs::read_dir(f.dir.join("owner-nonce-journal"))
            .unwrap()
            .count(),
        2
    );
    assert_eq!(fs::read(f.dir.join("ledger")).unwrap(), original_ledger);
    assert_eq!(fs::read(f.dir.join("witness")).unwrap(), original_witness);
}

#[test]
fn identical_nonce_on_different_original_target_cannot_pass_local_owner_journal() {
    let mut f = Fixture::new();
    let first = f.nonce_journal.reserve(&f.grant).unwrap();
    assert!(!first.is_zero());
    let mut other = f.grant.clone();
    other.original_record_id = id("another-completely-different-source-record");
    other.target_event_digest = dg("different-fabricated-target-event");
    other.target_anchor.chain_digest = dg("different-original-chain-anchor");
    // The same grant nonce cannot be spent to recover this other target,
    // even if different target reservation is fsynced first.
    assert_eq!(
        f.nonce_journal.reserve(&other),
        Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate)
    );
    let store = f.dir.join("owner-nonce-journal");
    assert_eq!(
        fs::read_dir(store).unwrap().count(),
        3,
        "both targets remain reserved, original nonce only"
    );
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[test]
fn child_only_reserve_exact_target_then_exit_before_nonce_file() {
    let Ok(dir) = std::env::var("HEPTA_ACKONLY_CHILD_TARGET_DIR") else {
        return;
    };
    let f = Fixture::new();
    let mut reopened =
        crate::AckOnlyGrantNonceJournalV1::open_preexisting(Path::new(&dir)).unwrap();
    // A distinct native Rust PROCESS exits AFTER target file and
    // directory fsync, BEFORE any nonce file can be created. No file
    // deletion, retries, or partial success claims.
    let _ = reopened.reserve_with_test_target_fsync_exit(&f.grant, || {
        std::process::exit(49);
    });
    panic!("child must have exited at target fsync");
}

#[test]
fn crashed_process_between_target_and_nonce_prevents_alternate_signed_grant() {
    let mut f = Fixture::new();
    let dir = f.dir.join("owner-nonce-journal");
    let call = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "ack_only_recovery::tests::child_only_reserve_exact_target_then_exit_before_nonce_file",
            "--nocapture",
        ])
        .env("HEPTA_ACKONLY_CHILD_TARGET_DIR", &dir)
        .output()
        .unwrap();
    assert_eq!(
        call.status.code(),
        Some(49),
        "{}",
        String::from_utf8_lossy(&call.stderr)
    );
    let list = fs::read_dir(&dir)
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(list.len(), 1);
    let name = list[0].file_name().to_string_lossy().to_string();
    assert!(name.starts_with("target-"));
    assert!(!fs::read(list[0].path()).unwrap().is_empty());
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
    f.grant.grant_nonce = dg("valid-different-grant-nonce-after-crashed-target");
    f.resign_grant();
    // The ORIGINAL already fsynced target key still denies even a
    // different valid nonce after the first process died.
    assert_eq!(
        f.try_repair(NOW),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 1);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
}

#[test]
fn two_concurrent_distinct_signed_grants_for_same_target_reserve_once() {
    let f = Fixture::new();
    let root = f.dir.join("owner-nonce-journal");
    let one = f.grant.clone();
    let mut two = f.grant.clone();
    two.grant_nonce = dg("different-authenticated-grant-nonce-same-target-race");
    let start = std::sync::Arc::new(std::sync::Barrier::new(3));
    let mut threads = Vec::new();
    for grant in [one, two] {
        let dir = root.clone();
        let barrier = start.clone();
        threads.push(std::thread::spawn(move || {
            let mut journal = crate::AckOnlyGrantNonceJournalV1::open_preexisting(&dir).unwrap();
            barrier.wait();
            journal.reserve(&grant)
        }));
    }
    start.wait();
    let results = threads
        .into_iter()
        .map(|task| task.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|r| matches!(
                r,
                Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
            ))
            .count(),
        1
    );
    assert_eq!(fs::read_dir(root).unwrap().count(), 2);
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}

#[cfg(unix)]
#[test]
fn event_target_and_nonce_files_created_private_with_distinct_domain_bound_bytes() {
    use std::os::unix::fs::PermissionsExt;
    let mut f = Fixture::new();
    let path = f.dir.join("owner-nonce-journal");
    f.nonce_journal.reserve(&f.grant).unwrap();
    let mut target_file = None;
    let mut nonce_file = None;
    for item in fs::read_dir(&path).unwrap() {
        let item = item.unwrap();
        assert_eq!(item.metadata().unwrap().permissions().mode() & 0o777, 0o600);
        let file_data = fs::read(item.path()).unwrap();
        let file_name = item.file_name().to_string_lossy().to_string();
        if file_name.starts_with("target-") {
            assert!(file_data.starts_with(b"hepta.ackonly-qualification-event-target-once.v1"));
            target_file = Some(file_data);
        } else if file_name.starts_with("nonce-") {
            assert!(file_data.starts_with(b"hepta.ackonly-qualification-reserved-once.v2"));
            nonce_file = Some(file_data);
        } else {
            panic!("unrecognized reservation file");
        }
    }
    assert!(target_file.is_some());
    assert!(nonce_file.is_some());
    assert_ne!(target_file, nonce_file);
    assert_eq!(fs::read_dir(path).unwrap().count(), 2);
}

#[cfg(unix)]
#[test]
fn symlink_at_event_target_filename_denied_before_creating_nonce_or_witness() {
    use std::os::unix::fs::symlink;
    let mut baseline = Fixture::new();
    baseline.nonce_journal.reserve(&baseline.grant).unwrap();
    let original = baseline.dir.join("owner-nonce-journal");
    let target_filename = fs::read_dir(&original)
        .unwrap()
        .filter_map(Result::ok)
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .find(|name| name.starts_with("target-"))
        .unwrap();
    let mut victim = Fixture::new();
    let path = victim.dir.join("owner-nonce-journal");
    let would_be_target = victim.dir.join("attack-target-outside-directory");
    symlink(&would_be_target, path.join(target_filename)).unwrap();
    assert_eq!(
        victim.try_repair(NOW),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
    );
    assert!(!would_be_target.exists());
    assert_eq!(fs::read_dir(path).unwrap().count(), 1);
    assert_eq!(victim.witness.frontier().unwrap().anchor.sequence, 0);
    assert_eq!(victim.ledger.records().unwrap().len(), 1);
}

#[cfg(unix)]
#[test]
fn child_only_replay_competing_signed_event_nonce_in_other_native_process() {
    let Ok(owner) = std::env::var("HEPTA_ACKONLY_TARGET_RACE_OWNER") else {
        return;
    };
    let flag = std::env::var("HEPTA_ACKONLY_TARGET_RACE_VARIANT").unwrap();
    let start = std::env::var("HEPTA_ACKONLY_TARGET_RACE_BARRIER").unwrap();
    assert!(flag == "first" || flag == "different-grant");
    let mut f = Fixture::new();
    if flag == "different-grant" {
        f.grant.grant_nonce = dg("another-physically-concurrent-original-event-grant");
        f.grant.grant_id = id("another-concurrent-Grant-for-same-original-target");
        f.resign_grant();
    }
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while !Path::new(&start).exists() {
        assert!(
            std::time::Instant::now() < deadline,
            "child did not receive independent starting barrier"
        );
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
    let mut store = crate::AckOnlyGrantNonceJournalV1::open_preexisting(Path::new(&owner)).unwrap();
    let result = store.reserve(&f.grant);
    drop(store);
    drop(f);
    match result {
        Ok(_) => std::process::exit(0),
        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate) => std::process::exit(51),
        unexpected => panic!("unrecognized concurrent native event result: {unexpected:?}"),
    }
}

#[cfg(unix)]
#[test]
fn two_separate_rust_processes_compete_on_one_event_with_different_nonces() {
    let f = Fixture::new();
    let directory = f.dir.join("owner-nonce-journal");
    let barrier = f.dir.join("both-processes-start-now");
    let child = std::env::current_exe().unwrap();
    let mut a=std::process::Command::new(&child)
        .args(["--exact",
            "ack_only_recovery::tests::child_only_replay_competing_signed_event_nonce_in_other_native_process",
            "--nocapture"])
        .env("HEPTA_ACKONLY_TARGET_RACE_OWNER",&directory)
        .env("HEPTA_ACKONLY_TARGET_RACE_VARIANT","first")
        .env("HEPTA_ACKONLY_TARGET_RACE_BARRIER",&barrier)
        .spawn().unwrap();
    let mut b=std::process::Command::new(&child)
        .args(["--exact",
            "ack_only_recovery::tests::child_only_replay_competing_signed_event_nonce_in_other_native_process",
            "--nocapture"])
        .env("HEPTA_ACKONLY_TARGET_RACE_OWNER",&directory)
        .env("HEPTA_ACKONLY_TARGET_RACE_VARIANT","different-grant")
        .env("HEPTA_ACKONLY_TARGET_RACE_BARRIER",&barrier)
        .spawn().unwrap();
    // Release both independently running processes together. Neither
    // receives any production credentials or touches source Ledger.
    fs::write(&barrier, b"go").unwrap();
    let statuses = [a.wait().unwrap().code(), b.wait().unwrap().code()];
    let successes = statuses.iter().filter(|s| **s == Some(0)).count();
    let rejected = statuses.iter().filter(|s| **s == Some(51)).count();
    assert_eq!(successes, 1, "exactly one independent process may reserve");
    assert_eq!(rejected, 1, "other differently signed grant is rejected");
    assert_eq!(fs::read_dir(directory).unwrap().count(), 2);
    assert_eq!(f.ledger.records().unwrap().len(), 1);
    assert_eq!(f.witness.frontier().unwrap().anchor.sequence, 0);
}
