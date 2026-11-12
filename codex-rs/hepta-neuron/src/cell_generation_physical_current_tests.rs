use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::support::*;
use super::*;
use crate::WitnessStoreError;

fn replace_original_bytes<W: AnchorWitnessStore>(
    owner: &mut CellGenerationJournalV2<W>,
    bytes: &[u8],
    position: u64,
) {
    checked(owner.file.seek(SeekFrom::Start(0)));
    checked(owner.file.set_len(bytes.len() as u64));
    checked(owner.file.write_all(bytes));
    checked(owner.file.seek(SeekFrom::Start(position)));
}

#[test]
fn physical_current_preserves_complete_bytes_cursor_state_and_append_owner() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    checked(owner.record_cost(charge("first", CellCostStageV2::Persistence)));
    checked(owner.drain());
    let bytes = owner.locked_bytes_for_test();
    let witness = checked(owner.witness.current());
    let observation = checked(owner.observe_generation());
    let checkpoint = checked(owner.continuity_checkpoint());
    checked(owner.file.seek(SeekFrom::Start(7)));
    assert_eq!(owner.read_current_checkpoint(), Ok(checkpoint));
    assert_eq!(checked(owner.file.stream_position()), 7);
    assert_eq!(owner.locked_bytes_for_test(), bytes);
    assert_eq!(checked(owner.observe_generation()), observation);
    assert_eq!(checked(owner.witness.current()), witness);
    assert!(crate::journal_lock::LockedFile::acquire(fixture.file("journal")).is_err());
    checked(owner.resume());
    assert_ne!(checked(owner.read_current_checkpoint()), checkpoint);
    assert_eq!(
        owner.read_current_checkpoint(),
        owner.continuity_checkpoint()
    );
}

#[test]
fn physical_current_rejects_short_tail_extra_tail_and_truncation_without_repair() {
    for change in ["truncated", "short_tail", "extra_frame"] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        checked(owner.drain());
        let original = owner.locked_bytes_for_test();
        let mut changed = original.clone();
        match change {
            "truncated" => {
                changed.pop();
            }
            "short_tail" => changed.extend_from_slice(&[0, 0, 1]),
            "extra_frame" => changed.extend_from_slice(&original[HEADER_BYTES..]),
            _ => unreachable!(),
        }
        replace_original_bytes(&mut owner, &changed, /*position*/ 9);
        assert_eq!(
            owner.read_current_checkpoint(),
            Err(CellGenerationErrorV2::Corrupt)
        );
        assert_eq!(checked(owner.file.stream_position()), 9);
        assert_eq!(owner.locked_bytes_for_test(), changed);
        replace_original_bytes(&mut owner, &original, /*position*/ 9);
        assert_eq!(owner.recover(), Err(CellGenerationErrorV2::CommitUncertain));
        assert_eq!(
            owner.read_current_checkpoint(),
            Err(CellGenerationErrorV2::CommitUncertain)
        );
        assert_eq!(owner.require_current(), Err(CellGenerationErrorV2::CommitUncertain));
        assert_eq!(owner.drain(), Err(CellGenerationErrorV2::CommitUncertain));
        assert_eq!(owner.locked_bytes_for_test(), original);
        assert_eq!(checked(owner.file.stream_position()), 9);
    }
}

#[test]
fn physical_current_rejects_valid_same_length_rehashed_history_and_cannot_rearm() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "original");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let original = owner.locked_bytes_for_test();
    let event = GenerationEvent::Admit {
        request: req,
        observed_at_micros: 12,
    };
    let payload = checked(serde_json::to_vec(&event));
    let next = checked(next_anchor(&owner.header, /*previous*/ None, &payload));
    let mut alternative = owner.header.clone();
    alternative.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    alternative.extend_from_slice(&payload);
    alternative.extend_from_slice(next.checkpoint_digest.as_array());
    let mut alternative_state = checked(GenerationState::new(&owner.config));
    checked(alternative_state.apply(&owner.config, &event));
    assert_eq!(alternative.len(), original.len());
    assert_ne!(alternative, original);
    let checkpoint = checked(owner.continuity_checkpoint());
    replace_original_bytes(&mut owner, &alternative, /*position*/ 5);
    assert_eq!(
        owner.read_current_checkpoint(),
        Err(CellGenerationErrorV2::Corrupt)
    );
    assert_eq!(owner.locked_bytes_for_test(), alternative);
    assert_eq!(checked(owner.file.stream_position()), 5);
    replace_original_bytes(&mut owner, &original, /*position*/ 5);
    assert_eq!(owner.recover(), Err(CellGenerationErrorV2::CommitUncertain));
    assert_eq!(owner.continuity_checkpoint(), Err(CellGenerationErrorV2::CommitUncertain));
    assert_ne!(checkpoint, Digest32::ZERO);
}

#[test]
fn physical_current_rejects_header_change_and_preserves_cursor_after_restore() {
    for index in [0, HEADER_BYTES - 1] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let original = owner.locked_bytes_for_test();
        let mut changed = original.clone();
        changed[index] ^= 1;
        replace_original_bytes(&mut owner, &changed, /*position*/ 3);
        assert_eq!(
            owner.read_current_checkpoint(),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
        assert_eq!(checked(owner.file.stream_position()), 3);
        assert_eq!(owner.locked_bytes_for_test(), changed);
        replace_original_bytes(&mut owner, &original, /*position*/ 3);
        assert_eq!(owner.recover(), Err(CellGenerationErrorV2::CommitUncertain));
        assert_eq!(
            owner.read_current_checkpoint(),
            Err(CellGenerationErrorV2::CommitUncertain)
        );
    }
}

struct MovingWitness {
    inner: FileAnchorWitnessStore,
    armed: Arc<AtomicBool>,
    reads: Arc<AtomicUsize>,
    writes: Arc<AtomicUsize>,
}

impl AnchorWitnessStore for MovingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let original = self.inner.current()?;
        if self.armed.load(Ordering::SeqCst) && self.reads.fetch_add(1, Ordering::SeqCst) > 0 {
            return Ok(original.map(|anchor| JournalAnchor {
                sequence: anchor.sequence,
                checkpoint_digest: Digest32::of_bytes(b"changed-witness"),
            }));
        }
        Ok(original)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.writes.fetch_add(1, Ordering::SeqCst);
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn physical_current_fences_witness_change_between_original_descriptor_reads() {
    let fixture = Fixture::new();
    let armed = Arc::new(AtomicBool::new(false));
    let reads = Arc::new(AtomicUsize::new(0));
    let writes = Arc::new(AtomicUsize::new(0));
    let witness = MovingWitness {
        inner: fixture.witness(),
        armed: Arc::clone(&armed),
        reads: Arc::clone(&reads),
        writes: Arc::clone(&writes),
    };
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        witness,
        config(),
        /*max_records*/ 128,
    ));
    checked(owner.drain());
    let original = owner.locked_bytes_for_test();
    let write_count = writes.load(Ordering::SeqCst);
    checked(owner.file.seek(SeekFrom::Start(11)));
    armed.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.read_current_checkpoint(),
        Err(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    assert_eq!(reads.load(Ordering::SeqCst), 2);
    assert_eq!(writes.load(Ordering::SeqCst), write_count);
    assert_eq!(owner.locked_bytes_for_test(), original);
    assert_eq!(checked(owner.file.stream_position()), 11);
    armed.store(false, Ordering::SeqCst);
    assert_eq!(owner.recover(), Err(CellGenerationErrorV2::CommitUncertain));
    assert_eq!(
        owner.read_current_checkpoint(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(writes.load(Ordering::SeqCst), write_count);
    assert_eq!(owner.locked_bytes_for_test(), original);
}
