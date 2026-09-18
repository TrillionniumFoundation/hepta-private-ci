use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::PersistentIndexedLearningLedgerV1;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);
const CACHE_LIMIT: usize = 8;
const ARCHIVE_INTERVAL: u64 = 32;
const HISTORY_RECORDS: u64 = 512;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identity")
}

fn temp_root() -> PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-persistent-ledger-integration-{}-{}",
        std::process::id(),
        NEXT_ROOT.fetch_add(1, Ordering::Relaxed),
    ))
}

fn decision(number: u64) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("record-{number}")),
        episode_id: id(&format!("episode-{number}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("candidate"), id("abstain")],
        selected_candidate_id: id("candidate"),
        selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(format!("support-{number}").as_bytes()),
    })
}

#[test]
fn large_history_keeps_hot_state_bounded_across_archive_restart_and_replay() {
    let root = temp_root();
    let empty = LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    };
    let first_event = decision(1);
    let first_receipt;
    let final_anchor;

    {
        let mut ledger = PersistentIndexedLearningLedgerV1::open(&root, CACHE_LIMIT, empty)
            .expect("open persistent ledger");
        let mut first = None;
        for sequence in 1..=HISTORY_RECORDS {
            let receipt = ledger.append(decision(sequence)).expect("append decision");
            if sequence == 1 {
                first = Some(receipt.clone());
            }
            assert_eq!(receipt.sequence.get(), sequence);
            assert!(ledger.historical_cache_len() <= CACHE_LIMIT);
            assert!(ledger.retained_record_count() <= ARCHIVE_INTERVAL as usize);

            if sequence % ARCHIVE_INTERVAL == 0 {
                let anchor = ledger.head_anchor();
                ledger
                    .confirm_payload_archive_and_compact(anchor)
                    .expect("confirm archive frontier");
                assert_eq!(ledger.retained_record_count(), 0);
                assert!(ledger.historical_cache_len() <= CACHE_LIMIT);
            }
        }
        first_receipt = first.expect("first receipt");
        final_anchor = ledger.head_anchor();
        assert_eq!(final_anchor.sequence, HISTORY_RECORDS);
        assert_eq!(ledger.retained_record_count(), 0);
    }

    let mut reopened = PersistentIndexedLearningLedgerV1::open(&root, CACHE_LIMIT, final_anchor)
        .expect("reopen from authenticated archive frontier");
    assert_eq!(
        reopened.historical_cache_len(),
        0,
        "restart must not hydrate total historical index state"
    );
    assert_eq!(reopened.retained_record_count(), 0);

    let replay = reopened
        .append(first_event)
        .expect("historical idempotent replay");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.sequence, first_receipt.sequence);
    assert_eq!(replay.chain_digest, first_receipt.chain_digest);
    assert!(reopened.historical_cache_len() <= CACHE_LIMIT);
    assert_eq!(reopened.retained_record_count(), 0);

    let next = reopened
        .append(decision(HISTORY_RECORDS + 1))
        .expect("continue after restart");
    assert_eq!(next.sequence.get(), HISTORY_RECORDS + 1);
    assert_eq!(reopened.retained_record_count(), 1);
    assert!(reopened.historical_cache_len() <= CACHE_LIMIT);

    fs::remove_dir_all(root).expect("cleanup persistent ledger fixture");
}
