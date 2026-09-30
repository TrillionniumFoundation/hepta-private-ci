//! Bounded streaming replay and incremental file append for the attempt owner.
use std::collections::BTreeMap;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use super::*;

#[path = "attempt_capacity.rs"]
mod capacity;
use capacity::AttemptCapacity;
#[path = "attempt_checkpoint.rs"]
mod checkpoint;

const MAGIC: &[u8; 8] = b"HEPTAT01";
const HEADER: u64 = 72;
const MAX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_FRAME: usize = 1024;
const MINIMUM_LIFECYCLE_EVENTS: usize = 7;
const MINIMUM_FRAME_BYTES: u64 = 136;
const MINIMUM_QUALIFICATION_BYTES: u64 =
    HEADER + MINIMUM_LIFECYCLE_EVENTS as u64 * MINIMUM_FRAME_BYTES;

pub struct LockedFileProductEvaluationAttemptJournalV1 {
    file: File,
    binding: Digest32,
    attempts: AttemptEvents,
    plan_owners: BTreeMap<[u8; 32], StableId>,
    capacity: AttemptCapacity,
    length: u64,
    event_count: usize,
    state_digest: Digest32,
    poisoned: bool,
}

impl LockedFileProductEvaluationAttemptJournalV1 {
    pub fn create(
        file: File,
        binding: Digest32,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        Self::create_with_limits(file, binding, MAX_BYTES, MAX_EVENTS)
    }

    /// Qualification-only constructor with stricter limits than the backend
    /// hard ceilings. It exists so admission-at-capacity behavior is exercised
    /// against the real file owner without allocating a 64 MiB fixture. These
    /// values can only reduce capacity and are not a deployment configuration.
    #[doc(hidden)]
    pub fn create_with_qualification_limits(
        file: File,
        binding: Digest32,
        maximum_bytes: u64,
        maximum_events: usize,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        validate_qualification_limits(maximum_bytes, maximum_events)?;
        Self::create_with_limits(file, binding, maximum_bytes, maximum_events)
    }

    fn create_with_limits(
        mut file: File,
        binding: Digest32,
        maximum_bytes: u64,
        maximum_events: usize,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
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
            plan_owners: BTreeMap::new(),
            capacity: AttemptCapacity::with_limits(maximum_bytes, maximum_events),
            length: HEADER,
            event_count: 0,
            state_digest: Digest32::of_bytes(&header),
            poisoned: false,
        })
    }

    /// Compatibility/source recovery only; production uses recover_with_anchor
    /// through the independently anchored owner. No tail is silently truncated.
    pub fn recover(
        file: File,
        binding: Digest32,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        Self::replay(file, binding, None, MAX_BYTES, MAX_EVENTS)
    }

    /// Qualification companion to `create_with_qualification_limits`.
    #[doc(hidden)]
    pub fn recover_with_qualification_limits(
        file: File,
        binding: Digest32,
        maximum_bytes: u64,
        maximum_events: usize,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        validate_qualification_limits(maximum_bytes, maximum_events)?;
        Self::replay(file, binding, None, maximum_bytes, maximum_events)
    }

    pub fn recover_with_anchor(
        file: File,
        binding: Digest32,
        minimum: ProductEvaluationAttemptAnchorV1,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        if minimum.binding != binding || minimum.state_digest.is_zero() {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        Self::replay(file, binding, Some(minimum), MAX_BYTES, MAX_EVENTS)
    }

    fn replay(
        mut file: File,
        binding: Digest32,
        minimum: Option<ProductEvaluationAttemptAnchorV1>,
        maximum_bytes: u64,
        maximum_events: usize,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        acquire(&file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > maximum_bytes {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        if length < HEADER {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut header = [0u8; HEADER as usize];
        file.read_exact(&mut header).map_err(io_error)?;
        if &header[..8] != MAGIC
            || &header[8..40] != binding.as_array()
            || &header[40..] != Digest32::of_bytes(&header[..40]).as_array()
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let mut state_digest = Digest32::of_bytes(&header);
        let mut anchor_seen = match minimum {
            Some(anchor) if anchor.event_count == 0 => anchor.state_digest == state_digest,
            None => true,
            Some(_) => false,
        };
        let mut attempts = BTreeMap::new();
        let mut plan_owners = BTreeMap::new();
        let mut capacity = AttemptCapacity::with_limits(maximum_bytes, maximum_events);
        let mut cursor = HEADER;
        let mut event_count = 0usize;
        while cursor < length {
            if length - cursor < 4 || event_count >= maximum_events {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let mut raw = [0u8; 4];
            file.read_exact(&mut raw).map_err(io_error)?;
            let count = u32::from_be_bytes(raw) as usize;
            if !(1..=MAX_FRAME).contains(&count) || length - cursor - 4 < count as u64 + 32 {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let mut payload = vec![0u8; count];
            let mut checksum = [0u8; 32];
            file.read_exact(&mut payload)
                .and_then(|()| file.read_exact(&mut checksum))
                .map_err(io_error)?;
            if &checksum != Digest32::of_bytes(&payload).as_array() {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let transition = decode_transition(&payload)?;
            let (receipt, appended) = preview_transition(&attempts, &plan_owners, transition)?;
            if !appended {
                return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
            }
            let previous = attempts
                .get(&receipt.transition.attempt_id)
                .and_then(|events: &Vec<ProductEvaluationAttemptReceiptV1>| events.last())
                .map(|event| event.transition.phase);
            let reservation = capacity.project(previous, &receipt.transition)?;
            install_transition(&mut attempts, &mut plan_owners, &receipt);
            capacity.install(reservation, &receipt.transition);
            event_count += 1;
            state_digest = advance_digest(state_digest, event_count, &payload);
            if let Some(anchor) = minimum
                && anchor.event_count == event_count as u64
            {
                anchor_seen = anchor.state_digest == state_digest;
            }
            cursor += 4 + count as u64 + 32;
        }
        if !anchor_seen || file.metadata().map_err(io_error)?.len() != length {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        // A complete tail may have survived an outcome-unknown sync. Establish
        // file durability before an anchored recovery acknowledges its frontier.
        file.sync_all()
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)?;
        // Legacy prefixes remain readable, including a prefix that did not
        // reserve enough space. New admission is refused while existing work
        // may spend the remaining bytes; migration never rewrites consumption.
        Ok(Self {
            file,
            binding,
            attempts,
            plan_owners,
            capacity,
            length,
            event_count,
            state_digest,
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

    pub fn anchor(
        &self,
    ) -> Result<ProductEvaluationAttemptAnchorV1, ProductEvaluationAttemptJournalErrorV1> {
        if self.poisoned {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(ProductEvaluationAttemptAnchorV1 {
            binding: self.binding,
            event_count: self.event_count as u64,
            state_digest: self.state_digest,
        })
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
        match self.file.metadata() {
            Ok(metadata) if metadata.len() == self.length => {}
            _ => {
                self.poisoned = true;
                return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
            }
        }
        let (receipt, appended) =
            preview_transition(&self.attempts, &self.plan_owners, transition.clone())?;
        if !appended {
            return Ok(receipt);
        }
        let (maximum_bytes, maximum_events) = self.capacity.limits();
        if self.event_count >= maximum_events {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        let payload = encode_transition(&transition)?;
        let next_length = self
            .length
            .checked_add(4 + payload.len() as u64 + 32)
            .filter(|value| *value <= maximum_bytes)
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        let previous = self
            .attempts
            .get(&transition.attempt_id)
            .and_then(|events| events.last())
            .map(|event| event.transition.phase);
        let reservation = self.capacity.project(previous, &transition)?;
        if previous.is_none() {
            // The intent is the admission boundary: reserve every future phase
            // before the runner can touch its holdout owner or provider.
            reservation.check(
                next_length,
                self.event_count + 1,
                maximum_bytes,
                maximum_events,
            )?;
        } else if self
            .capacity
            .reserved()
            .check(self.length, self.event_count, maximum_bytes, maximum_events)
            .is_ok()
        {
            reservation.check(
                next_length,
                self.event_count + 1,
                maximum_bytes,
                maximum_events,
            )?;
        }
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        if self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        install_transition(&mut self.attempts, &mut self.plan_owners, &receipt);
        self.capacity.install(reservation, &transition);
        self.length = next_length;
        self.event_count += 1;
        self.state_digest = advance_digest(self.state_digest, self.event_count, &payload);
        Ok(receipt)
    }

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        Ok(self
            .attempts
            .get(attempt_id)
            .and_then(|events| events.last())
            .cloned())
    }

    fn history(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        Ok(self.attempts.get(attempt_id).cloned().unwrap_or_default())
    }

    fn pending(
        &mut self,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        self.capacity.pending_page(&self.attempts, after, limit)
    }
}

fn validate_qualification_limits(
    maximum_bytes: u64,
    maximum_events: usize,
) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
    if !(MINIMUM_QUALIFICATION_BYTES..=MAX_BYTES).contains(&maximum_bytes)
        || !(MINIMUM_LIFECYCLE_EVENTS..=MAX_EVENTS).contains(&maximum_events)
    {
        return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
    }
    Ok(())
}

fn advance_digest(previous: Digest32, count: usize, payload: &[u8]) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.attempt-stream.v1".to_vec();
    bytes.extend_from_slice(previous.as_array());
    bytes.extend_from_slice(&(count as u64).to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(payload).as_array());
    Digest32::of_bytes(&bytes)
}

fn encode_transition(
    transition: &ProductEvaluationAttemptTransitionV1,
) -> Result<Vec<u8>, ProductEvaluationAttemptJournalErrorV1> {
    transition.validate()?;
    let id = transition.attempt_id.as_str().as_bytes();
    let length =
        u16::try_from(id.len()).map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let mut bytes = Vec::with_capacity(2 + id.len() + 97);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(transition.plan_digest.as_array());
    bytes.push(transition.phase.tag());
    bytes.extend_from_slice(transition.holdout_record_digest.as_array());
    bytes.extend_from_slice(transition.terminal_digest.as_array());
    if bytes.len() > MAX_FRAME {
        return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
    }
    Ok(bytes)
}

fn decode_transition(
    payload: &[u8],
) -> Result<ProductEvaluationAttemptTransitionV1, ProductEvaluationAttemptJournalErrorV1> {
    if payload.len() < 99 {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let length = usize::from(u16::from_be_bytes([payload[0], payload[1]]));
    if payload.len() != 99 + length {
        return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
    }
    let end = 2 + length;
    let id = std::str::from_utf8(&payload[2..end])
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
    let digest = |bytes: &[u8]| -> Result<Digest32, ProductEvaluationAttemptJournalErrorV1> {
        Ok(Digest32::from_array(bytes.try_into().map_err(|_| {
            ProductEvaluationAttemptJournalErrorV1::Corrupt
        })?))
    };
    let transition = ProductEvaluationAttemptTransitionV1 {
        attempt_id: StableId::new(id)
            .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Corrupt)?,
        plan_digest: digest(&payload[end..end + 32])?,
        phase: ProductEvaluationAttemptPhaseV1::from_tag(payload[end + 32])?,
        holdout_record_digest: digest(&payload[end + 33..end + 65])?,
        terminal_digest: digest(&payload[end + 65..end + 97])?,
    };
    transition.validate()?;
    Ok(transition)
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
