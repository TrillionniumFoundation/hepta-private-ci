use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceRecoveryFrontierV2;

pub const EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME: &str = "identity.json";
pub const EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY: &str = "frontiers";
pub(crate) const EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION: u32 = 1;
pub(crate) const EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION: u32 = 1;
pub(crate) const EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS: &str = "external_monotonic_cas";
pub(crate) const EVIDENCE_FRONTIER_MAX_IDENTITY_BYTES: u64 = 16 * 1024;
pub(crate) const EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
pub(crate) const EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES: usize = 256 * 1024;
pub(crate) const EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS: usize = 1_000_000;
const EVIDENCE_FRONTIER_MAX_HISTORY_RESULTS: u64 = 4096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceFrontierBackendIdentityV1 {
    pub schema_version: u32,
    pub backend_id: String,
    pub authority_id: String,
    pub authority_generation: u64,
    pub storage_class: String,
}

impl EvidenceFrontierBackendIdentityV1 {
    pub fn validate(&self) -> Result<(), EvidenceFrontierBackendError> {
        if self.schema_version != EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION
            || self.authority_generation == 0
            || self.storage_class != EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS
        {
            return Err(EvidenceFrontierBackendError::Invalid(
                "unsupported external frontier backend identity".to_string(),
            ));
        }
        StableId::new(self.backend_id.clone()).map_err(|error| {
            EvidenceFrontierBackendError::Invalid(format!("invalid backend id: {error}"))
        })?;
        StableId::new(self.authority_id.clone()).map_err(|error| {
            EvidenceFrontierBackendError::Invalid(format!("invalid backend authority id: {error}"))
        })?;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvidenceFrontierHistoryRangeV1 {
    pub first_generation: u64,
    pub last_generation: u64,
}

impl EvidenceFrontierHistoryRangeV1 {
    pub fn new(
        first_generation: u64,
        last_generation: u64,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        let count = last_generation
            .checked_sub(first_generation)
            .and_then(|delta| delta.checked_add(1))
            .ok_or_else(|| {
                EvidenceFrontierBackendError::Invalid(
                    "frontier history range is inverted".to_string(),
                )
            })?;
        if first_generation == 0 || count > EVIDENCE_FRONTIER_MAX_HISTORY_RESULTS {
            return Err(EvidenceFrontierBackendError::Invalid(
                "frontier history range is outside the bounded policy".to_string(),
            ));
        }
        Ok(Self {
            first_generation,
            last_generation,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceFrontierDurableAckV1 {
    pub backend_id: String,
    pub backend_identity_sha256: Sha256Digest,
    pub store_id: String,
    pub frontier_generation: u64,
    pub frontier_sha256: Sha256Digest,
    pub audit_sequence: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum EvidenceFrontierBackendError {
    #[error("invalid evidence frontier backend input: {0}")]
    Invalid(String),
    #[error("evidence frontier CAS conflict: expected {expected:?}, actual {actual:?}")]
    Conflict {
        expected: Option<u64>,
        actual: Option<u64>,
    },
    #[error("evidence frontier backend is unavailable: {0}")]
    Unavailable(String),
    #[error("evidence frontier backend is corrupt: {0}")]
    Corrupt(String),
    #[error("evidence frontier backend write is indeterminate: {0}")]
    Indeterminate(String),
    #[error("evidence frontier backend is unsupported on this platform")]
    Unsupported,
}

/// Authoritative monotonic storage for signed evidence recovery frontiers.
///
/// Implementations must linearize `compare_and_swap` across every process and
/// machine participating in the same store. A successful CAS is a durable
/// acknowledgement: the authoritative record and its audit link have reached
/// the backend's stable-storage boundary. Once a write begins, an uncertain
/// outcome must be reported as `Indeterminate`, never as a definite rejection.
pub trait EvidenceFrontierBackend {
    fn get_latest(
        &mut self,
        store_id: &str,
    ) -> Result<Option<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError>;

    fn compare_and_swap(
        &mut self,
        store_id: &str,
        expected_generation: Option<u64>,
        new_frontier: &EvidenceRecoveryFrontierV2,
    ) -> Result<EvidenceFrontierDurableAckV1, EvidenceFrontierBackendError>;

    fn get_history(
        &mut self,
        store_id: &str,
        range: EvidenceFrontierHistoryRangeV1,
    ) -> Result<Vec<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError>;

    fn verify_backend_identity(
        &mut self,
    ) -> Result<EvidenceFrontierBackendIdentityV1, EvidenceFrontierBackendError>;
}

#[cfg(test)]
#[path = "frontier_backend_tests.rs"]
mod tests;
