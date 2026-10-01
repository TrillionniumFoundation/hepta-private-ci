//! Bounded complete ancestry from the existing cognitive SQLite owner.
//!
//! Eligibility is evaluated at the current head: a verified, currently valid
//! live head or a terminal tombstone retains its entire immutable chain. An
//! expired, future or unverified live head excludes the whole chain. The
//! physical head manifest still binds excluded heads; this is not a claim that
//! every physical source is eligible for compaction.

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveOwnerFrontiers;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::cognitive_store::unavailable;
use crate::lane_c_snapshot::LaneCOwnerTransaction;

/// Whole-scope ancestry ceiling, shared with the existing Lane C snapshot.
pub const MAX_LANE_C_LINEAGE_REVISIONS: usize = 16_384;
/// Aggregate citation ceiling across all inspected revisions, not per head.
pub const MAX_LANE_C_LINEAGE_CITATIONS: usize = 65_536;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) enum LaneCProjection {
    Heads,
    EligibleLineage,
}

#[derive(Default)]
pub(crate) struct LaneCLineageCapture {
    pub records: Vec<MemoryRecord>,
    pub physical_head_digests: Vec<Digest32>,
}

// Both head/page reads and full lineage reads admit citation provenance at the
// owner boundary, including databases changed after initial open admission.
pub(crate) fn validate_citation_owner(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<(), CognitiveStoreError> {
    let authorized: Option<i64> = row.try_get("source_authorized").map_err(unavailable)?;
    if authorized != Some(1) {
        return Err(CognitiveStoreError::Corrupt(
            "Lane C citation source is missing or outside the authenticated scope".to_string(),
        ));
    }
    Ok(())
}

// MemoryRecord intentionally omits owner eligibility metadata. Bind it here
// even for excluded heads so revalidation detects any physical eligibility
// change without relying on a caller's assumption that SQL remained immutable.
pub(crate) fn physical_head_digest(
    record: &MemoryRecord,
    verification: &str,
    valid_from: i64,
    valid_to: Option<i64>,
) -> Result<Digest32, CognitiveStoreError> {
    let mut bytes = b"hepta.sqlite.lane-c.lineage-head.v1".to_vec();
    bytes.extend_from_slice(record.record_digest().as_array());
    bytes.push(match verification {
        "verified" => 1,
        "provisional" => 0,
        _ => {
            return Err(CognitiveStoreError::Corrupt(
                "invalid lineage verification".to_string(),
            ));
        }
    });
    bytes.extend_from_slice(&valid_from.to_be_bytes());
    match valid_to {
        Some(until) => {
            bytes.push(1);
            bytes.extend_from_slice(&until.to_be_bytes());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Owner-acquired metadata from one SQLite read transaction. Fields are private
/// so callers cannot substitute a source cut, omit ancestry or invent coverage.
/// This observation grants no writer, publication or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCognitiveLineageObservation {
    owner_cut: DurableCognitiveSnapshot,
    records: Vec<MemoryRecord>,
    source_head_count: u64,
    excluded_head_count: u64,
    source_head_manifest_digest: Digest32,
    source_binding_digest: Digest32,
    observed_at_unix_seconds: i64,
    observation_digest: Digest32,
}

impl DurableCognitiveLineageObservation {
    pub fn owner_cut(&self) -> &DurableCognitiveSnapshot {
        &self.owner_cut
    }

    pub fn scope_id(&self) -> &StableId {
        self.owner_cut.scope_id()
    }

    pub fn frontiers(&self) -> &CognitiveOwnerFrontiers {
        self.owner_cut.frontiers()
    }

    /// Complete original revisions for eligible current heads, ordered by
    /// record ID and revision. Earlier live revisions of a deleted head remain
    /// ancestry evidence; only `current_heads` describes selectable heads.
    pub fn records(&self) -> &[MemoryRecord] {
        &self.records
    }

    /// Move the bounded ancestry into a consumer without cloning it again.
    pub fn into_records(self) -> Vec<MemoryRecord> {
        self.records
    }

    pub fn current_heads(&self) -> &[MemoryRecord] {
        &self.owner_cut.snapshot().records
    }

    pub fn source_head_count(&self) -> u64 {
        self.source_head_count
    }

    pub fn excluded_head_count(&self) -> u64 {
        self.excluded_head_count
    }

    pub fn source_head_manifest_digest(&self) -> Digest32 {
        self.source_head_manifest_digest
    }

    /// Exact semantic cut including the physical head map and eligible ancestry.
    /// Its provenance is the owner method, not a self-authenticating digest.
    pub fn source_binding_digest(&self) -> Digest32 {
        self.source_binding_digest
    }

    pub fn observed_at_unix_seconds(&self) -> i64 {
        self.observed_at_unix_seconds
    }

    pub fn observation_digest(&self) -> Digest32 {
        self.observation_digest
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Assemble a receipt only from the shared validated owner projection.
    pub(crate) fn from_owner_projection(
        owner_cut: DurableCognitiveSnapshot,
        capture: LaneCLineageCapture,
        now_unix_seconds: i64,
    ) -> Result<Self, CognitiveStoreError> {
        let source_head_count = capture.physical_head_digests.len() as u64;
        let excluded_head_count = source_head_count
            .checked_sub(owner_cut.snapshot().records.len() as u64)
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt("lineage head coverage mismatch".to_string())
            })?;
        let mut manifest = b"hepta.sqlite.lane-c.lineage-heads.v1".to_vec();
        manifest.extend_from_slice(&source_head_count.to_be_bytes());
        for digest in capture.physical_head_digests {
            manifest.extend_from_slice(digest.as_array());
        }
        let source_head_manifest_digest = Digest32::of_bytes(&manifest);
        let mut binding = b"hepta.sqlite.lane-c.lineage-cut.v1".to_vec();
        binding.extend_from_slice(owner_cut.cut_digest().as_array());
        binding.extend_from_slice(source_head_manifest_digest.as_array());
        binding.extend_from_slice(&excluded_head_count.to_be_bytes());
        binding.extend_from_slice(&(capture.records.len() as u64).to_be_bytes());
        for record in &capture.records {
            binding.extend_from_slice(record.record_digest().as_array());
        }
        let source_binding_digest = Digest32::of_bytes(&binding);
        let mut receipt = b"hepta.sqlite.lane-c.lineage-observation.v1".to_vec();
        receipt.extend_from_slice(source_binding_digest.as_array());
        receipt.extend_from_slice(&now_unix_seconds.to_be_bytes());
        Ok(DurableCognitiveLineageObservation {
            owner_cut,
            records: capture.records,
            source_head_count,
            excluded_head_count,
            source_head_manifest_digest,
            source_binding_digest,
            observed_at_unix_seconds: now_unix_seconds,
            observation_digest: Digest32::of_bytes(&receipt),
        })
    }
}

impl CognitiveStore {
    /// Read bounded complete ancestry through the existing scope-authorized
    /// SQLite owner. Capacity failure rejects the cut instead of truncating it.
    /// The same transaction and validation power `lane_c_snapshot`; ordinary
    /// head readers do not allocate or copy the complete lineage projection.
    pub async fn lane_c_lineage(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveLineageObservation, CognitiveStoreError> {
        let mut transaction =
            LaneCOwnerTransaction::begin_read(self, access, scope, now_unix_seconds).await?;
        let observation = transaction.lineage(now_unix_seconds).await?;
        transaction.commit().await?;
        Ok(observation)
    }

    /// Reacquire the exact owner cut before use, including excluded-head
    /// changes and eligibility transitions caused only by elapsed time.
    pub async fn revalidate_lane_c_lineage(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: &DurableCognitiveLineageObservation,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveLineageObservation, CognitiveStoreError> {
        if now_unix_seconds < expected.observed_at_unix_seconds {
            return Err(CognitiveStoreError::Invalid(
                "lineage clock regressed".to_string(),
            ));
        }
        let mut transaction =
            LaneCOwnerTransaction::begin_read(self, access, scope, now_unix_seconds).await?;
        let current = transaction
            .revalidate_lineage(expected, now_unix_seconds)
            .await?;
        transaction.commit().await?;
        Ok(current)
    }
}

#[cfg(test)]
#[path = "lane_c_lineage_tests.rs"]
mod tests;
