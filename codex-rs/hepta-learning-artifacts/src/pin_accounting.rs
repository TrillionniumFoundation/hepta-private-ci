//! Explicit process-local pin and pending-erasure accounting.
//!
//! The accounting object is supplied by the embedding host. Dropping a guard
//! releases only the process-local pin; it is not proof of physical deletion,
//! backup deletion or fleet-wide quiescence.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::StableId;

use crate::LoadedPinnedCandidate;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RevalidatingCandidate;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_pinned_candidate;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactPinMetricsV1 {
    pub artifacts_with_active_pins: u64,
    pub active_pins: u64,
    pub pinned_bytes: u64,
    pub pending_erasure_bytes: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactPinStatusV1 {
    pub active_pins: u64,
    pub pinned_bytes: u64,
    pub pending_erasure_bytes: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct PinEntryV1 {
    active_pins: u64,
    pinned_bytes: u64,
    pending_erasure_bytes: u64,
}

#[derive(Debug, Default)]
pub struct ArtifactPinAccountingV1 {
    entries: Mutex<BTreeMap<StableId, PinEntryV1>>,
}

impl ArtifactPinAccountingV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn pin(
        self: &Arc<Self>,
        artifact_id: StableId,
        bytes: u64,
    ) -> Result<ArtifactPinGuardV1, ArtifactPinAccountingError> {
        if bytes == 0 {
            return Err(ArtifactPinAccountingError::InvalidBytes);
        }
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| ArtifactPinAccountingError::Poisoned)?;
        let entry = entries.entry(artifact_id.clone()).or_default();
        entry.active_pins = entry
            .active_pins
            .checked_add(1)
            .ok_or(ArtifactPinAccountingError::Capacity)?;
        entry.pinned_bytes = entry
            .pinned_bytes
            .checked_add(bytes)
            .ok_or(ArtifactPinAccountingError::Capacity)?;
        drop(entries);
        Ok(ArtifactPinGuardV1 {
            accounting: Arc::clone(self),
            artifact_id,
            bytes,
            pending_erasure: false,
        })
    }

    pub fn metrics(&self) -> Result<ArtifactPinMetricsV1, ArtifactPinAccountingError> {
        let entries = self
            .entries
            .lock()
            .map_err(|_| ArtifactPinAccountingError::Poisoned)?;
        let mut metrics = ArtifactPinMetricsV1::default();
        for entry in entries.values() {
            if entry.active_pins > 0 {
                metrics.artifacts_with_active_pins = metrics
                    .artifacts_with_active_pins
                    .checked_add(1)
                    .ok_or(ArtifactPinAccountingError::Capacity)?;
            }
            metrics.active_pins = metrics
                .active_pins
                .checked_add(entry.active_pins)
                .ok_or(ArtifactPinAccountingError::Capacity)?;
            metrics.pinned_bytes = metrics
                .pinned_bytes
                .checked_add(entry.pinned_bytes)
                .ok_or(ArtifactPinAccountingError::Capacity)?;
            metrics.pending_erasure_bytes = metrics
                .pending_erasure_bytes
                .checked_add(entry.pending_erasure_bytes)
                .ok_or(ArtifactPinAccountingError::Capacity)?;
        }
        Ok(metrics)
    }

    pub fn status(
        &self,
        artifact_id: &StableId,
    ) -> Result<ArtifactPinStatusV1, ArtifactPinAccountingError> {
        let entries = self
            .entries
            .lock()
            .map_err(|_| ArtifactPinAccountingError::Poisoned)?;
        let entry = entries.get(artifact_id).copied().unwrap_or_default();
        Ok(ArtifactPinStatusV1 {
            active_pins: entry.active_pins,
            pinned_bytes: entry.pinned_bytes,
            pending_erasure_bytes: entry.pending_erasure_bytes,
        })
    }

    pub fn mark_artifact_pending_erasure(
        &self,
        artifact_id: &StableId,
    ) -> Result<(), ArtifactPinAccountingError> {
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| ArtifactPinAccountingError::Poisoned)?;
        if let Some(entry) = entries.get_mut(artifact_id) {
            entry.pending_erasure_bytes = entry.pinned_bytes;
        }
        Ok(())
    }
}

#[derive(Debug)]
pub struct ArtifactPinGuardV1 {
    accounting: Arc<ArtifactPinAccountingV1>,
    artifact_id: StableId,
    bytes: u64,
    pending_erasure: bool,
}

impl ArtifactPinGuardV1 {
    pub fn mark_pending_erasure(&mut self) -> Result<(), ArtifactPinAccountingError> {
        if self.pending_erasure {
            return Ok(());
        }
        let mut entries = self
            .accounting
            .entries
            .lock()
            .map_err(|_| ArtifactPinAccountingError::Poisoned)?;
        let entry = entries
            .get_mut(&self.artifact_id)
            .ok_or(ArtifactPinAccountingError::UnknownPin)?;
        entry.pending_erasure_bytes = entry
            .pending_erasure_bytes
            .checked_add(self.bytes)
            .ok_or(ArtifactPinAccountingError::Capacity)?;
        self.pending_erasure = true;
        Ok(())
    }
}

impl Drop for ArtifactPinGuardV1 {
    fn drop(&mut self) {
        let mut entries = match self.accounting.entries.lock() {
            Ok(entries) => entries,
            Err(poisoned) => poisoned.into_inner(),
        };
        let mut remove = false;
        if let Some(entry) = entries.get_mut(&self.artifact_id) {
            entry.active_pins = entry.active_pins.saturating_sub(1);
            entry.pinned_bytes = entry.pinned_bytes.saturating_sub(self.bytes);
            if self.pending_erasure {
                entry.pending_erasure_bytes =
                    entry.pending_erasure_bytes.saturating_sub(self.bytes);
            }
            remove = entry.active_pins == 0
                && entry.pinned_bytes == 0
                && entry.pending_erasure_bytes == 0;
        }
        if remove {
            entries.remove(&self.artifact_id);
        }
    }
}

pub struct AccountedPinnedCandidateV1 {
    candidate: LoadedPinnedCandidate,
    guard: ArtifactPinGuardV1,
}

impl AccountedPinnedCandidateV1 {
    #[must_use]
    pub fn spec(&self) -> &PinnedCandidateSpec {
        self.candidate.spec()
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.candidate.bytes()
    }

    #[must_use]
    pub fn into_revalidating(self) -> AccountedRevalidatingCandidateV1 {
        let Self { candidate, guard } = self;
        AccountedRevalidatingCandidateV1 {
            candidate: RevalidatingCandidate::new(candidate),
            guard,
        }
    }
}

impl fmt::Debug for AccountedPinnedCandidateV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AccountedPinnedCandidateV1")
            .field("candidate", &self.candidate)
            .field("artifact_id", &self.guard.artifact_id)
            .field("bytes", &self.guard.bytes)
            .finish()
    }
}

pub struct AccountedRevalidatingCandidateV1 {
    candidate: RevalidatingCandidate,
    guard: ArtifactPinGuardV1,
}

impl AccountedRevalidatingCandidateV1 {
    pub fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, AccountedPinnedCandidateError> {
        match self.candidate.with_current(current, consume) {
            Ok(value) => Ok(value),
            Err(PinnedCandidateLoadError::Ineligible) => {
                self.guard.mark_pending_erasure()?;
                Err(AccountedPinnedCandidateError::Load(
                    PinnedCandidateLoadError::Ineligible,
                ))
            }
            Err(error) => Err(AccountedPinnedCandidateError::Load(error)),
        }
    }

    pub fn mark_pending_erasure(&mut self) -> Result<(), ArtifactPinAccountingError> {
        self.guard.mark_pending_erasure()
    }
}

pub fn load_accounted_pinned_candidate_v1(
    snapshot_file: File,
    payload_file: File,
    expected: PinnedCandidateSpec,
    accounting: Arc<ArtifactPinAccountingV1>,
) -> Result<AccountedPinnedCandidateV1, AccountedPinnedCandidateError> {
    let candidate = load_pinned_candidate(snapshot_file, payload_file, expected)?;
    let bytes = u64::try_from(candidate.bytes().len())
        .map_err(|_| ArtifactPinAccountingError::Capacity)?;
    let guard = accounting.pin(candidate.spec().manifest.artifact_id.clone(), bytes)?;
    Ok(AccountedPinnedCandidateV1 { candidate, guard })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactPinAccountingError {
    InvalidBytes,
    Capacity,
    Poisoned,
    UnknownPin,
}

impl fmt::Display for ArtifactPinAccountingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactPinAccountingError {}

#[derive(Debug)]
pub enum AccountedPinnedCandidateError {
    Load(PinnedCandidateLoadError),
    Accounting(ArtifactPinAccountingError),
}

impl fmt::Display for AccountedPinnedCandidateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AccountedPinnedCandidateError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Load(error) => Some(error),
            Self::Accounting(error) => Some(error),
        }
    }
}

impl From<PinnedCandidateLoadError> for AccountedPinnedCandidateError {
    fn from(value: PinnedCandidateLoadError) -> Self {
        Self::Load(value)
    }
}

impl From<ArtifactPinAccountingError> for AccountedPinnedCandidateError {
    fn from(value: ArtifactPinAccountingError) -> Self {
        Self::Accounting(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        match StableId::new(value.to_owned()) {
            Ok(value) => value,
            Err(error) => panic!("invalid test id: {error}"),
        }
    }

    #[test]
    fn pins_and_pending_erasure_are_released_by_drop() {
        let accounting = Arc::new(ArtifactPinAccountingV1::new());
        let mut guard = match accounting.pin(id("artifact"), 128) {
            Ok(guard) => guard,
            Err(error) => panic!("pin failed: {error}"),
        };
        assert_eq!(
            accounting.metrics().map(|metrics| metrics.pinned_bytes),
            Ok(128)
        );
        if let Err(error) = guard.mark_pending_erasure() {
            panic!("mark pending erasure failed: {error}");
        }
        assert_eq!(
            accounting
                .metrics()
                .map(|metrics| metrics.pending_erasure_bytes),
            Ok(128)
        );
        drop(guard);
        assert_eq!(accounting.metrics(), Ok(ArtifactPinMetricsV1::default()));
    }
}
