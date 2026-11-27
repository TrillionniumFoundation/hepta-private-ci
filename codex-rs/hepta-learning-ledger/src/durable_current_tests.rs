use super::*;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-ledger-current-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn create(&self) -> DurableLedger {
        DurableLedger::create(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(self.0.join("ledger"))
                .unwrap(),
            Digest32::of_bytes(b"current-ledger-original-binding"),
            /*max_records*/ 16,
        )
        .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn decision(support: &[u8]) -> LedgerEvent {
    let id = |value: &str| StableId::new(value).unwrap();
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision"),
        episode_id: id("episode"),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(/*raw*/ 1 << 31).unwrap(),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(support),
    })
}

fn bytes(ledger: &mut DurableLedger) -> Vec<u8> {
    ledger.file.qualification_bytes(MAX_BYTES).unwrap()
}

#[test]
fn current_reads_complete_original_bytes_and_preserves_cursor() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    ledger
        .append(Digest32::ZERO, decision(b"original"))
        .unwrap();
    let expected = ledger.snapshot().unwrap();
    let original = bytes(&mut ledger);
    ledger.file.seek(SeekFrom::Start(11)).unwrap();
    assert_eq!(ledger.read_current_snapshot().unwrap(), expected);
    assert_eq!(ledger.file.stream_position().unwrap(), 11);
    assert_eq!(bytes(&mut ledger), original);
}

#[test]
fn current_rejects_a_different_valid_same_length_ledger() {
    let fixture = Fixture::new();
    let mut ledger = fixture.create();
    ledger
        .append(Digest32::ZERO, decision(b"original"))
        .unwrap();
    let retained = ledger.snapshot().unwrap();
    let original = bytes(&mut ledger);
    let mut replacement = LearningLedger::new();
    replacement.append(decision(b"substituted")).unwrap();
    let frame = encode_frame(&replacement.records()[0]).unwrap();
    assert_eq!(frame.len() + HEADER, original.len());
    ledger.file.seek(SeekFrom::Start(HEADER as u64)).unwrap();
    ledger.file.write_all(&frame).unwrap();
    let changed = bytes(&mut ledger);
    assert_eq!(ledger.snapshot().unwrap(), retained);
    assert_eq!(
        ledger.read_current_snapshot(),
        Err(DurableLedgerError::AnchorMismatch)
    );
    assert_eq!(bytes(&mut ledger), changed);
    ledger.file.seek(SeekFrom::Start(0)).unwrap();
    ledger.file.write_all(&original).unwrap();
    assert_eq!(
        ledger.read_current_snapshot(),
        Err(DurableLedgerError::Poisoned)
    );
}

#[test]
fn current_refuses_truncation_short_tail_extra_tail_and_header_corruption_without_repair() {
    for mutation in 0..4 {
        let fixture = Fixture::new();
        let mut ledger = fixture.create();
        ledger
            .append(Digest32::ZERO, decision(b"original"))
            .unwrap();
        let original = bytes(&mut ledger);
        match mutation {
            0 => ledger.file.set_len(HEADER as u64).unwrap(),
            1 => ledger.file.set_len((original.len() - 1) as u64).unwrap(),
            2 => {
                ledger.file.seek(SeekFrom::End(0)).unwrap();
                ledger.file.write_all(&[1]).unwrap();
            }
            3 => {
                ledger.file.seek(SeekFrom::Start(9)).unwrap();
                ledger.file.write_all(&[original[9] ^ 1]).unwrap();
            }
            _ => unreachable!(),
        }
        let changed = bytes(&mut ledger);
        assert_ne!(changed, original);
        ledger.file.seek(SeekFrom::Start(13)).unwrap();
        assert!(ledger.read_current_snapshot().is_err());
        assert_eq!(ledger.file.stream_position().unwrap(), 13);
        assert_eq!(bytes(&mut ledger), changed);
        assert_eq!(ledger.snapshot(), Err(DurableLedgerError::Poisoned));
    }
}
