use std::fmt::Debug;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::Revocation;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn must<T, E: Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn decision(index: usize) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("record-{index}")),
        episode_id: id(&format!("episode-{index}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choose"), id("abstain")],
        selected_candidate_id: id("choose"),
        selected_propensity: must(ProbabilityQ32::from_raw(1_u64 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"support"),
    })
}

fn populated(count: usize) -> LearningLedger {
    let mut ledger = LearningLedger::new();
    for index in 0..count {
        must(ledger.append(decision(index)));
    }
    ledger
}

#[test]
fn first_middle_and_last_identity_use_the_correct_immutable_record() {
    let ledger = populated(257);
    for index in [0, 128, 256] {
        let record = ledger.record_by_id(&id(&format!("record-{index}")));
        assert_eq!(record, ledger.records().get(index));
    }
    assert!(ledger.record_by_id(&id("missing")).is_none());
}

#[test]
fn old_identity_retries_keep_the_original_receipt_after_growth() {
    let mut ledger = populated(257);
    let expected = ledger.records()[0].clone();
    let receipt = must(ledger.append(decision(0)));
    assert_eq!(receipt.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(receipt.sequence, expected.sequence);
    assert_eq!(receipt.event_digest, expected.event_digest);
    assert_eq!(receipt.chain_digest, expected.chain_digest);
    assert_eq!(ledger.records().len(), 257);
}

#[test]
fn conflicting_identity_does_not_overwrite_the_position() {
    let mut ledger = populated(8);
    let mut event = decision(0);
    let LedgerEvent::Decision(value) = &mut event else {
        panic!("decision fixture");
    };
    value.support_digest = Digest32::of_bytes(b"different");
    assert!(matches!(ledger.append(event), Err(LedgerError::IdentityConflict(_))));
    assert_eq!(ledger.record_by_id(&id("record-0")), ledger.records().first());
    assert_eq!(ledger.records().len(), 8);
}

#[test]
fn replay_rebuilds_positions_and_preserves_revoked_history() {
    let mut ledger = populated(32);
    must(ledger.append(LedgerEvent::Revocation(Revocation {
        record_id: id("revoke-0"),
        target_record_id: id("record-0"),
        authority_id: id("revocation-owner"),
        reason_digest: Digest32::of_bytes(b"withdraw"),
    })));
    let mut restored = must(LearningLedger::from_snapshot(ledger.snapshot()));
    assert_eq!(restored.snapshot(), ledger.snapshot());
    assert_eq!(restored.active_records().len(), 32);
    assert!(restored.record_by_id(&id("record-0")).is_some());
    let retry = must(restored.append(decision(0)));
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(restored.active_records().len(), 32);
}

#[test]
fn bounded_pages_are_borrowed_and_cover_history_once() {
    let ledger = populated(23);
    let first = ledger.records_after(0, 7);
    assert!(std::ptr::eq(first.as_ptr(), ledger.records().as_ptr()));
    let mut cursor = 0;
    let mut sequences = Vec::new();
    loop {
        let page = ledger.records_after(cursor, 7);
        if page.is_empty() {
            break;
        }
        for record in page {
            sequences.push(record.sequence.get());
            cursor = record.sequence.get();
        }
    }
    assert_eq!(sequences, (1..=23).collect::<Vec<u64>>());
}

#[test]
fn zero_and_extreme_cursors_do_not_panic_or_allocate_history() {
    let ledger = populated(3);
    assert!(ledger.records_after(0, 0).is_empty());
    assert!(ledger.records_after(3, 100).is_empty());
    assert!(ledger.records_after(u64::MAX, usize::MAX).is_empty());
    assert_eq!(ledger.records_after(1, usize::MAX).len(), 2);
    assert!(LearningLedger::new().records_after(0, usize::MAX).is_empty());
}

#[test]
fn caller_limit_cannot_defeat_the_page_bound() {
    let ledger = populated(LearningLedger::MAX_PAGE_RECORDS + 1);
    assert_eq!(ledger.records_after(0, usize::MAX).len(), LearningLedger::MAX_PAGE_RECORDS);
    assert_eq!(ledger.records_after(LearningLedger::MAX_PAGE_RECORDS as u64, usize::MAX).len(), 1);
}
