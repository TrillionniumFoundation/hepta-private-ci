use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CandidateSetCompleteness;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}
fn id(value: &str) -> StableId {
    must(StableId::new(value))
}
// Inspect through the owning locked handle. Other handles may be denied by
// mandatory byte-range locking on some platforms. Restore its shared offset.
fn locked_bytes(ledger: &DurableLedger) -> Vec<u8> {
    let mut file = must(ledger.file.try_clone());
    let position = must(file.stream_position());
    must(file.seek(SeekFrom::Start(0)));
    let mut bytes = Vec::new();
    must(file.read_to_end(&mut bytes));
    must(file.seek(SeekFrom::Start(position)));
    bytes
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"host-verified-scope-purpose-epoch")
}
fn decision() -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision-1"),
        episode_id: id("episode-1"),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy-1"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: must(ProbabilityQ32::from_raw(/*raw*/ 1 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"decision-support"),
    })
}
fn outcome() -> LedgerEvent {
    LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("observation-1"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: Digest32::of_bytes(b"observed-outcome"),
    })
}
fn credit() -> LedgerEvent {
    LedgerEvent::Credit(CreditAssignment {
        record_id: id("assignment-1"),
        credit_id: id("credit-1"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        target_artifact_id: id("artifact-1"),
        allocator_id: id("allocator-1"),
        credit: FixedQ32::ONE,
        support_digest: Digest32::of_bytes(b"credit-support"),
    })
}
fn revocation() -> LedgerEvent {
    LedgerEvent::Revocation(Revocation {
        record_id: id("revocation-1"),
        target_record_id: id("decision-1"),
        authority_id: id("privacy-owner"),
        reason_digest: Digest32::of_bytes(b"authorized-revocation"),
    })
}
struct Fixture {
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-causal-journal-{}-{serial}",
            std::process::id()
        ));
        must(fs::create_dir(&root));
        must(
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(root.join("ledger")),
        );
        Self { root }
    }
    fn path(&self) -> PathBuf {
        self.root.join("ledger")
    }
    fn file(&self) -> File {
        must(OpenOptions::new().read(true).write(true).open(self.path()))
    }
    fn create(&self) -> DurableLedger {
        must(DurableLedger::create(
            self.file(),
            binding(),
            /*max_records*/ 16,
        ))
    }
    fn recover(&self, recovery: LedgerRecovery) -> Result<DurableLedger, DurableLedgerError> {
        DurableLedger::recover(self.file(), binding(), /*max_records*/ 16, recovery)
    }
    fn write_events(&self, events: Vec<LedgerEvent>) -> LedgerSnapshot {
        let mut ledger = self.create();
        let mut predecessor = Digest32::ZERO;
        for event in events {
            predecessor = must(ledger.append(predecessor, event)).chain_digest;
        }
        must(ledger.snapshot())
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn anchored(snapshot: &LedgerSnapshot) -> LedgerRecovery {
    LedgerRecovery::Acknowledged(LedgerAnchor {
        sequence: snapshot.records().len() as u64,
        chain_digest: snapshot.head_digest,
    })
}

#[test]
fn persisted_causal_events_replay_exact_core_and_revocation_excludes_descendants() {
    let fixture = Fixture::new();
    let events = vec![decision(), outcome(), credit(), revocation()];
    let mut expected = LearningLedger::new();
    for event in &events {
        must(expected.append(event.clone()));
    }
    let snapshot = fixture.write_events(events);
    assert_eq!(snapshot, expected.snapshot());
    let reopened = must(fixture.recover(anchored(&snapshot)));
    assert_eq!(must(reopened.snapshot()), snapshot);
    assert_eq!(must(reopened.active_records()), expected.active_records());
    assert!(
        must(reopened.active_records())
            .iter()
            .all(|row| matches!(row.event, LedgerEvent::Revocation(_)))
    );
    assert_eq!(must(reopened.records()).len(), 4); // Logical exclusion, not physical erasure.
}

#[test]
fn canonical_candidate_permutation_retry_after_later_events_never_appends() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision(), outcome()]);
    let mut ledger = must(fixture.recover(anchored(&snapshot)));
    let before = locked_bytes(&ledger);
    let mut event = decision();
    if let LedgerEvent::Decision(value) = &mut event {
        value.candidate_ids.reverse();
    }
    let receipt = must(ledger.append(Digest32::ZERO, event));
    assert_eq!(
        receipt,
        AppendReceipt {
            disposition: AppendDisposition::IdempotentReplay,
            sequence: snapshot.records()[0].sequence,
            event_digest: snapshot.records()[0].event_digest,
            chain_digest: snapshot.records()[0].chain_digest
        }
    );
    assert_eq!(locked_bytes(&ledger), before);
    assert_eq!(must(ledger.snapshot()), snapshot);
}

#[test]
fn changed_identity_and_stale_predecessor_reject_without_mutating_either_store() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision()]);
    let mut ledger = must(fixture.recover(anchored(&snapshot)));
    let before = locked_bytes(&ledger);
    assert_eq!(
        ledger.append(Digest32::ZERO, outcome()),
        Err(DurableLedgerError::Conflict)
    );
    let mut changed = decision();
    if let LedgerEvent::Decision(value) = &mut changed {
        value.support_digest = Digest32::of_bytes(b"different");
    }
    assert!(matches!(
        ledger.append(Digest32::ZERO, changed),
        Err(DurableLedgerError::Semantic(LedgerError::IdentityConflict(
            _
        )))
    ));
    assert_eq!(must(ledger.snapshot()), snapshot);
    assert_eq!(locked_bytes(&ledger), before);
}

#[test]
fn invalid_causal_facts_and_oversized_candidate_sets_fail_before_io() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    let first = must(ledger.append(Digest32::ZERO, decision()));
    let before = locked_bytes(&ledger);
    let mut self_label = outcome();
    if let LedgerEvent::Outcome(value) = &mut self_label {
        value.observer_id = id("policy-1");
    }
    assert_eq!(
        ledger.append(first.chain_digest, self_label),
        Err(DurableLedgerError::Semantic(
            LedgerError::PolicySelfLabelsOutcome
        ))
    );
    assert!(matches!(
        ledger.append(first.chain_digest, credit()),
        Err(DurableLedgerError::Semantic(LedgerError::OutcomeNotFound(
            _
        )))
    ));
    let mut oversized = decision();
    if let LedgerEvent::Decision(value) = &mut oversized {
        value.candidate_ids = vec![id("same"); 129];
    }
    assert_eq!(
        ledger.append(first.chain_digest, oversized),
        Err(DurableLedgerError::Semantic(
            LedgerError::CandidateLimitExceeded
        ))
    );
    assert_eq!(locked_bytes(&ledger), before);
    assert_eq!(must(ledger.records()).len(), 1);
}

#[test]
fn acknowledged_revocation_cannot_disappear_as_a_valid_prefix_or_partial_tail() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision(), outcome(), credit(), revocation()]);
    let full = must(fs::read(fixture.path()));
    let last_size = must(encode_frame(&snapshot.records()[3])).len();
    let start = full.len() - last_size;
    for tail in 0..last_size {
        let damaged = &full[..start + tail];
        must(fs::write(fixture.path(), damaged));
        assert_eq!(
            fixture.recover(anchored(&snapshot)).err(),
            Some(DurableLedgerError::AcknowledgedHistoryMissing)
        );
        assert_eq!(must(fs::read(fixture.path())), damaged);
    }
}

#[test]
fn unacknowledged_partial_tail_recovers_exact_predecessor_at_every_cut() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision(), outcome()]);
    let full = must(fs::read(fixture.path()));
    let final_size = must(encode_frame(&snapshot.records()[1])).len();
    let start = full.len() - final_size;
    for tail in 0..=final_size {
        must(fs::write(fixture.path(), &full[..start + tail]));
        let recovered = must(fixture.recover(LedgerRecovery::Unacknowledged));
        assert_eq!(
            must(recovered.records()).len(),
            if tail == final_size { 2 } else { 1 }
        );
        assert_eq!(
            must(fs::metadata(fixture.path())).len(),
            if tail == final_size {
                full.len() as u64
            } else {
                start as u64
            }
        );
    }
}

#[test]
fn empty_recovery_is_not_creation_and_existing_history_is_never_overwritten() {
    let fixture = Fixture::new();
    assert_eq!(
        fixture.recover(LedgerRecovery::Unacknowledged).err(),
        Some(DurableLedgerError::MissingHeader)
    );
    assert_eq!(must(fs::metadata(fixture.path())).len(), 0);
    let snapshot = fixture.write_events(vec![decision()]);
    let bytes = must(fs::read(fixture.path()));
    assert_eq!(
        DurableLedger::create(fixture.file(), binding(), /*max_records*/ 16).err(),
        Some(DurableLedgerError::AlreadyInitialized)
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
    must(fs::write(fixture.path(), b""));
    assert_eq!(
        fixture.recover(anchored(&snapshot)).err(),
        Some(DurableLedgerError::MissingHeader)
    );
    assert_eq!(must(fs::metadata(fixture.path())).len(), 0);
}

#[test]
fn complete_corruption_invalid_length_prefix_and_rehashed_bad_lineage_reject() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision()]);
    let original = must(fs::read(fixture.path()));
    for index in [0, 12, HEADER - 1, HEADER, HEADER + 4, original.len() - 1] {
        let mut bytes = original.clone();
        bytes[index] ^= 1;
        must(fs::write(fixture.path(), &bytes));
        assert_eq!(
            fixture.recover(anchored(&snapshot)).err(),
            Some(DurableLedgerError::Corrupt)
        );
        assert_eq!(must(fs::read(fixture.path())), bytes);
    }
    let mut bytes = original;
    bytes[HEADER + 16] ^= 1; // Forged predecessor with a recomputed outer checksum.
    let end = bytes.len() - 32;
    let checksum = Digest32::of_bytes(&bytes[HEADER..end]);
    bytes[end..].copy_from_slice(checksum.as_array());
    must(fs::write(fixture.path(), &bytes));
    assert_eq!(
        fixture.recover(LedgerRecovery::Unacknowledged).err(),
        Some(DurableLedgerError::Corrupt)
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn wrong_anchor_never_repairs_tail_and_matching_early_anchor_preserves_later_frames() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision(), outcome()]);
    let complete = must(fs::read(fixture.path()));
    let mut bytes = complete.clone();
    bytes.extend_from_slice(&[1, 2, 3]);
    must(fs::write(fixture.path(), &bytes));
    let wrong = LedgerRecovery::Acknowledged(LedgerAnchor {
        sequence: 1,
        chain_digest: Digest32::of_bytes(b"wrong-history"),
    });
    assert_eq!(
        fixture.recover(wrong).err(),
        Some(DurableLedgerError::AnchorMismatch)
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
    let early = LedgerRecovery::Acknowledged(LedgerAnchor {
        sequence: 1,
        chain_digest: snapshot.records()[0].chain_digest,
    });
    let recovered = must(fixture.recover(early));
    assert_eq!(must(recovered.snapshot()), snapshot);
    assert_eq!(locked_bytes(&recovered), complete);
}

#[test]
fn exclusive_writer_fencing_releases_on_drop() {
    let fixture = Fixture::new();
    let first = fixture.create();
    assert_eq!(
        fixture.recover(LedgerRecovery::Unacknowledged).err(),
        Some(DurableLedgerError::Busy)
    );
    drop(first);
    assert_eq!(
        must(must(fixture.recover(LedgerRecovery::Unacknowledged)).records()).len(),
        0
    );
}

#[test]
fn record_quota_allows_exact_retry_but_not_a_new_event() {
    let fixture = Fixture::new();
    let mut ledger = must(DurableLedger::create(
        fixture.file(),
        binding(),
        /*max_records*/ 1,
    ));
    let first = must(ledger.append(Digest32::ZERO, decision()));
    let before = locked_bytes(&ledger);
    assert_eq!(
        ledger.append(first.chain_digest, outcome()),
        Err(DurableLedgerError::Capacity)
    );
    assert_eq!(
        must(ledger.append(Digest32::ZERO, decision())).disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(locked_bytes(&ledger), before);
}

#[test]
fn malformed_domain_anchor_and_excess_file_reject_without_changes() {
    let fixture = Fixture::new();
    for max_records in [0, MAX_RECORDS + 1, usize::MAX] {
        assert_eq!(
            DurableLedger::create(fixture.file(), binding(), max_records).err(),
            Some(DurableLedgerError::InvalidLimit)
        );
    }
    assert_eq!(
        DurableLedger::create(fixture.file(), Digest32::ZERO, /*max_records*/ 16).err(),
        Some(DurableLedgerError::InvalidBinding)
    );
    let snapshot = fixture.write_events(vec![decision()]);
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        DurableLedger::recover(
            fixture.file(),
            Digest32::of_bytes(b"other-scope"),
            /*max_records*/ 16,
            anchored(&snapshot)
        )
        .err(),
        Some(DurableLedgerError::BindingMismatch)
    );
    for sequence in [0, 17, u64::MAX] {
        let anchor = LedgerAnchor {
            sequence,
            chain_digest: snapshot.head_digest,
        };
        assert_eq!(
            fixture.recover(LedgerRecovery::Acknowledged(anchor)).err(),
            Some(DurableLedgerError::InvalidAnchor)
        );
    }
    assert_eq!(must(fs::read(fixture.path())), before);
    must(fixture.file().set_len(MAX_BYTES + 1));
    assert_eq!(
        fixture.recover(LedgerRecovery::Unacknowledged).err(),
        Some(DurableLedgerError::Capacity)
    );
    assert_eq!(must(fs::metadata(fixture.path())).len(), MAX_BYTES + 1);
}

#[cfg(target_os = "linux")]
#[test]
fn failed_write_poisons_memory_and_requires_recovery() {
    let fixture = Fixture::new();
    drop(fixture.create());
    let file = must(File::open(fixture.path()));
    let mut ledger = must(DurableLedger::recover(
        file,
        binding(),
        /*max_records*/ 16,
        LedgerRecovery::Unacknowledged,
    ));
    assert_eq!(
        ledger.append(Digest32::ZERO, decision()),
        Err(DurableLedgerError::Indeterminate)
    );
    assert_eq!(
        ledger.append(Digest32::ZERO, decision()),
        Err(DurableLedgerError::Poisoned)
    );
    assert_eq!(ledger.snapshot(), Err(DurableLedgerError::Poisoned));
    assert_eq!(ledger.records(), Err(DurableLedgerError::Poisoned));
    assert_eq!(ledger.active_records(), Err(DurableLedgerError::Poisoned));
    drop(ledger);
    assert!(must(must(fixture.recover(LedgerRecovery::Unacknowledged)).records()).is_empty());
}

#[test]
fn full_unacknowledged_frame_is_synced_and_deduplicated_on_recover() {
    let fixture = Fixture::new();
    drop(fixture.create());
    let mut core = LearningLedger::new();
    must(core.append(decision()));
    let frame = must(encode_frame(&core.records()[0]));
    let mut file = fixture.file();
    must(file.seek(SeekFrom::End(0)));
    must(file.write_all(&frame));
    drop(file);
    let mut recovered = must(fixture.recover(LedgerRecovery::Unacknowledged));
    let before = locked_bytes(&recovered);
    assert_eq!(
        must(recovered.append(Digest32::ZERO, decision())).disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(must(recovered.snapshot()), core.snapshot());
    assert_eq!(locked_bytes(&recovered), before);
}

#[test]
fn codec_rejects_every_truncation_unknown_variant_and_trailing_bytes() {
    for event in [decision(), outcome(), credit(), revocation()] {
        let bytes = crate::ledger::encode_event(&event);
        assert_eq!(decode_event(&bytes), Ok(event));
        for cut in 0..bytes.len() {
            assert_eq!(
                decode_event(&bytes[..cut]),
                Err(DurableLedgerError::Corrupt)
            );
        }
        let mut invalid = bytes.clone();
        invalid.push(0);
        assert_eq!(decode_event(&invalid), Err(DurableLedgerError::Corrupt));
        let mut invalid = bytes;
        invalid[b"hepta.learning-ledger.event.v1".len()] = 255;
        assert_eq!(decode_event(&invalid), Err(DurableLedgerError::Corrupt));
    }
}

#[test]
fn canonical_event_and_file_match_independent_integer_byte_oracle() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision()]);
    assert_eq!(
        snapshot.records()[0].event_digest.to_string(),
        "1d7e56032e2d34ebecb61d432f084c461d2e995e27ef23062b9d521c0f342346"
    );
    assert_eq!(
        snapshot.head_digest.to_string(),
        "5c418c837b6e23e963547be00fd03fe8cd58d2783eb0e8b82b4f4d815fe6de94"
    );
    let bytes = must(fs::read(fixture.path()));
    assert_eq!(bytes.len(), 362);
    assert_eq!(
        Digest32::of_bytes(&bytes).to_string(),
        "eba8162e7d3f4e8eb26babe2552731774ee9c6cd04facf81a3bb2a004eefbfcf"
    );
}

#[cfg(target_os = "linux")]
#[test]
fn owner_drop_releases_lock_with_a_transient_duplicate_alive() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    must(ledger.append(Digest32::ZERO, decision()));
    let snapshot = must(ledger.snapshot());
    // Model the open-description lifetime during fork, without a child writer.
    let transient = must(ledger.file.try_clone());
    assert_eq!(
        fixture.recover(anchored(&snapshot)).err(),
        Some(DurableLedgerError::Busy)
    );
    drop(ledger);
    let reopened = must(fixture.recover(anchored(&snapshot)));
    assert_eq!(must(reopened.snapshot()), snapshot);
    drop(transient);
    assert_eq!(
        fixture.recover(anchored(&snapshot)).err(),
        Some(DurableLedgerError::Busy)
    );
}

#[cfg(target_os = "linux")]
#[test]
fn failed_constructor_releases_acquired_lock_with_transient_duplicate() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision()]);
    let file = fixture.file();
    let transient = must(file.try_clone());
    assert_eq!(
        DurableLedger::create(file, binding(), /*max_records*/ 16).err(),
        Some(DurableLedgerError::AlreadyInitialized)
    );
    let recovered = must(fixture.recover(anchored(&snapshot)));
    assert_eq!(must(recovered.snapshot()), snapshot);
    drop(transient);
    assert_eq!(
        fixture.recover(anchored(&snapshot)).err(),
        Some(DurableLedgerError::Busy)
    );
}

#[cfg(target_os = "linux")]
#[test]
fn failed_recovery_releases_acquired_lock_before_store_exists() {
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![decision()]);
    let original = must(fs::read(fixture.path()));
    for bytes in [Vec::new(), b"broken".to_vec(), {
        let mut bad = original;
        bad[HEADER] ^= 1;
        bad
    }] {
        must(fs::write(fixture.path(), &bytes));
        let file = fixture.file();
        let transient = must(file.try_clone());
        let first = DurableLedger::recover(
            file,
            binding(),
            /*max_records*/ 16,
            anchored(&snapshot),
        )
        .err();
        assert!(matches!(
            first,
            Some(DurableLedgerError::MissingHeader | DurableLedgerError::Corrupt)
        ));
        assert_eq!(fixture.recover(anchored(&snapshot)).err(), first);
        drop(transient);
        assert_eq!(must(fs::read(fixture.path())), bytes);
    }
}
