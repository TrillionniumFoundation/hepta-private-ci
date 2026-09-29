//! Exact-ID materialization through the existing owner page implementation.
//! This is a read-only value, not another store, authorization cache or lease.

use std::collections::BTreeSet;

use codex_hepta_cognitive_read::MAX_READ_IDS_V1;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use super::CognitiveOwnerFrontiers;
use super::DurableCognitiveSnapshot;
use super::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
use super::corrupt;
use super::push_stable_id;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

/// One bounded ID set, complete selected ancestry and the same transaction's
/// global owner frontier/head-eligibility witness. It owns no SQL handle.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCognitiveSelectionSnapshot {
    owner: DurableCognitiveSnapshot,
    record_ids: Vec<StableId>,
    owner_state_digest: Digest32,
}

impl DurableCognitiveSelectionSnapshot {
    pub fn snapshot(&self) -> &CognitiveSnapshot {
        self.owner.snapshot()
    }

    /// Legacy structural consumers may borrow these records, but must not
    /// substitute the inner cut digest for this selection's complete binding.
    pub fn owner_snapshot(&self) -> &DurableCognitiveSnapshot {
        &self.owner
    }

    pub fn scope_id(&self) -> &StableId {
        self.owner.scope_id()
    }

    pub fn frontiers(&self) -> &CognitiveOwnerFrontiers {
        self.owner.frontiers()
    }

    pub fn record_ids(&self) -> &[StableId] {
        &self.record_ids
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    pub fn cut_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.sqlite.lane-c.exact-cut.v1".to_vec();
        bytes.extend_from_slice(self.owner.cut_digest().as_array());
        bytes.extend_from_slice(self.owner_state_digest.as_array());
        bytes.extend_from_slice(&(self.record_ids.len() as u64).to_be_bytes());
        for id in &self.record_ids {
            push_stable_id(&mut bytes, id);
        }
        Digest32::of_bytes(&bytes)
    }

    /// Project a subset within this immutable owner cut, never admitting an
    /// ID not present in the original request (including explicit missing IDs).
    /// Authorization/currentness are still rechecked by the physical owner.
    pub fn select_ids(&self, record_ids: &[StableId]) -> Result<Self, CognitiveStoreError> {
        let ids = checked_ids(record_ids)?;
        if ids.iter().any(|id| self.record_ids.binary_search(id).is_err()) {
            return Err(CognitiveStoreError::Invalid(
                "selected cognitive IDs are outside the acquired owner request".to_string(),
            ));
        }
        let records = self.owner.snapshot.records.iter()
            .filter(|record| ids.binary_search(&record.record_id).is_ok())
            .cloned()
            .collect();
        let snapshot = build_snapshot(generation(&self.owner.frontiers)?, records).map_err(corrupt)?;
        Ok(Self {
            owner: DurableCognitiveSnapshot {
                scope_id: self.owner.scope_id.clone(),
                frontiers: self.owner.frontiers.clone(),
                snapshot,
                observed_at_unix_seconds: self.owner.observed_at_unix_seconds,
            },
            record_ids: ids,
            owner_state_digest: self.owner_state_digest,
        })
    }
}

impl CognitiveStore {
    /// Read the requested heads through the same bounded page/ancestry code.
    /// Whole-scope historical row counts are witnesses, not materialization
    /// ceilings. A complete selected ancestry/citation overflow still errors.
    pub async fn lane_c_snapshot_ids(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        record_ids: &[StableId],
    ) -> Result<DurableCognitiveSelectionSnapshot, CognitiveStoreError> {
        self.authorize(access, scope)?;
        let ids = checked_ids(record_ids)?;
        let page = self.lane_c_snapshot_page_inner(
            access,
            scope,
            now_unix_seconds,
            MAX_LANE_C_SNAPSHOT_PAGE_HEADS as u32,
            /*after*/ None,
            Some(&ids),
        ).await?;
        if !page.complete || page.after.is_some() || page.next.is_some() {
            return Err(corrupt("exact-ID owner materialization was incomplete"));
        }
        let snapshot = build_snapshot(generation(&page.frontiers)?, page.records).map_err(corrupt)?;
        Ok(DurableCognitiveSelectionSnapshot {
            owner: DurableCognitiveSnapshot {
                scope_id: page.scope_id,
                frontiers: page.frontiers,
                snapshot,
                observed_at_unix_seconds: page.observed_at_unix_seconds,
            },
            record_ids: ids,
            owner_state_digest: page.owner_state_digest,
        })
    }

    pub async fn revalidate_lane_c_selection(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: &DurableCognitiveSelectionSnapshot,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSelectionSnapshot, CognitiveStoreError> {
        self.authorize(access, scope)?;
        if now_unix_seconds < expected.owner.observed_at_unix_seconds {
            return Err(CognitiveStoreError::Invalid("snapshot clock regressed".to_string()));
        }
        let current = self.lane_c_snapshot_ids(access, scope, now_unix_seconds, &expected.record_ids).await?;
        if current.cut_digest() != expected.cut_digest() || current.snapshot() != expected.snapshot() {
            return Err(CognitiveStoreError::Conflict(
                "selected cognitive owner cut changed or rolled back".to_string(),
            ));
        }
        Ok(current)
    }
}

fn checked_ids(record_ids: &[StableId]) -> Result<Vec<StableId>, CognitiveStoreError> {
    if record_ids.len() > MAX_READ_IDS_V1 {
        return Err(CognitiveStoreError::Invalid(format!(
            "exact owner read accepts at most {MAX_READ_IDS_V1} IDs"
        )));
    }
    let unique = record_ids.iter().cloned().collect::<BTreeSet<_>>();
    if unique.len() != record_ids.len() {
        return Err(CognitiveStoreError::Invalid("duplicate exact owner read ID".to_string()));
    }
    Ok(unique.into_iter().collect())
}

fn generation(frontiers: &CognitiveOwnerFrontiers) -> Result<Generation, CognitiveStoreError> {
    Generation::new(frontiers.memory.checked_add(1).ok_or_else(|| corrupt("memory frontier overflow"))?)
        .map_err(corrupt)
}

/// Supplement the existing ID/revision head digest with current eligibility.
/// The legacy page digest stays unchanged. Exact cuts additionally bind this
/// witness, so even an unselected head's expiry or metadata drift invalidates it.
pub(super) fn advance_head_state(
    prior: Digest32,
    row: &SqliteRow,
    now_unix_seconds: i64,
) -> Result<Digest32, CognitiveStoreError> {
    let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
    let revision: i64 = row.try_get("revision").map_err(unavailable)?;
    let digest: String = row.try_get("content_sha256").map_err(unavailable)?;
    let digest: Digest32 = digest.parse().map_err(corrupt)?;
    let verification: String = row.try_get("verification").map_err(unavailable)?;
    let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
    let valid_from: i64 = row.try_get("valid_from_unix_seconds").map_err(unavailable)?;
    let valid_to: Option<i64> = row.try_get("valid_to_unix_seconds").map_err(unavailable)?;
    let eligible = match lifecycle.as_str() {
        "tombstoned" => true,
        "active" => verification == "verified"
            && valid_from <= now_unix_seconds
            && valid_to.is_none_or(|until| now_unix_seconds < until),
        _ => return Err(corrupt("invalid cognitive head lifecycle")),
    };
    if revision <= 0 || !matches!(verification.as_str(), "verified" | "provisional") {
        return Err(corrupt("invalid cognitive head metadata"));
    }
    let mut bytes = b"hepta.sqlite.lane-c.head-state.v1".to_vec();
    bytes.extend_from_slice(prior.as_array());
    push_stable_id(&mut bytes, &StableId::new(memory_id).map_err(corrupt)?);
    bytes.extend_from_slice(&revision.to_be_bytes());
    bytes.extend_from_slice(digest.as_array());
    for value in [&verification, &lifecycle] {
        bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }
    bytes.extend_from_slice(&valid_from.to_be_bytes());
    match valid_to {
        Some(until) => {
            bytes.push(1);
            bytes.extend_from_slice(&until.to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.push(u8::from(eligible));
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
#[path = "lane_c_selected_snapshot_tests.rs"]
mod tests;
