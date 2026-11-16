//! A read nonce is spent durably before model entry, including on failure.

use codex_hepta_types::Digest32;
use serde::Serialize;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::MemoryCellQueryV1;
use super::MemoryCellSourceBindingV1;
use super::MemoryCellSourceClaimV1;
use super::MemoryCellSourceError;
use super::ProductionDurableWriter;
use super::ProductionWriterError;
use super::now_unix_ms;
use crate::CognitiveAccess;
use crate::LocalAdmission;
use crate::cognitive_store::unavailable;

/// Only the durable source owner can construct this admission. It contains no
/// model authority: the native host separately validates actual execution.
#[derive(Debug)]
pub struct MemoryCellAdmissionV1 {
    access: CognitiveAccess,
    query: MemoryCellQueryV1,
    claim: MemoryCellSourceClaimV1,
    binding: MemoryCellSourceBindingV1,
    lease_id: String,
    occurrence: String,
}

impl MemoryCellAdmissionV1 {
    pub fn binding(&self) -> &MemoryCellSourceBindingV1 {
        &self.binding
    }
    pub fn query(&self) -> &MemoryCellQueryV1 {
        &self.query
    }
}

/// Owner commit binds a checked source cut to a host-supplied execution digest;
/// it is not, by itself, proof that a model ran.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryCellUseReceiptV1 {
    pub binding: MemoryCellSourceBindingV1,
    #[serde(serialize_with = "super::memory_cell_types::serialize_digest")]
    pub execution_digest: Digest32,
    pub event_id: String,
}

impl ProductionDurableWriter {
    /// Recheck a source without spending a nonce, including when delivering a
    /// completed asynchronous read. This never admits a model callback.
    pub async fn authorize_memory_cell(
        &self,
        access: &CognitiveAccess,
        query: &MemoryCellQueryV1,
        claim: &MemoryCellSourceClaimV1,
    ) -> Result<MemoryCellSourceBindingV1, MemoryCellSourceError> {
        self.verify_current_authority().await?;
        let mut tx = self.store.pool.begin().await.map_err(unavailable)?;
        let binding = self
            .memory_cell_source_tx(&mut tx, access, query, claim, now_unix_ms()?)
            .await?;
        tx.commit().await.map_err(unavailable)?;
        self.verify_current_authority().await?;
        query.validate_at(now_unix_ms()?)?;
        Ok(binding)
    }

    pub async fn admit_memory_cell(
        &self,
        access: &CognitiveAccess,
        query: &MemoryCellQueryV1,
        claim: &MemoryCellSourceClaimV1,
    ) -> Result<MemoryCellAdmissionV1, MemoryCellSourceError> {
        self.verify_current_authority().await?;
        let mut tx = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let binding = self
            .memory_cell_source_tx(&mut tx, access, query, claim, now_unix_ms()?)
            .await?;
        let occurrence = format!("memory-cell-query:{}", query.request_id);
        // Cross-lease lookup: reopening a writer must not reset replay protection.
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE owner_agent_id = ? AND occurrence_key = ?")
            .bind(self.owner_agent_id().as_str()).bind(&occurrence)
            .fetch_one(&mut *tx).await.map_err(unavailable)?;
        if count != 0 {
            return Err(MemoryCellSourceError::Replay);
        }
        let payload = serde_json::to_string(&binding)
            .map_err(|_| MemoryCellSourceError::Invalid("admission encoding"))?;
        let admitted = self
            .lease
            .admit_in_transaction(
                &mut tx,
                occurrence.clone(),
                "memory-cell.read.v1".to_string(),
                payload,
            )
            .await
            .map_err(ProductionWriterError::from)?;
        if !matches!(admitted, LocalAdmission::Queued(_)) {
            return Err(MemoryCellSourceError::Replay);
        }
        self.verify_current_authority().await?;
        query.validate_at(now_unix_ms()?)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(MemoryCellAdmissionV1 {
            access: access.clone(),
            query: query.clone(),
            claim: claim.clone(),
            binding,
            lease_id: self.lease_id().to_string(),
            occurrence,
        })
    }

    /// Reacquire the owner view immediately before and after model entry.
    pub async fn revalidate_memory_cell(
        &self,
        admission: &MemoryCellAdmissionV1,
    ) -> Result<(), MemoryCellSourceError> {
        self.verify_current_authority().await?;
        let mut tx = self.store.pool.begin().await.map_err(unavailable)?;
        self.memory_cell_pending_tx(&mut tx, admission).await?;
        let current = self
            .memory_cell_source_tx(
                &mut tx,
                &admission.access,
                &admission.query,
                &admission.claim,
                now_unix_ms()?,
            )
            .await?;
        if current != admission.binding {
            return Err(MemoryCellSourceError::Invalid("source binding changed"));
        }
        tx.commit().await.map_err(unavailable)?;
        self.verify_current_authority().await?;
        admission.query.validate_at(now_unix_ms()?)?;
        Ok(())
    }

    /// Revalidate delivery after completion without reopening the spent nonce.
    /// This checks only the source cut and never authorizes another callback.
    pub async fn revalidate_memory_cell_source(
        &self,
        admission: &MemoryCellAdmissionV1,
    ) -> Result<(), MemoryCellSourceError> {
        let current = self
            .authorize_memory_cell(&admission.access, &admission.query, &admission.claim)
            .await?;
        if current != admission.binding {
            return Err(MemoryCellSourceError::Invalid("source binding changed"));
        }
        Ok(())
    }

    /// Atomically check the final source head and record one completion. A
    /// failed, timed-out or abandoned admission remains spent across restart.
    pub async fn finish_memory_cell(
        &self,
        admission: &MemoryCellAdmissionV1,
        execution_digest: Digest32,
    ) -> Result<MemoryCellUseReceiptV1, MemoryCellSourceError> {
        if execution_digest.is_zero() {
            return Err(MemoryCellSourceError::Invalid("empty execution receipt"));
        }
        self.verify_current_authority().await?;
        let mut tx = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        self.memory_cell_pending_tx(&mut tx, admission).await?;
        let current = self
            .memory_cell_source_tx(
                &mut tx,
                &admission.access,
                &admission.query,
                &admission.claim,
                now_unix_ms()?,
            )
            .await?;
        if current != admission.binding {
            return Err(MemoryCellSourceError::Invalid("source binding changed"));
        }
        let payload = serde_json::to_string(&(
            "memory-cell.execution.v1",
            &current,
            execution_digest.to_string(),
        ))
        .map_err(|_| MemoryCellSourceError::Invalid("execution encoding"))?;
        let result = self
            .lease
            .apply_in_transaction(&mut tx, admission.occurrence.clone(), payload)
            .await
            .map_err(ProductionWriterError::from)?;
        self.verify_current_authority().await?;
        admission.query.validate_at(now_unix_ms()?)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(MemoryCellUseReceiptV1 {
            binding: current,
            execution_digest,
            event_id: result.event_id,
        })
    }

    async fn memory_cell_pending_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        admission: &MemoryCellAdmissionV1,
    ) -> Result<(), MemoryCellSourceError> {
        if self.lease_id() != admission.lease_id {
            return Err(MemoryCellSourceError::Invalid("admission owner changed"));
        }
        let payload = serde_json::to_string(&admission.binding)
            .map_err(|_| MemoryCellSourceError::Invalid("admission encoding"))?;
        let rows: Vec<(String, String)> = sqlx::query_as("SELECT event_kind, payload_json FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? AND owner_agent_id = ?")
            .bind(&admission.lease_id).bind(&admission.occurrence).bind(self.owner_agent_id().as_str())
            .fetch_all(&mut **tx).await.map_err(unavailable)?;
        if rows != vec![("admitted".to_string(), payload)] {
            return Err(MemoryCellSourceError::Replay);
        }
        Ok(())
    }
}
