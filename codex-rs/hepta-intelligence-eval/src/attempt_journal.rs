//! Durable lifecycle journal for product evaluation attempts.
//!
//! The journal records the irreversible final-holdout consumption before a
//! provider may release observations, then records exactly one terminal state.
//! Exact retries are idempotent. Reusing an attempt identity with different
//! semantics, skipping the consumed state, or changing a terminal result fails
//! closed.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTAT01";
const HEADER: usize = 72;
const MAX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_FRAME: usize = 1024;
const MAX_EVENTS: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptPhaseV1 {
    HoldoutConsumed,
    ComparisonSealed,
    Failed,
}

impl ProductEvaluationAttemptPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::HoldoutConsumed => 0,
            Self::ComparisonSealed => 1,
            Self::Failed => 2,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        match tag {
            0 => Ok(Self::HoldoutConsumed),
            1 => Ok(Self::ComparisonSealed),
            2 => Ok(Self::Failed),
            _ => Err(ProductEvaluationAttemptJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptTransitionV1 {
    pub attempt_id: StableId,
    pub plan_digest: Digest32,
    pub phase: ProductEvaluationAttemptPhaseV1,
    pub holdout_record_digest: Digest32,
    /// `ZERO` for `HoldoutConsumed`; the execution digest for
    /// `ComparisonSealed`; a deterministic failure digest for `Failed`.
    pub terminal_digest: Digest32,
}

impl ProductEvaluationAttemptTransitionV1 {
    pub fn holdout_consumed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            holdout_record_digest,
            terminal_digest: Digest32::ZERO,
        }
    }

    pub fn comparison_sealed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        execution_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::ComparisonSealed,
            holdout_record_digest,
            terminal_digest: execution_digest,
        }
    }

    pub fn failed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        failure_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::Failed,
            holdout_record_digest,
            terminal_digest: failure_digest,
        }
    }

    fn validate(&self) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        if self.plan_digest.is_zero() || self.holdout_record_digest.is_zero() {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        match self.phase {
            ProductEvaluationAttemptPhaseV1::HoldoutConsumed => {
                if !self.terminal_digest.is_zero() {
                    return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
                }
            }
            ProductEvaluationAttemptPhaseV1::ComparisonSealed
            | ProductEvaluationAttemptPhaseV1::Failed => {
                if self.terminal_digest.is_zero() {
                    return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptReceiptV1 {
    pub transition: ProductEvaluationAttemptTransitionV1,
    pub sequence: u64,
    pub predecessor_digest: Digest32,
    pub event_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ProductEvaluationAttemptReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        self.transition.validate()?;
        if self.sequence == 0
            || self.event_digest.is_zero()
            || self.authority.grants_any()
            || self.event_digest != event_digest(
                &self.transition,
                self.sequence,
                self.predecessor_digest,
            )
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        Ok(())
    }
}

pub trait ProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1>;

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>;
}

#[derive(Clone, Debug, Default)]
pub struct InMemoryProductEvaluationAttemptJournalV1 {
    attempts: BTreeMap<StableId, Vec<ProductEvaluationAttemptReceiptV1>>,
}

impl ProductEvaluationAttemptJournalV1 for InMemoryProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        apply_transition(&mut self.attempts, transition).map(|(receipt, _)| receipt)
    }

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(self
            .attempts
            .get(attempt_id)
            .and_then(|events| events.last())
            .cloned())
    }
}

pub struct LockedFileProductEvaluationAttemptJournalV1 {
    file: File,
    binding: Digest32,
    attempts: BTreeMap<StableId, Vec<ProductEvaluationAttemptReceiptV1>>,
    length: u64,
    event_count: usize,
    poisoned: bool,
}

impl LockedFileProductEvaluationAttemptJournalV1 {
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(ProductEvaluationAttemptJournalErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            attempts: BTreeMap::new(),
            length: HEADER as u64,
            event_count: 0,
            poisoned: false,
        })
    }

    pub fn recover(mut file: File, binding: Digest32) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        acquire(&file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length || bytes.len() < HEADER {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }

        let mut attempts = BTreeMap::new();
        let mut cursor = HEADER;
        let mut event_count = 0usize;
        while cursor < bytes.len() {
            let raw = bytes
                .get(cursor..cursor + 4)
                .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
            let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
            if !(1..=MAX_FRAME).contains(&count) {
                return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
            }
            cursor += 4;
            let payload = bytes
                .get(cursor..cursor + count)
                .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
            cursor += count;
            let checksum = bytes
                .get(cursor..cursor + 32)
                .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
            cursor += 32;
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let transition = decode_transition(payload)?;
            let (_, appended) = apply_transition(&mut attempts, transition)?;
            if !appended {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            event_count = event_count
                .checked_add(1)
                .ok_or(ProductEvaluationAttemptJournalErrorV1::Capacity)?;
            if event_count > MAX_EVENTS {
                return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
            }
        }
        Ok(Self {
            file,
            binding,
            attempts,
            length,
            event_count,
            poisoned: false,
        })
    }

    #[must_use]
    pub const fn byte_len(&self) -> u64 {
        self.length
    }

    #[must_use]
    pub const fn event_count(&self) -> usize {
        self.event_count
    }

    #[must_use]
    pub const fn binding(&self) -> Digest32 {
        self.binding
    }
}

impl ProductEvaluationAttemptJournalV1 for LockedFileProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        if self.poisoned {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        if self
            .file
            .metadata()
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)?
            .len()
            != self.length
        {
            self.poisoned = true;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }

        let mut next = self.attempts.clone();
        let (receipt, appended) = apply_transition(&mut next, transition.clone())?;
        if !appended {
            return Ok(receipt);
        }
        if self.event_count >= MAX_EVENTS {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        let payload = encode_transition(&transition)?;
        if payload.len() > MAX_FRAME {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        let next_length = self
            .length
            .checked_add(4)
            .and_then(|value| value.checked_add(payload.len() as u64))
            .and_then(|value| value.checked_add(32))
            .filter(|value| *value <= MAX_BYTES)
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        let write = self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all());
        if write.is_err() {
            self.poisoned = true;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        self.attempts = next;
        self.length = next_length;
        self.event_count += 1;
        Ok(receipt)
    }

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        if self.poisoned {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(self
            .attempts
            .get(attempt_id)
            .and_then(|events| events.last())
            .cloned())
    }
}

fn apply_transition(
    attempts: &mut BTreeMap<StableId, Vec<ProductEvaluationAttemptReceiptV1>>,
    transition: ProductEvaluationAttemptTransitionV1,
) -> Result<(ProductEvaluationAttemptReceiptV1, bool), ProductEvaluationAttemptJournalErrorV1> {
    transition.validate()?;
    let events = attempts.entry(transition.attempt_id.clone()).or_default();
    if let Some(existing) = events
        .iter()
        .find(|receipt| receipt.transition == transition)
        .cloned()
    {
        return Ok((existing, false));
    }
    match events.as_slice() {
        [] if transition.phase == ProductEvaluationAttemptPhaseV1::HoldoutConsumed => {}
        [consumed]
            if consumed.transition.phase == ProductEvaluationAttemptPhaseV1::HoldoutConsumed
                && matches!(
                    transition.phase,
                    ProductEvaluationAttemptPhaseV1::ComparisonSealed
                        | ProductEvaluationAttemptPhaseV1::Failed
                )
                && consumed.transition.plan_digest == transition.plan_digest
                && consumed.transition.holdout_record_digest
                    == transition.holdout_record_digest => {}
        [] => return Err(ProductEvaluationAttemptJournalErrorV1::MissingConsumption),
        _ => return Err(ProductEvaluationAttemptJournalErrorV1::Conflict),
    }
    let sequence = u64::try_from(events.len() + 1)
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let predecessor_digest = events
        .last()
        .map_or(Digest32::ZERO, |receipt| receipt.event_digest);
    let receipt = ProductEvaluationAttemptReceiptV1 {
        event_digest: event_digest(&transition, sequence, predecessor_digest),
        transition,
        sequence,
        predecessor_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate_integrity()?;
    events.push(receipt.clone());
    Ok((receipt, true))
}

fn event_digest(
    transition: &ProductEvaluationAttemptTransitionV1,
    sequence: u64,
    predecessor_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.attempt-event.v1".to_vec();
    push_id(&mut bytes, &transition.attempt_id);
    bytes.extend_from_slice(transition.plan_digest.as_array());
    bytes.push(transition.phase.tag());
    bytes.extend_from_slice(transition.holdout_record_digest.as_array());
    bytes.extend_from_slice(transition.terminal_digest.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn encode_transition(
    transition: &ProductEvaluationAttemptTransitionV1,
) -> Result<Vec<u8>, ProductEvaluationAttemptJournalErrorV1> {
    transition.validate()?;
    let id = transition.attempt_id.as_str().as_bytes();
    let length = u16::try_from(id.len()).map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let mut bytes = Vec::with_capacity(2 + id.len() + 97);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(transition.plan_digest.as_array());
    bytes.push(transition.phase.tag());
    bytes.extend_from_slice(transition.holdout_record_digest.as_array());
    bytes.extend_from_slice(transition.terminal_digest.as_array());
    Ok(bytes)
}

fn decode_transition(
    payload: &[u8],
) -> Result<ProductEvaluationAttemptTransitionV1, ProductEvaluationAttemptJournalErrorV1> {
    if payload.len() < 2 + 32 + 1 + 32 + 32 {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let length = u16::from_be_bytes([payload[0], payload[1]]) as usize;
    let id_start = 2usize;
    let id_end = id_start
        .checked_add(length)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let plan_end = id_end
        .checked_add(32)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let phase_end = plan_end
        .checked_add(1)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let holdout_end = phase_end
        .checked_add(32)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let terminal_end = holdout_end
        .checked_add(32)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    if terminal_end != payload.len() {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let id = std::str::from_utf8(
        payload
            .get(id_start..id_end)
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
    )
    .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let plan = payload
        .get(id_end..plan_end)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let holdout = payload
        .get(phase_end..holdout_end)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let terminal = payload
        .get(holdout_end..terminal_end)
        .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let transition = ProductEvaluationAttemptTransitionV1 {
        attempt_id: StableId::new(id)
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
        plan_digest: Digest32::from_array(
            plan.try_into()
                .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
        ),
        phase: ProductEvaluationAttemptPhaseV1::from_tag(payload[plan_end])?,
        holdout_record_digest: Digest32::from_array(
            holdout
                .try_into()
                .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
        ),
        terminal_digest: Digest32::from_array(
            terminal
                .try_into()
                .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
        ),
    };
    transition.validate()?;
    Ok(transition)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn acquire(file: &File, binding: Digest32) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
    if binding.is_zero() {
        return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.file_type().is_file() {
        return Err(ProductEvaluationAttemptJournalErrorV1::NotRegular);
    }
    match file.try_lock() {
        Ok(()) => Ok(()),
        Err(TryLockError::WouldBlock) => Err(ProductEvaluationAttemptJournalErrorV1::Busy),
        Err(TryLockError::Error(error)) => Err(io_error(error)),
    }
}

fn io_error(error: io::Error) -> ProductEvaluationAttemptJournalErrorV1 {
    ProductEvaluationAttemptJournalErrorV1::Io(error.kind())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptJournalErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    Corrupt,
    Conflict,
    MissingConsumption,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for ProductEvaluationAttemptJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationAttemptJournalErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::NamedTempFile;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn consumed_then_terminal_is_replayable_and_exact_retry_is_idempotent() {
        let temp = NamedTempFile::new().expect("temporary journal");
        let binding = digest("attempt-journal-binding");
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
            temp.reopen().expect("reopen"),
            binding,
        )
        .expect("create journal");
        let consumed = ProductEvaluationAttemptTransitionV1::holdout_consumed(
            id("attempt:1"),
            digest("plan"),
            digest("holdout"),
        );
        let first = journal.append(consumed.clone()).expect("record consumed");
        let retry = journal.append(consumed).expect("exact retry");
        assert_eq!(first, retry);
        assert_eq!(journal.event_count(), 1);

        let terminal = ProductEvaluationAttemptTransitionV1::comparison_sealed(
            id("attempt:1"),
            digest("plan"),
            digest("holdout"),
            digest("execution"),
        );
        let sealed = journal.append(terminal).expect("record sealed");
        assert_eq!(sealed.sequence, 2);
        let length = journal.byte_len();
        drop(journal);

        let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover(
            temp.reopen().expect("reopen recovered"),
            binding,
        )
        .expect("recover journal");
        assert_eq!(recovered.byte_len(), length);
        assert_eq!(
            recovered.latest(&id("attempt:1")).expect("latest"),
            Some(sealed)
        );
    }

    #[test]
    fn terminal_without_consumption_and_conflicting_terminal_fail_closed() {
        let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
        let terminal = ProductEvaluationAttemptTransitionV1::failed(
            id("attempt:2"),
            digest("plan"),
            digest("holdout"),
            digest("failure"),
        );
        assert_eq!(
            journal.append(terminal),
            Err(ProductEvaluationAttemptJournalErrorV1::MissingConsumption)
        );
        journal
            .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
                id("attempt:2"),
                digest("plan"),
                digest("holdout"),
            ))
            .expect("record consumed");
        journal
            .append(ProductEvaluationAttemptTransitionV1::failed(
                id("attempt:2"),
                digest("plan"),
                digest("holdout"),
                digest("failure"),
            ))
            .expect("record failure");
        assert_eq!(
            journal.append(ProductEvaluationAttemptTransitionV1::failed(
                id("attempt:2"),
                digest("plan"),
                digest("holdout"),
                digest("different failure"),
            )),
            Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
        );
    }

    #[test]
    fn truncated_frame_and_second_writer_are_rejected() {
        let temp = NamedTempFile::new().expect("temporary journal");
        let binding = digest("attempt-journal-binding-2");
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
            temp.reopen().expect("reopen"),
            binding,
        )
        .expect("create journal");
        assert_eq!(
            LockedFileProductEvaluationAttemptJournalV1::recover(
                temp.reopen().expect("second writer"),
                binding,
            )
            .map(|_| ()),
            Err(ProductEvaluationAttemptJournalErrorV1::Busy)
        );
        journal
            .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
                id("attempt:3"),
                digest("plan"),
                digest("holdout"),
            ))
            .expect("append");
        let length = journal.byte_len();
        drop(journal);
        temp.as_file()
            .set_len(length - 1)
            .expect("truncate last checksum byte");
        assert!(matches!(
            LockedFileProductEvaluationAttemptJournalV1::recover(
                temp.reopen().expect("reopen truncated"),
                binding,
            ),
            Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
        ));
        let _ = fs::metadata(temp.path()).expect("journal remains inspectable");
    }
}
