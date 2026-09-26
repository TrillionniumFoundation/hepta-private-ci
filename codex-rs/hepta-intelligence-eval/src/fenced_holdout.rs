//! Fenced compare-and-swap owner for production final-holdout consumption.
//!
//! The existing file adapter is intentionally a single-host/cooperative-owner
//! mechanism. This module defines the stronger host boundary required when more
//! than one process or machine can contend for authoritative holdout state.
//! The host store must provide linearizable compare-and-swap semantics and must
//! report uncertain writes as `Indeterminate`.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CrossFoldPlanReceiptV1;
use crate::FinalHoldoutJournalError;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutJournalSnapshotV1;
use crate::FinalHoldoutJournalV1;

const MAX_RECORDS: usize = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldoutWriterFenceV1 {
    pub owner_id: StableId,
    pub generation: u64,
    pub lease_digest: Digest32,
}

impl HoldoutWriterFenceV1 {
    fn validate(&self) -> Result<(), FencedHoldoutError> {
        if self.generation == 0 || self.lease_digest.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalHoldoutCasRecordV1 {
    pub binding: Digest32,
    pub fence: HoldoutWriterFenceV1,
    pub journal: FinalHoldoutJournalSnapshotV1,
    pub state_digest: Digest32,
}

impl FinalHoldoutCasRecordV1 {
    pub(crate) fn new(
        binding: Digest32,
        fence: HoldoutWriterFenceV1,
        journal: FinalHoldoutJournalSnapshotV1,
    ) -> Result<Self, FencedHoldoutError> {
        if binding.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        fence.validate()?;
        let state_digest = digest_state(binding, &fence, &journal)?;
        Ok(Self {
            binding,
            fence,
            journal,
            state_digest,
        })
    }

    pub(crate) fn validate(&self, binding: Digest32) -> Result<(), FencedHoldoutError> {
        if self.binding != binding
            || self.state_digest != digest_state(self.binding, &self.fence, &self.journal)?
        {
            return Err(FencedHoldoutError::Corrupt);
        }
        self.fence.validate()?;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalHoldoutCasStoreError {
    /// The expected state no longer matches the authoritative state.
    Conflict,
    /// The store rejected the operation before it could become authoritative.
    Rejected,
    /// The caller cannot determine whether the write became authoritative.
    Indeterminate,
}

impl fmt::Display for FinalHoldoutCasStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for FinalHoldoutCasStoreError {}

/// Host-provided authoritative storage.
///
/// `compare_and_swap` must be linearizable across every process and machine
/// participating in the same binding. `expected = None` means the record must
/// not exist. An uncertain commit must return `Indeterminate`, never `Rejected`.
pub trait FinalHoldoutCasStoreV1 {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError>;

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalHoldoutCasAnchorV1 {
    pub fence_generation: u64,
    pub record_count: u64,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct HoldoutFenceIssuerV1 {
    owner_id: StableId,
    authority_digest: Digest32,
    next_generation: u64,
}

impl HoldoutFenceIssuerV1 {
    pub fn resume(
        owner_id: StableId,
        authority_digest: Digest32,
        minimum: Option<FinalHoldoutCasAnchorV1>,
    ) -> Result<Self, FencedHoldoutError> {
        if authority_digest.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        let next_generation = minimum
            .map(|anchor| anchor.fence_generation.checked_add(1))
            .unwrap_or(Some(1))
            .ok_or(FencedHoldoutError::Binding)?;
        Ok(Self {
            owner_id,
            authority_digest,
            next_generation,
        })
    }

    pub fn issue(
        &mut self,
        lease_digest: Digest32,
    ) -> Result<HoldoutWriterFenceV1, FencedHoldoutError> {
        if lease_digest.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        let generation = self.next_generation;
        self.next_generation = generation
            .checked_add(1)
            .ok_or(FencedHoldoutError::Binding)?;
        let mut bytes = b"hepta.intelligence-eval.holdout-fence-lease.v1".to_vec();
        bytes.extend_from_slice(self.authority_digest.as_array());
        bytes.extend_from_slice(lease_digest.as_array());
        bytes.extend_from_slice(&generation.to_be_bytes());
        Ok(HoldoutWriterFenceV1 {
            owner_id: self.owner_id.clone(),
            generation,
            lease_digest: Digest32::of_bytes(&bytes),
        })
    }
}

pub struct FencedFinalHoldoutOwnerV1<S> {
    store: S,
    binding: Digest32,
    fence: HoldoutWriterFenceV1,
    journal: FinalHoldoutJournalV1,
    state_digest: Digest32,
    poisoned: bool,
}

impl<S: FinalHoldoutCasStoreV1> FencedFinalHoldoutOwnerV1<S> {
    /// Initialize a previously absent authoritative record.
    pub fn initialize(
        mut store: S,
        binding: Digest32,
        fence: HoldoutWriterFenceV1,
    ) -> Result<Self, FencedHoldoutError> {
        if binding.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        fence.validate()?;
        if store.load(binding)?.is_some() {
            return Err(FencedHoldoutError::Conflict);
        }
        let journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
            .map_err(FencedHoldoutError::Journal)?;
        let record = FinalHoldoutCasRecordV1::new(binding, fence.clone(), journal.snapshot())?;
        apply_cas(&mut store, binding, None, &record)?;
        Ok(Self {
            store,
            binding,
            fence,
            journal,
            state_digest: record.state_digest,
            poisoned: false,
        })
    }

    /// Recover current state and, when the supplied generation is newer,
    /// atomically take ownership without rewriting or truncating journal history.
    pub fn recover(
        mut store: S,
        binding: Digest32,
        fence: HoldoutWriterFenceV1,
    ) -> Result<Self, FencedHoldoutError> {
        if binding.is_zero() {
            return Err(FencedHoldoutError::Binding);
        }
        fence.validate()?;
        let current = store.load(binding)?.ok_or(FencedHoldoutError::Missing)?;
        current.validate(binding)?;
        let journal = FinalHoldoutJournalV1::from_snapshot_with_record_limit(
            current.journal.clone(),
            MAX_RECORDS,
        )
        .map_err(|_| FencedHoldoutError::Corrupt)?;

        let record = if fence == current.fence {
            current
        } else {
            if fence.generation <= current.fence.generation {
                return Err(FencedHoldoutError::StaleFence);
            }
            let next = FinalHoldoutCasRecordV1::new(binding, fence.clone(), journal.snapshot())?;
            apply_cas(&mut store, binding, Some(current.state_digest), &next)?;
            next
        };

        Ok(Self {
            store,
            binding,
            fence,
            journal,
            state_digest: record.state_digest,
            poisoned: false,
        })
    }

    /// Persist the semantic transition with CAS before publishing it in memory.
    /// A stale writer therefore cannot consume a final holdout after takeover.
    pub fn consume(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, FencedHoldoutError> {
        if self.poisoned {
            return Err(FencedHoldoutError::Poisoned);
        }
        let mut candidate = self.journal.clone();
        let receipt = candidate
            .consume(candidate.head_digest(), plan)
            .map_err(FencedHoldoutError::Journal)?;
        let next =
            FinalHoldoutCasRecordV1::new(self.binding, self.fence.clone(), candidate.snapshot())?;

        match self
            .store
            .compare_and_swap(self.binding, Some(self.state_digest), &next)
        {
            Ok(()) => {
                self.journal = candidate;
                self.state_digest = next.state_digest;
                Ok(receipt)
            }
            Err(FinalHoldoutCasStoreError::Conflict) => {
                self.poisoned = true;
                Err(FencedHoldoutError::Conflict)
            }
            Err(FinalHoldoutCasStoreError::Rejected) => Err(FencedHoldoutError::Rejected),
            Err(FinalHoldoutCasStoreError::Indeterminate) => {
                self.poisoned = true;
                Err(FencedHoldoutError::Indeterminate)
            }
        }
    }

    #[must_use]
    pub fn fence(&self) -> &HoldoutWriterFenceV1 {
        &self.fence
    }

    #[must_use]
    pub fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub fn anchor(&self) -> FinalHoldoutCasAnchorV1 {
        FinalHoldoutCasAnchorV1 {
            fence_generation: self.fence.generation,
            record_count: self.journal.records().len() as u64,
            state_digest: self.state_digest,
        }
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.journal.head_digest()
    }

    #[must_use]
    pub fn is_poisoned(&self) -> bool {
        self.poisoned
    }

    #[must_use]
    pub fn into_store(self) -> S {
        self.store
    }
}

fn apply_cas<S: FinalHoldoutCasStoreV1>(
    store: &mut S,
    binding: Digest32,
    expected: Option<Digest32>,
    next: &FinalHoldoutCasRecordV1,
) -> Result<(), FencedHoldoutError> {
    match store.compare_and_swap(binding, expected, next) {
        Ok(()) => Ok(()),
        Err(FinalHoldoutCasStoreError::Conflict) => Err(FencedHoldoutError::Conflict),
        Err(FinalHoldoutCasStoreError::Rejected) => Err(FencedHoldoutError::Rejected),
        Err(FinalHoldoutCasStoreError::Indeterminate) => Err(FencedHoldoutError::Indeterminate),
    }
}

fn digest_state(
    binding: Digest32,
    fence: &HoldoutWriterFenceV1,
    journal: &FinalHoldoutJournalSnapshotV1,
) -> Result<Digest32, FencedHoldoutError> {
    digest_state_frontier(binding, fence, journal.records.len(), journal.head_digest)
}

// Shared canonical encoder only; this does not authenticate or publish a state.
// The locked-file replay caller supplies a journal built by validated consume.
pub(crate) fn digest_state_frontier(
    binding: Digest32,
    fence: &HoldoutWriterFenceV1,
    record_count: usize,
    head_digest: Digest32,
) -> Result<Digest32, FencedHoldoutError> {
    if record_count > MAX_RECORDS {
        return Err(FencedHoldoutError::Corrupt);
    }
    let owner = fence.owner_id.as_str().as_bytes();
    let owner_len = u32::try_from(owner.len()).map_err(|_| FencedHoldoutError::Binding)?;
    let record_count = u64::try_from(record_count).map_err(|_| FencedHoldoutError::Corrupt)?;
    let mut bytes = b"hepta.intelligence-eval.final-holdout-cas-state.v1".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&owner_len.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&fence.generation.to_be_bytes());
    bytes.extend_from_slice(fence.lease_digest.as_array());
    bytes.extend_from_slice(&record_count.to_be_bytes());
    bytes.extend_from_slice(head_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FencedHoldoutError {
    Binding,
    Missing,
    Corrupt,
    StaleFence,
    Conflict,
    Rejected,
    Indeterminate,
    Poisoned,
    Store(FinalHoldoutCasStoreError),
    Journal(FinalHoldoutJournalError),
}

impl fmt::Display for FencedHoldoutError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for FencedHoldoutError {}

impl From<FinalHoldoutCasStoreError> for FencedHoldoutError {
    fn from(value: FinalHoldoutCasStoreError) -> Self {
        Self::Store(value)
    }
}

#[cfg(test)]
#[path = "fenced_holdout_tests.rs"]
mod tests;
