//! Receipt preparation and source floors share the real consumer's FULL owner.
use super::ConsumerPortError;
use super::consumer_owner::CredentialConsumerOwner;
use super::consumer_owner::UncertainCommit;
use super::consumer_receipt_wire::SignedPreparedCredentialUse;
use super::consumer_wire::ConsumerIntent;
use super::consumer_wire::MAX_CONSUMER_OPERATIONS;
use crate::role_storage::unavailable;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_types::Digest32;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use std::sync::atomic::Ordering;

impl CredentialConsumerOwner {
    pub(super) async fn begin_receipt(
        &self,
    ) -> Result<(Transaction<'static, Sqlite>, UncertainCommit<'_>), ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        let guard = UncertainCommit {
            owner: self,
            armed: true,
        };
        let tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        Ok((tx, guard))
    }
    pub(super) async fn commit_receipt(
        &self,
        tx: Transaction<'static, Sqlite>,
        mut guard: UncertainCommit<'_>,
    ) -> Result<(), ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        tx.commit().await.map_err(unavailable)?;
        guard.armed = false;
        Ok(())
    }
    pub(super) async fn enroll_receipt_profile(
        &self,
        profile: [u8; 32],
    ) -> Result<(), ConsumerPortError> {
        let (mut tx, guard) = self.begin_receipt().await?;
        let retained: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT profile_sha256 FROM credential_receipt_meta WHERE singleton=1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        match retained {
            Some(retained) if retained == profile => {}
            Some(_) => return Err(ConsumerPortError::Conflict),
            None => {
                sqlx::query("INSERT INTO credential_receipt_meta VALUES(1,?,0,0)")
                    .bind(profile.as_slice())
                    .execute(&mut *tx)
                    .await
                    .map_err(unavailable)?;
            }
        }
        self.commit_receipt(tx, guard).await
    }
    pub(super) async fn retain_source_floor(
        &self,
        tx: &mut Transaction<'static, Sqlite>,
        time: &SignedTrustedTimeAttestation,
    ) -> Result<(), ConsumerPortError> {
        let row = sqlx::query(
            "SELECT source_wall_ms,source_revision FROM credential_receipt_meta WHERE singleton=1",
        )
        .fetch_one(&mut **tx)
        .await
        .map_err(unavailable)?;
        let wall: i64 = row.try_get("source_wall_ms").map_err(unavailable)?;
        let revision: i64 = row.try_get("source_revision").map_err(unavailable)?;
        let next_wall = i64::try_from(time.claims.wall_time_ms).map_err(unavailable)?;
        let next_revision = i64::try_from(time.claims.source_revision).map_err(unavailable)?;
        if next_wall < wall || next_revision <= revision {
            return Err(ConsumerPortError::Unavailable);
        }
        sqlx::query("UPDATE credential_receipt_meta SET source_wall_ms=?,source_revision=? WHERE singleton=1 AND source_wall_ms=? AND source_revision=?")
            .bind(next_wall).bind(next_revision).bind(wall).bind(revision).execute(&mut **tx).await.map_err(unavailable)?;
        Ok(())
    }
    /// Existing immutable preparation is returned, never extended or replaced.
    pub(super) async fn retain_preparation(
        &self,
        token: &SignedPreparedCredentialUse,
        time: &SignedTrustedTimeAttestation,
    ) -> Result<(SignedPreparedCredentialUse, bool), ConsumerPortError> {
        token.verify(&self.public_key)?;
        let intent = &token.preparation.intent;
        let (mut tx, guard) = self.begin_receipt().await?;
        self.retain_source_floor(&mut tx, time).await?;
        let retained = sqlx::query("SELECT preparation_sha256,preparation_json FROM credential_receipt_preparation WHERE operation_id=?")
            .bind(&intent.operation_id).fetch_optional(&mut *tx).await.map_err(unavailable)?;
        if let Some(row) = retained {
            let retained = self.decode_preparation(&row, &intent.operation_id)?;
            let a = &retained.preparation;
            let b = &token.preparation;
            let same = a.intent == b.intent
                && a.receipt == b.receipt
                && a.grant_sha256 == b.grant_sha256
                && a.approval_sha256 == b.approval_sha256;
            self.commit_receipt(tx, guard).await?;
            return if same {
                Ok((retained, false))
            } else {
                Err(ConsumerPortError::Conflict)
            };
        }
        // A legacy ACK has no receipt. It must never be upgraded by a caller.
        let legacy = sqlx::query_scalar::<_, i64>(
            "SELECT 1 FROM credential_consumer_ack WHERE operation_id=?",
        )
        .bind(&intent.operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .is_some();
        if legacy {
            self.commit_receipt(tx, guard).await?;
            return Err(ConsumerPortError::Conflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM credential_receipt_preparation")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        if count >= MAX_CONSUMER_OPERATIONS {
            return Err(ConsumerPortError::Capacity);
        }
        let encoding = serde_json::to_vec(token).map_err(unavailable)?;
        sqlx::query("INSERT INTO credential_receipt_preparation VALUES(?,?,?)")
            .bind(&intent.operation_id)
            .bind(Digest32::of_bytes(&encoding).as_array().as_slice())
            .bind(encoding)
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        self.commit_receipt(tx, guard).await?;
        Ok((token.clone(), true))
    }
    pub(super) async fn receipt_preparation(
        &self,
        operation: &str,
    ) -> Result<Option<SignedPreparedCredentialUse>, ConsumerPortError> {
        crate::authority_role_owner::original_id(operation)?;
        let row = sqlx::query("SELECT preparation_sha256,preparation_json FROM credential_receipt_preparation WHERE operation_id=?")
            .bind(operation).fetch_optional(&self.pool).await.map_err(unavailable)?;
        row.map(|row| self.decode_preparation(&row, operation))
            .transpose()
    }
    fn decode_preparation(
        &self,
        row: &sqlx::sqlite::SqliteRow,
        operation: &str,
    ) -> Result<SignedPreparedCredentialUse, ConsumerPortError> {
        let encoding: Vec<u8> = row.try_get("preparation_json").map_err(unavailable)?;
        let digest: Vec<u8> = row.try_get("preparation_sha256").map_err(unavailable)?;
        if encoding.is_empty()
            || encoding.len() > 32768
            || digest != Digest32::of_bytes(&encoding).as_array()
        {
            return Err(ConsumerPortError::Unavailable);
        }
        let token: SignedPreparedCredentialUse =
            serde_json::from_slice(&encoding).map_err(unavailable)?;
        token.verify(&self.public_key)?;
        if token.preparation.intent.operation_id != operation {
            return Err(ConsumerPortError::Conflict);
        }
        Ok(token)
    }
    pub(super) async fn receipt_status(
        &self,
        intent: &ConsumerIntent,
    ) -> Result<Option<super::consumer_wire::SignedConsumerAcknowledgement>, ConsumerPortError>
    {
        let Some(token) = self.receipt_preparation(&intent.operation_id).await? else {
            return Ok(None);
        };
        if token.preparation.intent != *intent {
            return Err(ConsumerPortError::Conflict);
        }
        self.status(intent).await
    }
}
