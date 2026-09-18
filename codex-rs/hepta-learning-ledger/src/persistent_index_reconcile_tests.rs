use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::PersistentIndexedLearningLedgerV1;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn root() -> PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-index-reconcile-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed),
    ))
}

fn decision() -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision-record"),
        episode_id: id("episode"),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"decision-support"),
    })
}

fn outcome() -> LedgerEvent {
    LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: Digest32::of_bytes(b"outcome-support"),
    })
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 0x0f)]));
    }
    output
}

fn write_only_record_index(root: &PathBuf, record: &crate::LedgerRecord) {
    // Reproduce only the first immutable row written by persist_event_indexes:
    // record identity metadata. The episode/decision row is deliberately absent.
    let logical_key = record.event.record_id().as_str().as_bytes();
    let mut key_domain = b"record".to_vec();
    key_domain.push(0);
    key_domain.extend_from_slice(logical_key);
    let path = root
        .join("record")
        .join(hex(Digest32::of_bytes(&key_domain).as_array()));

    let mut value = Vec::with_capacity(105);
    value.extend_from_slice(&record.sequence.get().to_be_bytes());
    value.extend_from_slice(record.predecessor_chain_digest.as_array());
    value.extend_from_slice(record.event_digest.as_array());
    value.extend_from_slice(record.chain_digest.as_array());
    value.push(0); // decision event kind

    let mut envelope = Vec::new();
    envelope.push(1); // persistent-index envelope version
    envelope.extend_from_slice(&(logical_key.len() as u32).to_be_bytes());
    envelope.extend_from_slice(logical_key);
    envelope.extend_from_slice(&(value.len() as u32).to_be_bytes());
    envelope.extend_from_slice(&value);

    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .expect("create partial record index");
    file.write_all(&envelope).expect("write partial record index");
    file.sync_all().expect("sync partial record index");
}

#[test]
fn durable_record_reconciliation_fills_missing_event_specific_index_rows() {
    let root = root();
    let empty = LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    };

    // Create namespace layout without publishing semantic history.
    drop(
        PersistentIndexedLearningLedgerV1::open(&root, 4, empty)
            .expect("initialize persistent index root"),
    );

    let mut canonical = LearningLedger::new();
    let decision_receipt = canonical.append(decision()).expect("canonical decision");
    let record = canonical.records()[0].clone();
    write_only_record_index(&root, &record);

    let mut recovering =
        PersistentIndexedLearningLedgerV1::open(&root, 4, empty).expect("reopen partial sidecar");
    let receipt = recovering
        .reconcile_durable_record(&record)
        .expect("reconcile durable record");
    assert_eq!(receipt.disposition, AppendDisposition::Appended);
    assert_eq!(receipt.sequence, decision_receipt.sequence);
    assert_eq!(receipt.chain_digest, decision_receipt.chain_digest);
    drop(recovering);

    // Open at the reconciled durable frontier. A dependent outcome can now load
    // the missing decision index directly from disk; no historical payload scan
    // is required.
    let anchor = LedgerAnchor {
        sequence: receipt.sequence.get(),
        chain_digest: receipt.chain_digest,
    };
    let mut continued =
        PersistentIndexedLearningLedgerV1::open(&root, 2, anchor).expect("open at repaired head");
    let outcome_receipt = continued.append(outcome()).expect("dependent outcome");
    assert_eq!(outcome_receipt.sequence.get(), 2);
    assert!(continued.historical_cache_len() <= 2);

    fs::remove_dir_all(root).expect("cleanup");
}
