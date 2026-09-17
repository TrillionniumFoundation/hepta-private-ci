use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::DurableLearningJournal;
use crate::DurableLedger;
use crate::EpisodeDecision;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;

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
    Digest32::of_bytes(b"independently-bound-segmented-test-owner")
}

fn limits() -> LedgerSegmentLimits {
    LedgerSegmentLimits {
        records: 2,
        bytes: 4096,
    }
}

fn decision(number: usize) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("decision-{number}")),
        episode_id: id(&format!("episode-{number}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: must(ProbabilityQ32::from_raw(/*raw*/ 1 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"complete-support"),
    })
}

fn outcome() -> LedgerEvent {
    LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode-0"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: Digest32::of_bytes(b"outcome-support"),
    })
}

fn revoke() -> LedgerEvent {
    LedgerEvent::Revocation(Revocation {
        record_id: id("revocation"),
        target_record_id: id("decision-0"),
        authority_id: id("privacy-owner"),
        reason_digest: Digest32::of_bytes(b"authorized-delete"),
    })
}

struct Fixture {
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-segments-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        must(fs::create_dir(&root));
        let value = Self { root };
        drop(value.new_file("owner"));
        drop(value.new_file("0"));
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
    fn files(&self, count: usize) -> Vec<File> {
        (0..count).map(|i| self.file(&i.to_string())).collect()
    }
    fn create(&self) -> SegmentedLedger {
        must(SegmentedLedger::create(
            self.file("owner"),
            self.file("0"),
            binding(),
            limits(),
        ))
    }
    fn recover(
        &self,
        count: usize,
        minimum: LedgerSegmentCheckpoint,
    ) -> Result<SegmentedLedger, DurableLedgerError> {
        SegmentedLedger::recover(
            self.file("owner"),
            self.files(count),
            binding(),
            limits(),
            minimum,
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn append(ledger: &mut SegmentedLedger, event: LedgerEvent) -> AppendReceipt {
    let head = must(ledger.anchor()).chain_digest;
    must(ledger.append(head, event))
}

#[test]
fn cross_segment_causality_revocation_and_historical_retry_keep_one_identity() {
    let f = Fixture::new();
    let mut ledger = f.create();
    let original = append(&mut ledger, decision(0));
    let anchor = must(ledger.anchor());
    must(ledger.rotate(f.new_file("1"), anchor));
    assert_eq!(must(ledger.retained_record_count()), 0);
    append(&mut ledger, outcome());
    append(&mut ledger, revoke());
    let checkpoint = must(ledger.checkpoint());
    assert!(matches!(
        ledger.snapshot(),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    ));
    let snapshot = must(ledger.snapshot_with_archives(f.files(1)));
    let mut expected = LearningLedger::new();
    for event in [decision(0), outcome(), revoke()] {
        must(expected.append(event));
    }
    assert_eq!(snapshot, expected.snapshot());
    let expected_active: Vec<LedgerRecord> =
        expected.active_records().into_iter().cloned().collect();
    assert_eq!(
        must(ledger.active_records_with_archives(f.files(1))),
        expected_active
    );
    let range = must(ledger.archive_range(&id("decision-0"))).expect("archived decision range");
    assert_eq!(range.segment, 0);
    let archived = must(ledger.archived_record(f.file("0"), &id("decision-0")))
        .expect("archived decision payload");
    assert_eq!(archived.event, decision(0));
    drop(ledger);

    let mut reopened = must(f.recover(2, checkpoint));
    assert_eq!(must(reopened.retained_record_count()), 2);
    let retry = must(reopened.append(Digest32::ZERO, decision(0)));
    assert_eq!(retry.chain_digest, original.chain_digest);
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(must(reopened.snapshot_with_archives(f.files(1))), snapshot);
    assert_eq!(
        must(reopened.active_records_with_archives(f.files(1))),
        expected_active
    );
    let mut changed = decision(0);
    if let LedgerEvent::Decision(ref mut row) = changed {
        row.support_digest = Digest32::of_bytes(b"substituted");
    }
    assert!(reopened.append(Digest32::ZERO, changed).is_err());
}

#[test]
fn state_checkpoint_recovery_replays_only_the_tail_and_pages_archive_on_demand() {
    let f = Fixture::new();
    let mut ledger = f.create();
    let original = append(&mut ledger, decision(0));
    let archived_anchor = must(ledger.anchor());
    let witness = must(ledger.rotate_with_state_checkpoint(
        f.new_file("state-checkpoint"),
        f.new_file("1"),
        archived_anchor,
    ));
    assert_eq!(witness.segment, 0);
    assert_eq!(witness.anchor, archived_anchor);
    assert_eq!(must(ledger.retained_record_count()), 0);
    append(&mut ledger, outcome());
    let final_anchor = must(ledger.anchor());
    let minimum = LedgerSegmentCheckpoint {
        segment: witness.segment,
        anchor: witness.anchor,
        sealed: true,
    };
    drop(ledger);

    let mut reopened = must(SegmentedLedger::recover_from_state_checkpoint(
        f.file("owner"),
        f.file("state-checkpoint"),
        vec![f.file("1")],
        binding(),
        limits(),
        witness,
        minimum,
    ));
    assert_eq!(must(reopened.anchor()), final_anchor);
    assert_eq!(must(reopened.retained_record_count()), 1);
    assert_eq!(reopened.archive_ranges().len(), 1);
    let retry = must(reopened.append(Digest32::ZERO, decision(0)));
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.chain_digest, original.chain_digest);
    let range = must(reopened.archive_range(&id("decision-0"))).expect("archive range");
    assert_eq!(range.segment, 0);
    let archived =
        must(reopened.archived_record(f.file("0"), &id("decision-0"))).expect("archived decision");
    assert_eq!(archived.sequence.get(), 1);
    assert_eq!(archived.chain_digest, original.chain_digest);
    assert_eq!(archived.event, decision(0));
}

#[test]
fn checkpoint_digest_is_independently_witnessed() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    let archived_anchor = must(ledger.anchor());
    let witness = must(ledger.rotate_with_state_checkpoint(
        f.new_file("state-checkpoint"),
        f.new_file("1"),
        archived_anchor,
    ));
    drop(ledger);
    let mut wrong = witness;
    wrong.state_digest = Digest32::of_bytes(b"wrong-checkpoint-witness");
    assert!(matches!(
        SegmentedLedger::recover_from_state_checkpoint(
            f.file("owner"),
            f.file("state-checkpoint"),
            vec![f.file("1")],
            binding(),
            limits(),
            wrong,
            LedgerSegmentCheckpoint {
                segment: witness.segment,
                anchor: witness.anchor,
                sealed: true,
            },
        ),
        Err(DurableLedgerError::Corrupt)
    ));
}

#[test]
fn sealed_prefix_is_readable_while_the_new_segment_writer_remains_active() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    let prefix_anchor = must(ledger.anchor());
    let prefix = must(ledger.snapshot());
    must(ledger.rotate(f.new_file("1"), prefix_anchor));
    append(&mut ledger, outcome());
    assert_eq!(
        must(inspect_ledger_segments(
            f.files(1),
            binding(),
            limits(),
            prefix_anchor
        )),
        prefix
    );
    assert!(matches!(
        inspect_ledger_segments(f.files(2), binding(), limits(), must(ledger.anchor())),
        Err(DurableLedgerError::Busy)
    ));
    assert!(matches!(
        inspect_ledger_segments(f.files(1), binding(), limits(), must(ledger.anchor())),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    ));
    assert!(matches!(
        f.recover(1, must(ledger.checkpoint())),
        Err(DurableLedgerError::Busy)
    ));
}

#[test]
fn checkpoint_prevents_missing_empty_successor_and_seal_resurrection() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    let anchor = must(ledger.anchor());
    must(ledger.seal(anchor));
    let sealed = must(ledger.checkpoint());
    must(ledger.rotate(f.new_file("1"), anchor));
    let successor = must(ledger.checkpoint());
    drop(ledger);
    assert!(matches!(
        f.recover(1, successor),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    ));
    let file = f.file("0");
    let length = must(file.metadata()).len();
    must(file.set_len(length - segment_codec::FOOTER as u64));
    drop(file);
    assert!(matches!(
        f.recover(1, sealed),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    ));
    assert!(matches!(
        f.recover(2, successor),
        Err(DurableLedgerError::IncompleteTail)
    ));
}

#[test]
fn capacity_rejection_and_wrong_successor_never_mutate_the_owner() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    append(&mut ledger, outcome());
    let checkpoint = must(ledger.checkpoint());
    let before = must(ledger.snapshot());
    assert_eq!(
        ledger.append(checkpoint.anchor.chain_digest, decision(1)),
        Err(DurableLedgerError::Capacity)
    );
    let mut nonempty = f.new_file("bad");
    must(nonempty.write_all(b"not-empty"));
    assert_eq!(
        ledger.rotate(nonempty, checkpoint.anchor),
        Err(DurableLedgerError::AlreadyInitialized)
    );
    assert!(!must(ledger.is_sealed()));
    assert_eq!(must(ledger.snapshot()), before);
    let wrong = LedgerAnchor {
        sequence: checkpoint.anchor.sequence,
        chain_digest: Digest32::ZERO,
    };
    assert_eq!(
        ledger.rotate(f.new_file("1"), wrong),
        Err(DurableLedgerError::AnchorMismatch)
    );
    assert!(!must(ledger.is_sealed()));
}

#[test]
fn reordered_history_wrong_limits_and_corruption_fail_without_repair() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    let anchor = must(ledger.anchor());
    must(ledger.rotate(f.new_file("1"), anchor));
    append(&mut ledger, outcome());
    let checkpoint = must(ledger.checkpoint());
    drop(ledger);
    assert!(
        SegmentedLedger::recover(
            f.file("owner"),
            vec![f.file("1"), f.file("0")],
            binding(),
            limits(),
            checkpoint
        )
        .is_err()
    );
    assert!(
        SegmentedLedger::recover(
            f.file("owner"),
            f.files(2),
            binding(),
            LedgerSegmentLimits {
                records: 3,
                bytes: 4096
            },
            checkpoint
        )
        .is_err()
    );
    let path = f.root.join("1");
    let mut bytes = must(fs::read(&path));
    bytes[segment_codec::HEADER + 50] ^= 1;
    must(fs::write(&path, &bytes));
    assert!(matches!(
        f.recover(2, checkpoint),
        Err(DurableLedgerError::Corrupt)
    ));
    assert_eq!(must(fs::read(path)), bytes);
}

#[test]
fn incomplete_final_frame_is_repaired_only_after_minimum_anchor_validation() {
    let mut core = LearningLedger::new();
    must(core.append(decision(0)));
    let prepared = must(core.prepare(outcome()));
    let frame = must(encode_frame(&prepared.record));
    for cut in [1, 7, 8, 48, frame.len() - 1, frame.len()] {
        let f = Fixture::new();
        let mut ledger = f.create();
        append(&mut ledger, decision(0));
        let checkpoint = must(ledger.checkpoint());
        let before = must(ledger.snapshot());
        drop(ledger);
        let mut file = f.file("0");
        must(file.seek(SeekFrom::End(0)));
        must(file.write_all(&frame[..cut]));
        drop(file);
        let path = f.root.join("0");
        let torn = must(fs::read(&path));
        let mut wrong = checkpoint;
        wrong.anchor.chain_digest = Digest32::of_bytes(b"wrong-independent-anchor");
        assert!(matches!(
            f.recover(1, wrong),
            Err(DurableLedgerError::AnchorMismatch)
        ));
        assert_eq!(must(fs::read(&path)), torn);
        let recovered = must(f.recover(1, checkpoint));
        let after = must(recovered.snapshot());
        if cut == frame.len() {
            assert_eq!(after.records().len(), 2);
        } else {
            assert_eq!(after, before);
        }
    }
}

#[test]
fn witnessed_sealed_last_segment_can_rotate_but_never_append_after_restart() {
    let f = Fixture::new();
    let mut ledger = f.create();
    append(&mut ledger, decision(0));
    let anchor = must(ledger.anchor());
    must(ledger.seal(anchor));
    let checkpoint = must(ledger.checkpoint());
    drop(ledger);
    let mut reopened = must(f.recover(1, checkpoint));
    assert!(must(reopened.is_sealed()));
    assert_eq!(
        reopened.append(anchor.chain_digest, outcome()),
        Err(DurableLedgerError::Capacity)
    );
    must(reopened.rotate(f.new_file("1"), anchor));
    append(&mut reopened, outcome());
    assert_eq!(must(reopened.anchor()).sequence, 2);
}

#[test]
fn original_v1_and_segmented_v2_share_the_real_durable_port_not_a_fixture() {
    let f = Fixture::new();
    let mut v1 = must(DurableLedger::create(f.new_file("legacy"), binding(), 2));
    let mut v2 = f.create();
    for journal in [&mut v1 as &mut dyn DurableLearningJournal, &mut v2] {
        must(journal.append(Digest32::ZERO, decision(0)));
    }
    assert_eq!(must(v1.snapshot()), must(v2.snapshot()));
    drop(v1);
    drop(v2);
    assert!(
        DurableLedger::recover(f.file("0"), binding(), 2, LedgerRecovery::Unacknowledged).is_err()
    );
}

#[test]
fn history_exceeds_v1_record_capacity_without_resetting_chain_or_limits() {
    let f = Fixture::new();
    let configured = LedgerSegmentLimits {
        records: 32,
        bytes: 64 * 1024,
    };
    let mut ledger = must(SegmentedLedger::create(
        f.file("owner"),
        f.file("0"),
        binding(),
        configured,
    ));
    let mut count = 1;
    for number in 0..8200 {
        if number != 0 && number % configured.records == 0 {
            let anchor = must(ledger.anchor());
            must(ledger.rotate(f.new_file(&count.to_string()), anchor));
            count += 1;
        }
        append(&mut ledger, decision(number));
        assert!(must(ledger.retained_record_count()) <= configured.records);
    }
    let checkpoint = must(ledger.checkpoint());
    let head = must(ledger.anchor());
    assert_eq!(checkpoint.anchor.sequence, 8200);
    assert_eq!(head, checkpoint.anchor);
    assert!(must(ledger.retained_record_count()) <= configured.records);
    let oldest_range = must(ledger.archive_range(&id("decision-0"))).expect("oldest archive range");
    assert_eq!(oldest_range.segment, 0);
    let oldest = must(ledger.archived_record(f.file("0"), &id("decision-0")))
        .expect("oldest archived record");
    assert_eq!(oldest.sequence.get(), 1);
    drop(ledger);

    let mut reopened = must(SegmentedLedger::recover(
        f.file("owner"),
        f.files(count),
        binding(),
        configured,
        checkpoint,
    ));
    assert_eq!(must(reopened.anchor()), head);
    assert!(must(reopened.retained_record_count()) <= configured.records);
    let replay = must(reopened.append(Digest32::ZERO, decision(0)));
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
}

#[test]
fn crash_child() {
    let Ok(root) = std::env::var("HEPTA_SEGMENT_CRASH_FIXTURE") else {
        return;
    };
    let f = Fixture {
        root: PathBuf::from(root),
    };
    let bytes: [u8; 32] = must(must(fs::read(f.root.join("retained-anchor"))).try_into());
    let minimum = LedgerSegmentCheckpoint {
        segment: 0,
        anchor: LedgerAnchor {
            sequence: 1,
            chain_digest: Digest32::from_array(bytes),
        },
        sealed: false,
    };
    let mut ledger = must(f.recover(1, minimum));
    append(&mut ledger, outcome());
    let anchor = must(ledger.anchor());
    must(ledger.seal(anchor));
    if std::env::var("HEPTA_SEGMENT_CRASH_PHASE").as_deref() == Ok("after-successor") {
        must(ledger.rotate(f.new_file("1"), anchor));
    }
    // Deliberately no destructors or acknowledgement: an actual process exits
    // after durable I/O at the two rotation boundaries.
    std::process::exit(19);
}

#[test]
fn process_exit_after_seal_or_successor_preserves_unknown_outcome_without_redispatch() {
    for phase in ["after-seal", "after-successor"] {
        let f = Fixture::new();
        let mut ledger = f.create();
        append(&mut ledger, decision(0));
        let minimum = must(ledger.checkpoint());
        must(fs::write(
            f.root.join("retained-anchor"),
            minimum.anchor.chain_digest.as_array(),
        ));
        drop(ledger);
        let output = must(
            Command::new(must(std::env::current_exe()))
                .args(["--exact", "segments::tests::crash_child", "--nocapture"])
                .env("HEPTA_SEGMENT_CRASH_FIXTURE", &f.root)
                .env("HEPTA_SEGMENT_CRASH_PHASE", phase)
                .output(),
        );
        assert_eq!(
            output.status.code(),
            Some(19),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let count = if phase == "after-seal" { 1 } else { 2 };
        let mut recovered = must(f.recover(count, minimum));
        assert_eq!(must(recovered.anchor()).sequence, 2);
        let retry = must(recovered.append(minimum.anchor.chain_digest, outcome()));
        assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(must(recovered.anchor()).sequence, 2);
    }
}
