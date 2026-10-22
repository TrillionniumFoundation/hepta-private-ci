//! Derived checkpoint custody under the existing production writer lease.
//! This module is private to that writer so no raw mutable owner escapes.

use std::sync::Arc;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::DurableCognitiveSnapshot;
use crate::LoadedMemoryCellCheckpointV1;
use crate::LocalLease;
use crate::MemoryCellCheckpointDraftV1;
use crate::MemoryCellCheckpointReadPinsV1;
use crate::MemoryCellCheckpointReceiptV1;
use crate::MemoryCellStateErrorV1;
use crate::cognitive_store::unavailable;
use crate::memory_cell_state_types::MAX_CHECKPOINTS;
use crate::memory_cell_state_types::MAX_STORED_BYTES;
use crate::memory_cell_state_types::checkpoint_digest;

/// Privately minted byte-custody capability. Every operation rechecks the live
/// external authority and the existing SQLite writer fence. It cannot publish
/// facts, authorize a model, or establish the semantics of an opaque codec.
#[derive(Clone)]
pub struct ProductionMemoryCellStateCapability {
    writer: Arc<ProductionDurableWriter>,
}

impl ProductionDurableWriter {
    pub fn memory_cell_state_capability(
        self: &Arc<Self>,
    ) -> Result<ProductionMemoryCellStateCapability, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        Ok(ProductionMemoryCellStateCapability {
            writer: Arc::clone(self),
        })
    }
}

impl ProductionMemoryCellStateCapability {
    fn verify_live(&self) -> Result<(), ProductionWriterError> {
        self.writer
            .authority
            .validate_for_agent(self.writer.owner_agent_id())?;
        self.writer
            .live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&self.writer.authority, self.writer.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }

    async fn current_cut(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: ContractDigestV1,
        now_unix_seconds: i64,
    ) -> Result<(DurableCognitiveSnapshot, LocalLease), MemoryCellStateErrorV1> {
        self.writer.store.authorize(access, scope)?;
        self.verify_live()?;
        let lease = self
            .writer
            .lease
            .verify_current_in_transaction(transaction)
            .await
            .map_err(ProductionWriterError::from)?;
        let cut = self
            .writer
            .store
            .lane_c_snapshot_tx(transaction, access, scope, now_unix_seconds)
            .await?;
        if cut.cut_digest() != expected.digest() {
            return Err(MemoryCellStateErrorV1::Conflict(
                "owner source/forget cut changed",
            ));
        }
        Ok((cut, lease))
    }

    /// Append the actual bounded bytes and advance exactly one cell head in the
    /// same transaction that verifies the source/forget cut and writer lease.
    pub async fn commit(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        draft: &MemoryCellCheckpointDraftV1,
        now_unix_seconds: i64,
    ) -> Result<MemoryCellCheckpointReceiptV1, MemoryCellStateErrorV1> {
        let header = draft.encode_header()?;
        let digest = checkpoint_digest(&header)?;
        let mut transaction = self
            .writer
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let (cut, lease) = self
            .current_cut(
                &mut transaction,
                access,
                scope,
                draft.header.owner_cut_digest,
                now_unix_seconds,
            )
            .await?;
        let scope_key = scope.projection_key();
        let cell = draft.header.manifest.cell_id.as_str();
        let previous = load_head(&mut transaction, &scope_key, cell).await?;
        if let Some(previous) = &previous
            && previous.header().logical_sequence == draft.header.logical_sequence
        {
            if previous.draft != *draft {
                return Err(MemoryCellStateErrorV1::Conflict(
                    "same sequence has different bytes or identity",
                ));
            }
            self.verify_live()?;
            transaction.commit().await.map_err(unavailable)?;
            let mut current = previous.receipt().clone();
            current.replayed = true;
            return Ok(current);
        }
        let expected_sequence = previous
            .as_ref()
            .map_or(1, |head| head.header().logical_sequence + 1);
        let expected_predecessor = previous
            .as_ref()
            .map(|head| head.receipt().checkpoint_digest);
        if draft.header.logical_sequence != expected_sequence
            || draft.header.predecessor_digest != expected_predecessor
        {
            return Err(MemoryCellStateErrorV1::Conflict(
                "checkpoint predecessor or sequence",
            ));
        }
        let (count, stored_bytes): (i64, i64) = sqlx::query_as(
            "SELECT count(*), COALESCE(sum(length(CAST(header_json AS BLOB)) + length(state_bytes) + length(recall_bytes)), 0)
             FROM (SELECT header_json, state_bytes, recall_bytes FROM cognitive_memory_cell_checkpoints LIMIT 1025)",
        ).fetch_one(&mut *transaction).await.map_err(unavailable)?;
        let added_bytes =
            (header.len() + draft.state_bytes.len() + draft.recall_bytes.len()) as i64;
        if count >= MAX_CHECKPOINTS || stored_bytes > MAX_STORED_BYTES - added_bytes {
            return Err(MemoryCellStateErrorV1::Invalid(
                "owner checkpoint capacity exceeded".into(),
            ));
        }
        sqlx::query(
            "INSERT INTO cognitive_memory_cell_checkpoints
             (scope_key, cell_id, logical_sequence, checkpoint_sha256, predecessor_sha256,
              owner_cut_sha256, source_frontier, tombstone_frontier, header_json, state_bytes,
              recall_bytes, lease_id, lease_sha256, authority_grant_sha256)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&scope_key)
        .bind(cell)
        .bind(draft.header.logical_sequence as i64)
        .bind(digest.to_string())
        .bind(expected_predecessor.map(|value| value.to_string()))
        .bind(draft.header.owner_cut_digest.to_string())
        .bind(cut.frontiers().source as i64)
        .bind(cut.frontiers().tombstone as i64)
        .bind(&header)
        .bind(&draft.state_bytes)
        .bind(&draft.recall_bytes)
        .bind(self.writer.lease_id())
        .bind(lease.lease_sha256.as_str())
        .bind(self.writer.authority.grant_digest.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let changed = if let Some(previous) = &previous {
            sqlx::query("UPDATE cognitive_memory_cell_heads SET logical_sequence = ? WHERE scope_key = ? AND cell_id = ? AND logical_sequence = ?")
                .bind(draft.header.logical_sequence as i64).bind(&scope_key).bind(cell)
                .bind(previous.header().logical_sequence as i64)
                .execute(&mut *transaction).await.map_err(unavailable)?
        } else {
            sqlx::query("INSERT INTO cognitive_memory_cell_heads (scope_key, cell_id, logical_sequence) VALUES (?, ?, 1)")
                .bind(&scope_key).bind(cell).execute(&mut *transaction).await.map_err(unavailable)?
        };
        if changed.rows_affected() != 1 {
            return Err(MemoryCellStateErrorV1::Conflict(
                "checkpoint head compare-and-swap",
            ));
        }
        self.verify_live()?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(MemoryCellCheckpointReceiptV1 {
            cell_id: draft.header.manifest.cell_id.clone(),
            logical_sequence: draft.header.logical_sequence,
            checkpoint_digest: digest,
            owner_cut_digest: draft.header.owner_cut_digest,
            source_frontier: cut.frontiers().source,
            tombstone_frontier: cut.frontiers().tombstone,
            state_content_digest: draft.header.state_content_digest,
            recall_content_digest: draft.header.recall_content_digest,
            writer_lease_digest: lease.lease_sha256,
            authority_grant_digest: self.writer.authority.grant_digest.clone(),
            replayed: false,
        })
    }

    /// Read only a caller-pinned current checkpoint. A later source or forget
    /// change invalidates these bytes; a caller must revalidate before use.
    pub async fn read_current(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        pins: &MemoryCellCheckpointReadPinsV1,
        now_unix_seconds: i64,
    ) -> Result<LoadedMemoryCellCheckpointV1, MemoryCellStateErrorV1> {
        pins.manifest
            .validate()
            .map_err(|error| MemoryCellStateErrorV1::Invalid(error.to_string()))?;
        let mut transaction = self.writer.store.pool.begin().await.map_err(unavailable)?;
        let (cut, _) = self
            .current_cut(
                &mut transaction,
                access,
                scope,
                pins.owner_cut_digest,
                now_unix_seconds,
            )
            .await?;
        let loaded = load_head(
            &mut transaction,
            &scope.projection_key(),
            pins.manifest.cell_id.as_str(),
        )
        .await?
        .ok_or(MemoryCellStateErrorV1::Conflict("checkpoint head absent"))?;
        if loaded.header().manifest != pins.manifest
            || loaded.receipt().checkpoint_digest != pins.checkpoint_digest
            || loaded.header().owner_cut_digest != pins.owner_cut_digest
            || loaded.receipt().source_frontier != cut.frontiers().source
            || loaded.receipt().tombstone_frontier != cut.frontiers().tombstone
        {
            return Err(MemoryCellStateErrorV1::Conflict("current checkpoint pins"));
        }
        self.verify_live()?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(loaded)
    }
}

async fn load_head(
    transaction: &mut Transaction<'_, Sqlite>,
    scope_key: &str,
    cell: &str,
) -> Result<Option<LoadedMemoryCellCheckpointV1>, MemoryCellStateErrorV1> {
    let head: Option<i64> = sqlx::query_scalar("SELECT logical_sequence FROM cognitive_memory_cell_heads WHERE scope_key = ? AND cell_id = ?")
        .bind(scope_key).bind(cell).fetch_optional(&mut **transaction).await.map_err(unavailable)?;
    let history: Vec<(i64, String, Option<String>)> = sqlx::query_as(
        "SELECT logical_sequence, checkpoint_sha256, predecessor_sha256 FROM cognitive_memory_cell_checkpoints
         WHERE scope_key = ? AND cell_id = ? ORDER BY logical_sequence LIMIT 1025",
    ).bind(scope_key).bind(cell).fetch_all(&mut **transaction).await.map_err(unavailable)?;
    if history.is_empty() && head.is_none() {
        return Ok(None);
    }
    if history.len() > MAX_CHECKPOINTS as usize || head != Some(history.len() as i64) {
        return Err(MemoryCellStateErrorV1::Corrupt(
            "checkpoint head/history mismatch",
        ));
    }
    let mut prior = None;
    for (index, (sequence, digest, predecessor)) in history.iter().enumerate() {
        if *sequence != index as i64 + 1 || *predecessor != prior {
            return Err(MemoryCellStateErrorV1::Corrupt("checkpoint ancestry"));
        }
        ContractDigestV1::parse(digest)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("checkpoint digest"))?;
        prior = Some(digest.clone());
    }
    let (sequence, digest, predecessor) = history
        .last()
        .ok_or(MemoryCellStateErrorV1::Corrupt("missing checkpoint"))?;
    // The SQL byte limits apply before any JSON/BLOB is returned to Rust, even
    // if a damaged database was written while constraint enforcement was off.
    let row = sqlx::query(
        "SELECT header_json, state_bytes, recall_bytes, owner_cut_sha256, source_frontier,
                tombstone_frontier, lease_sha256, authority_grant_sha256
         FROM cognitive_memory_cell_checkpoints WHERE scope_key = ? AND cell_id = ? AND logical_sequence = ?
           AND length(CAST(header_json AS BLOB)) BETWEEN 1 AND 16384
           AND length(state_bytes) BETWEEN 1 AND 1048576 AND length(recall_bytes) BETWEEN 1 AND 524288",
    ).bind(scope_key).bind(cell).bind(sequence).fetch_optional(&mut **transaction).await.map_err(unavailable)?
        .ok_or(MemoryCellStateErrorV1::Corrupt("checkpoint body missing or oversized"))?;
    let header: String = row.try_get("header_json").map_err(unavailable)?;
    let draft = MemoryCellCheckpointDraftV1 {
        header: serde_json::from_str(&header)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("checkpoint header"))?,
        state_bytes: row.try_get("state_bytes").map_err(unavailable)?,
        recall_bytes: row.try_get("recall_bytes").map_err(unavailable)?,
    };
    let owner_cut: String = row.try_get("owner_cut_sha256").map_err(unavailable)?;
    let canonical = draft
        .encode_header()
        .map_err(|_| MemoryCellStateErrorV1::Corrupt("checkpoint content identity"))?;
    let actual_digest = checkpoint_digest(&canonical)?;
    if canonical != header
        || actual_digest.to_string() != *digest
        || draft.header.logical_sequence != *sequence as u64
        || draft.header.manifest.cell_id.as_str() != cell
        || draft.header.owner_cut_digest.to_string() != owner_cut
        || draft
            .header
            .predecessor_digest
            .map(|value| value.to_string())
            != *predecessor
    {
        return Err(MemoryCellStateErrorV1::Corrupt("checkpoint row identity"));
    }
    let source: i64 = row.try_get("source_frontier").map_err(unavailable)?;
    let tombstone: i64 = row.try_get("tombstone_frontier").map_err(unavailable)?;
    let lease: String = row.try_get("lease_sha256").map_err(unavailable)?;
    let grant: String = row.try_get("authority_grant_sha256").map_err(unavailable)?;
    let receipt = MemoryCellCheckpointReceiptV1 {
        cell_id: draft.header.manifest.cell_id.clone(),
        logical_sequence: *sequence as u64,
        checkpoint_digest: actual_digest,
        owner_cut_digest: draft.header.owner_cut_digest,
        source_frontier: u64::try_from(source)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("source frontier"))?,
        tombstone_frontier: u64::try_from(tombstone)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("forget frontier"))?,
        state_content_digest: draft.header.state_content_digest,
        recall_content_digest: draft.header.recall_content_digest,
        writer_lease_digest: Sha256Digest::parse(lease)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("writer lease digest"))?,
        authority_grant_digest: Sha256Digest::parse(grant)
            .map_err(|_| MemoryCellStateErrorV1::Corrupt("authority grant digest"))?,
        replayed: false,
    };
    Ok(Some(LoadedMemoryCellCheckpointV1 { draft, receipt }))
}

#[cfg(test)]
#[path = "memory_cell_state_store_tests.rs"]
mod tests;
