use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::ProbabilityQ32;

use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"long-horizon-bounded-hot-test-binding")
}

fn limits() -> LedgerSegmentLimits {
    LedgerSegmentLimits {
        records: 8,
        bytes: 64 * 1024,
    }
}

fn decision(number: u64) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("record-{number}")),
        episode_id: id(&format!("episode-{number}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("abstain"), id("choice")],
        selected_candidate_id: id("choice"),
        selected_propensity: must(ProbabilityQ32::from_raw(1_u64 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(format!("support-{number}").as_bytes()),
    })
}

struct Fixture {
    root: PathBuf,
    index_root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-long-horizon-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        must(fs::create_dir(&root));
        let index_root = root.join("index");
        let value = Self { root, index_root };
        drop(value.new_file("owner"));
        drop(value.new_file("segment-0"));
        value
    }

    fn new_file(&self, name: &str) -> File {
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(self.root.join(name)),
        )
    }

    fn file(&self, name: &str) -> File {
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.root.join(name)),
        )
    }

    fn segment_name(index: usize) -> String {
        format!("segment-{index}")
    }

    fn new_segment(&self, index: usize) -> File {
        self.new_file(&Self::segment_name(index))
    }

    fn segment(&self, index: usize) -> File {
        self.file(&Self::segment_name(index))
    }

    fn create(&self, cache_limit: usize) -> LongHorizonSegmentedLedgerV1 {
        must(LongHorizonSegmentedLedgerV1::create(
            self.file("owner"),
            self.segment(0),
            &self.index_root,
            binding(),
            limits(),
            cache_limit,
        ))
    }

    fn recover(
        &self,
        cache_limit: usize,
        minimum: LongHorizonLedgerCheckpointV1,
    ) -> Result<LongHorizonSegmentedLedgerV1, LongHorizonLedgerErrorV1> {
        LongHorizonSegmentedLedgerV1::recover(
            self.file("owner"),
            self.segment(minimum.active_segment),
            &self.index_root,
            binding(),
            limits(),
            cache_limit,
            minimum,
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn append(
    ledger: &mut LongHorizonSegmentedLedgerV1,
    event: LedgerEvent,
) -> AppendReceipt {
    let predecessor = ledger.head_anchor().chain_digest;
    must(ledger.append(predecessor, event))
}

#[test]
fn total_history_growth_does_not_expand_hot_writer_or_restart_replay() {
    let f = Fixture::new();
    let mut ledger = f.create(4);
    let mut first_receipt = None;

    for number in 0..64_u64 {
        let receipt = append(&mut ledger, decision(number));
        if number == 0 {
            first_receipt = Some(receipt.clone());
        }
        let metrics = must(ledger.metrics());
        assert!(metrics.retained_payload_records <= limits().records);
        assert!(metrics.historical_cache_entries <= 4);
        if (number + 1) % limits().records as u64 == 0 {
            let head = ledger.head_anchor();
            let next = ledger
                .checkpoint()
                .expect("checkpoint")
                .active_segment
                + 1;
            let checkpoint = must(ledger.rotate(f.new_segment(next), head));
            assert_eq!(checkpoint.active_segment, next);
            let metrics = must(ledger.metrics());
            assert_eq!(metrics.retained_payload_records, 0);
            assert!(metrics.historical_cache_entries <= 4);
        }
    }

    for number in 64..67_u64 {
        append(&mut ledger, decision(number));
    }
    let minimum = must(ledger.checkpoint());
    let before = must(ledger.metrics());
    assert_eq!(before.active_segment, 8);
    assert_eq!(before.retained_payload_records, 3);
    assert!(before.historical_cache_entries <= 4);
    assert!(before.active_segment_bytes <= limits().bytes);

    assert_eq!(
        must(ledger.archive_segment_for_record(&id("record-0"))),
        Some(0)
    );
    let archived = must(ledger.archived_record(f.segment(0), &id("record-0")))
        .expect("first record is archived");
    assert_eq!(archived.event, decision(0));
    drop(ledger);

    let mut reopened = must(f.recover(4, minimum));
    let after = must(reopened.metrics());
    assert_eq!(after.active_segment, 8);
    assert_eq!(after.retained_payload_records, 3);
    assert!(after.historical_cache_entries <= 4);
    assert!(after.active_segment_bytes <= limits().bytes);

    let replay = must(reopened.append(Digest32::ZERO, decision(0)));
    let first_receipt = first_receipt.expect("first receipt");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.sequence, first_receipt.sequence);
    assert_eq!(replay.chain_digest, first_receipt.chain_digest);
    assert_eq!(must(reopened.metrics()).retained_payload_records, 3);

    let next = append(&mut reopened, decision(67));
    assert_eq!(next.sequence.get(), 68);
    assert_eq!(must(reopened.metrics()).retained_payload_records, 4);
    assert!(must(reopened.metrics()).historical_cache_entries <= 4);
}

#[test]
fn durable_frame_without_sidecar_commit_is_reconciled_from_bounded_tail() {
    let f = Fixture::new();
    let mut ledger = f.create(3);
    let minimum = must(ledger.checkpoint());

    // Simulate process death in the only crash window: semantic validation has
    // succeeded and the exact payload frame is durable, but sidecar publication
    // has not begun. No private index row is written here.
    let prepared = must(ledger.semantic.prepare_event(decision(0)));
    let record = prepared.record().clone();
    let frame = must(encode_frame(&record));
    must(ledger.active.seek(SeekFrom::End(0)));
    must(ledger.active.write_all(&frame));
    must(ledger.active.sync_all());
    drop(prepared);
    drop(ledger);

    let mut recovered = must(f.recover(3, minimum));
    assert_eq!(recovered.head_anchor().sequence, 1);
    assert_eq!(must(recovered.metrics()).retained_payload_records, 1);
    assert!(must(recovered.metrics()).historical_cache_entries <= 3);

    // A second reopen starts from an independently retained current-head
    // checkpoint and verifies that the repaired semantic rows are reusable.
    let repaired_minimum = must(recovered.checkpoint());
    drop(recovered);
    let mut reopened = must(f.recover(3, repaired_minimum));
    let replay = must(reopened.append(Digest32::ZERO, decision(0)));
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.sequence.get(), 1);
}

#[test]
fn acknowledged_tail_rollback_is_not_healed_from_sidecar() {
    let f = Fixture::new();
    let mut ledger = f.create(2);
    append(&mut ledger, decision(0));
    let minimum = must(ledger.checkpoint());
    assert_eq!(minimum.head_anchor.sequence, 1);
    drop(ledger);

    let file = f.segment(0);
    must(file.set_len(segment_codec::HEADER as u64));
    must(file.sync_all());
    drop(file);

    assert!(matches!(
        f.recover(2, minimum),
        Err(LongHorizonLedgerErrorV1::Durable(
            DurableLedgerError::AcknowledgedHistoryMissing
        ))
    ));
}
