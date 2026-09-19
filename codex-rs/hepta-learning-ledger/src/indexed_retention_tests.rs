//! Pure-core retention regressions. Disk crash/recovery is tested by the
//! long-horizon and persistent-index owners, not simulated by clearing a Vec.

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LearningLedger;
use crate::LedgerEvent;
use crate::Revocation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn decision(index: usize) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("record-{index}")),
        episode_id: id(&format!("episode-{index}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choose"), id("abstain")],
        selected_candidate_id: id("choose"),
        selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).expect("propensity"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"support"),
    })
}

fn sequence(value: u64) -> Option<LogicalSequence> {
    Some(LogicalSequence::new(value).expect("sequence"))
}

#[test]
fn pages_after_compaction_use_global_sequences_not_hot_vector_offsets() {
    let mut ledger = LearningLedger::new();
    for index in 0..32 {
        ledger.append(decision(index)).expect("append prefix");
    }
    let archived_head = ledger.head_digest();
    ledger.compact_retained_payloads();
    assert!(ledger.records().is_empty());
    assert_eq!(ledger.head_sequence(), sequence(32));
    assert_eq!(ledger.head_digest(), archived_head);
    for index in 32..36 {
        ledger.append(decision(index)).expect("append retained tail");
    }
    for cursor in [None, sequence(1), sequence(31), sequence(32)] {
        let page = ledger.records_after(cursor, 2);
        assert_eq!(page.len(), 2);
        assert_eq!(page[0].sequence.get(), 33);
        assert_eq!(page[1].sequence.get(), 34);
        assert!(std::ptr::eq(page.as_ptr(), ledger.records().as_ptr()));
    }
    let page = ledger.records_after(sequence(34), usize::MAX);
    assert_eq!(page.len(), 2);
    assert_eq!(page[0].sequence.get(), 35);
    assert!(ledger.records_after(sequence(36), 2).is_empty());
    assert!(ledger.records_after(sequence(u64::MAX), usize::MAX).is_empty());
    assert!(ledger.record(&id("record-0")).is_none());
    assert_eq!(ledger.record(&id("record-32")), ledger.records().first());
}

#[test]
fn archived_identity_retry_never_repopulates_or_reindexes_the_retained_tail() {
    let mut ledger = LearningLedger::new();
    let original = ledger.append(decision(0)).expect("first record");
    for index in 1..64 {
        ledger.append(decision(index)).expect("append prefix");
    }
    ledger.compact_retained_payloads();
    ledger.append(decision(64)).expect("hot record");
    let before = ledger.records().to_vec();
    let indexed = ledger.record_index.len();
    let head = ledger.head_digest();
    let retry = ledger.append(decision(0)).expect("archived identity replay");
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.sequence, original.sequence);
    assert_eq!(retry.chain_digest, original.chain_digest);
    assert_eq!(retry.event_digest, original.event_digest);
    assert_eq!(ledger.records(), before.as_slice());
    assert_eq!(ledger.record_index.len(), indexed);
    assert_eq!(ledger.head_digest(), head);
    assert!(ledger.record(&id("record-0")).is_none());
}

#[test]
fn compaction_and_old_retries_do_not_remove_revocation_state() {
    let mut ledger = LearningLedger::new();
    ledger.append(decision(0)).expect("decision");
    ledger.compact_retained_payloads();
    ledger
        .append(LedgerEvent::Revocation(Revocation {
            record_id: id("revoke-0"),
            target_record_id: id("record-0"),
            authority_id: id("revocation-owner"),
            reason_digest: Digest32::of_bytes(b"withdraw"),
        }))
        .expect("revoke archived decision");
    ledger.compact_retained_payloads();
    assert!(ledger.revoked.contains(&id("record-0")));
    let head = ledger.head_digest();
    let retry = ledger.append(decision(0)).expect("replay is not resurrection");
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert!(ledger.revoked.contains(&id("record-0")));
    assert!(ledger.records().is_empty());
    assert_eq!(ledger.head_digest(), head);
}
