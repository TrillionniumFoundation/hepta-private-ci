//! Separate, durable and non-authorizing Neuron model-effect intent fence.
//!
//! Final-use nonces authenticate physical effects, but a newly signed nonce
//! must never replay a business tick that may already have crossed the device
//! boundary. This journal records the *tick* identity, not the nonce. It is
//! separate from the sparse checkpoint and external anchor witness.
//!
//! On recovery an unmatched Prepare quarantines the owner. It must be
//! reconciled independently; neither a missing checkpoint nor a new signed
//! grant permits automatic re-execution. This journal never mints authority.

use std::collections::BTreeSet;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::JournalScope;

const MAGIC: &[u8; 8] = b"HPTNEI01";
const HEADER_BYTES: usize = 112;
const RECORD_BYTES: usize = 97;
const MAX_RECORDS: usize = 65_536;
const RECORD_DOMAIN: &[u8] = b"hepta.neuron.effect-intent.record.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronEffectIntentErrorV1 {
    InvalidLimit,
    InvalidScope,
    UnsafeFile,
    UnsupportedPlatform,
    Busy,
    Corrupt,
    Capacity,
    DuplicateTick,
    PendingReconciliation,
    Mismatch,
    Poisoned,
    Io(io::ErrorKind),
}

impl From<io::Error> for NeuronEffectIntentErrorV1 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl std::fmt::Display for NeuronEffectIntentErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for NeuronEffectIntentErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NeuronEffectIntentStatusV1 {
    pub attempted_ticks: usize,
    pub durable_records: usize,
    pub unresolved_tick: Option<Digest32>,
    pub poisoned: bool,
}

/// Exactly one scope/generation owner holds the exclusive locked file. The
/// composing host must supply an owner-only, independently durable file name
/// and parent-directory synchronization before serving the first effect.
pub struct DurableNeuronEffectIntentV1 {
    file: File,
    limit: usize,
    records: usize,
    head: Digest32,
    scope: JournalScope,
    generation: Generation,
    attempted: BTreeSet<Digest32>,
    pending: Option<(Digest32, Digest32)>,
    poisoned: bool,
}

impl DurableNeuronEffectIntentV1 {
    /// Replays and validates every record. Never clears an unresolved intent.
    /// A distinct scope/generation cannot silently inherit this journal.
    #[cfg(unix)]
    pub fn open(
        mut file: File,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
    ) -> Result<Self, NeuronEffectIntentErrorV1> {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if !(2..=MAX_RECORDS).contains(&max_records) {
            return Err(NeuronEffectIntentErrorV1::InvalidLimit);
        }
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(NeuronEffectIntentErrorV1::InvalidScope);
        }
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.permissions().mode() & 0o077 != 0
        {
            return Err(NeuronEffectIntentErrorV1::UnsafeFile);
        }
        file.try_lock().map_err(|_| NeuronEffectIntentErrorV1::Busy)?;
        let expected_header = header_bytes(scope, generation);
        let length = file.metadata()?.len();
        if length == 0 {
            file.write_all(&expected_header)?;
            file.sync_all()?;
        } else {
            let maximum = HEADER_BYTES as u64 + max_records as u64 * RECORD_BYTES as u64;
            if length < HEADER_BYTES as u64
                || length > maximum
                || (length - HEADER_BYTES as u64) % RECORD_BYTES as u64 != 0
            {
                return Err(NeuronEffectIntentErrorV1::Corrupt);
            }
        }
        file.seek(SeekFrom::Start(0))?;
        let mut actual_header = [0_u8; HEADER_BYTES];
        file.read_exact(&mut actual_header)?;
        if actual_header != expected_header {
            return Err(NeuronEffectIntentErrorV1::Corrupt);
        }
        let records = ((file.metadata()?.len() - HEADER_BYTES as u64) / RECORD_BYTES as u64) as usize;
        let mut attempted = BTreeSet::new();
        let mut pending = None;
        let mut head = Digest32::ZERO;
        for _ in 0..records {
            let mut encoded = [0_u8; RECORD_BYTES];
            file.read_exact(&mut encoded)?;
            let kind = encoded[0];
            let tick = Digest32::from_array(
                encoded[1..33]
                    .try_into()
                    .map_err(|_| NeuronEffectIntentErrorV1::Corrupt)?,
            );
            let checkpoint = Digest32::from_array(
                encoded[33..65]
                    .try_into()
                    .map_err(|_| NeuronEffectIntentErrorV1::Corrupt)?,
            );
            let expected = record_digest(head, kind, tick, checkpoint);
            if tick.is_zero() || &encoded[65..97] != expected.as_array().as_slice() {
                return Err(NeuronEffectIntentErrorV1::Corrupt);
            }
            match kind {
                b'P' if pending.is_none() && attempted.insert(tick) => {
                    pending = Some((tick, checkpoint));
                }
                b'R' if pending.is_some_and(|(id, previous)| {
                    id == tick && !checkpoint.is_zero() && checkpoint != previous
                }) => {
                    pending = None;
                }
                _ => return Err(NeuronEffectIntentErrorV1::Corrupt),
            }
            head = expected;
        }
        Ok(Self {
            file,
            limit: max_records,
            records,
            head,
            scope,
            generation,
            attempted,
            pending,
            poisoned: false,
        })
    }

    /// Unsupported platforms cannot claim exclusive owner-only durability.
    #[cfg(not(unix))]
    pub fn open(
        _file: File,
        _scope: JournalScope,
        _generation: Generation,
        _max_records: usize,
    ) -> Result<Self, NeuronEffectIntentErrorV1> {
        Err(NeuronEffectIntentErrorV1::UnsupportedPlatform)
    }

    pub fn status(&self) -> NeuronEffectIntentStatusV1 {
        NeuronEffectIntentStatusV1 {
            attempted_ticks: self.attempted.len(),
            durable_records: self.records,
            unresolved_tick: self.pending.map(|(tick, _)| tick),
            poisoned: self.poisoned,
        }
    }

    /// A signed NDU read does not change the owning Neuron scope/generation.
    /// Bind the intent journal to the same source subject and objective as
    /// the sparse runtime, not merely a caller-provided file handle.
    pub fn matches_tick_scope(
        &self,
        subject: &StableId,
        objective: Digest32,
        generation: Generation,
    ) -> bool {
        self.generation == generation
            && self.scope.objective_digest == objective
            && crate::runtime_types::subject_scope_digest(subject).ok()
                == Some(self.scope.scope_digest)
    }

    pub fn can_prepare(&self, tick_digest: Digest32) -> Result<(), NeuronEffectIntentErrorV1> {
        if self.poisoned {
            return Err(NeuronEffectIntentErrorV1::Poisoned);
        }
        if self.pending.is_some() {
            return Err(NeuronEffectIntentErrorV1::PendingReconciliation);
        }
        if tick_digest.is_zero() {
            return Err(NeuronEffectIntentErrorV1::Mismatch);
        }
        if self.attempted.contains(&tick_digest) {
            return Err(NeuronEffectIntentErrorV1::DuplicateTick);
        }
        // Reserve the matching durable resolution record before any effect.
        if self.records.checked_add(2).is_none_or(|count| count > self.limit) {
            return Err(NeuronEffectIntentErrorV1::Capacity);
        }
        Ok(())
    }

    /// This sync completes BEFORE issuing the physical model request.
    pub fn prepare(
        &mut self,
        tick_digest: Digest32,
        previous_checkpoint: Digest32,
    ) -> Result<(), NeuronEffectIntentErrorV1> {
        self.can_prepare(tick_digest)?;
        self.append(b'P', tick_digest, previous_checkpoint)?;
        self.attempted.insert(tick_digest);
        self.pending = Some((tick_digest, previous_checkpoint));
        Ok(())
    }

    /// Only the owner that independently verified the actual committed
    /// checkpoint and the live NDU/authority frontier may call resolve.
    /// A crash leaves an unmatched Prepare; the caller must NEVER synthesize
    /// Resolve from its input digest alone.
    pub fn resolve(
        &mut self,
        tick_digest: Digest32,
        committed_checkpoint: Digest32,
    ) -> Result<(), NeuronEffectIntentErrorV1> {
        if self.poisoned {
            return Err(NeuronEffectIntentErrorV1::Poisoned);
        }
        if !self.pending.is_some_and(|(pending, previous)| {
            pending == tick_digest && !committed_checkpoint.is_zero()
                && committed_checkpoint != previous
        }) {
            return Err(NeuronEffectIntentErrorV1::Mismatch);
        }
        self.append(b'R', tick_digest, committed_checkpoint)?;
        self.pending = None;
        Ok(())
    }

    fn append(
        &mut self,
        kind: u8,
        tick_digest: Digest32,
        checkpoint_digest: Digest32,
    ) -> Result<(), NeuronEffectIntentErrorV1> {
        if self.poisoned {
            return Err(NeuronEffectIntentErrorV1::Poisoned);
        }
        if self.records >= self.limit {
            return Err(NeuronEffectIntentErrorV1::Capacity);
        }
        let digest = record_digest(self.head, kind, tick_digest, checkpoint_digest);
        let mut bytes = [0_u8; RECORD_BYTES];
        bytes[0] = kind;
        bytes[1..33].copy_from_slice(tick_digest.as_array());
        bytes[33..65].copy_from_slice(checkpoint_digest.as_array());
        bytes[65..97].copy_from_slice(digest.as_array());
        self.poisoned = true;
        let expected_size = (HEADER_BYTES + self.records * RECORD_BYTES) as u64;
        if self.file.seek(SeekFrom::End(0))? != expected_size {
            return Err(NeuronEffectIntentErrorV1::Corrupt);
        }
        self.file.write_all(&bytes)?;
        self.file.sync_all()?;
        self.records += 1;
        self.head = digest;
        self.poisoned = false;
        Ok(())
    }
}

fn header_bytes(scope: JournalScope, generation: Generation) -> [u8; HEADER_BYTES] {
    let mut bytes = [0_u8; HEADER_BYTES];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..40].copy_from_slice(scope.scope_digest.as_array());
    bytes[40..72].copy_from_slice(scope.objective_digest.as_array());
    bytes[72..80].copy_from_slice(&generation.get().to_be_bytes());
    let digest = Digest32::of_bytes(&bytes[..80]);
    bytes[80..112].copy_from_slice(digest.as_array());
    bytes
}

fn record_digest(
    previous: Digest32,
    kind: u8,
    tick: Digest32,
    checkpoint: Digest32,
) -> Digest32 {
    let mut bytes = Vec::with_capacity(RECORD_DOMAIN.len() + 97);
    bytes.extend_from_slice(RECORD_DOMAIN);
    bytes.extend_from_slice(previous.as_array());
    bytes.push(kind);
    bytes.extend_from_slice(tick.as_array());
    bytes.extend_from_slice(checkpoint.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(all(test, unix))]
#[path = "effect_intent_tests.rs"]
mod tests;
