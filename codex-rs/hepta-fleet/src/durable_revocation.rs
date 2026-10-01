use sqlx::Row;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::DurableRevocationStateV1;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_rows::content_digest;
use crate::durable_rows::decode_json;
use crate::durable_rows::encode_json;
use crate::durable_rows::operation_id;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    pub async fn persist_revocation_state(
        &self,
        state: &DurableRevocationStateV1,
        convergence_deadline_ms: u64,
    ) -> Result<FleetOperationReceiptV1, DurableFleetError> {
        let update = &state.update.update;
        let epoch = update.head.authority_epoch;
        let revision = update.head.revision;
        if epoch == 0
            || revision == 0
            || update.issued_at_unix_ms >= update.expires_at_unix_ms
            || convergence_deadline_ms < update.issued_at_unix_ms
            || convergence_deadline_ms > update.expires_at_unix_ms
        {
            return Err(DurableFleetError::Invalid(
                "invalid revocation frontier".to_string(),
            ));
        }
        let update_json = encode_json(&state.update)?;
        let update_digest = content_digest(&state.update)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        if let Some(row) = sqlx::query(
            "SELECT authority_epoch, revision, update_digest FROM fleet_revocation_frontier
             WHERE singleton = 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        {
            let old_epoch = to_u64(row.try_get("authority_epoch").map_err(sqlx_error)?)?;
            let old_revision = to_u64(row.try_get("revision").map_err(sqlx_error)?)?;
            let old_digest: String = row.try_get("update_digest").map_err(sqlx_error)?;
            if (epoch, revision) < (old_epoch, old_revision) {
                return Err(DurableFleetError::Stale);
            }
            if (epoch, revision) == (old_epoch, old_revision) && old_digest != update_digest {
                return Err(DurableFleetError::Conflict("revocation frontier".into()));
            }
            if (epoch, revision) > (old_epoch, old_revision) {
                sqlx::query("DELETE FROM fleet_revocation_acks")
                    .execute(&mut *tx)
                    .await
                    .map_err(sqlx_error)?;
            }
        }
        sqlx::query(
            "INSERT INTO fleet_revocation_frontier(
                singleton, authority_epoch, revision, issued_at_ms, expires_at_ms,
                convergence_deadline_ms, update_digest, update_json, updated_at_ms
             ) VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(singleton) DO UPDATE SET
                authority_epoch = excluded.authority_epoch,
                revision = excluded.revision,
                issued_at_ms = excluded.issued_at_ms,
                expires_at_ms = excluded.expires_at_ms,
                convergence_deadline_ms = excluded.convergence_deadline_ms,
                update_digest = excluded.update_digest,
                update_json = excluded.update_json,
                updated_at_ms = excluded.updated_at_ms",
        )
        .bind(to_i64(epoch)?)
        .bind(to_i64(revision)?)
        .bind(to_i64(update.issued_at_unix_ms)?)
        .bind(to_i64(update.expires_at_unix_ms)?)
        .bind(to_i64(convergence_deadline_ms)?)
        .bind(&update_digest)
        .bind(&update_json)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        for signed in &state.acknowledgements {
            if signed.ack.authority_epoch != epoch || signed.ack.revision != revision {
                return Err(DurableFleetError::Invalid(
                    "revocation acknowledgement does not match frontier".into(),
                ));
            }
            let ack_json = encode_json(signed)?;
            let ack_digest = content_digest(signed)?;
            sqlx::query(
                "INSERT INTO fleet_revocation_acks(
                    authority_epoch, revision, node_id, ack_digest, ack_json, applied_at_ms
                 ) VALUES(?, ?, ?, ?, ?, ?)
                 ON CONFLICT(authority_epoch, revision, node_id) DO UPDATE SET
                    ack_digest = excluded.ack_digest,
                    ack_json = excluded.ack_json,
                    applied_at_ms = excluded.applied_at_ms",
            )
            .bind(to_i64(epoch)?)
            .bind(to_i64(revision)?)
            .bind(&signed.ack.node_id)
            .bind(ack_digest)
            .bind(ack_json)
            .bind(to_i64(signed.ack.applied_at_unix_ms)?)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        }
        let receipt = FleetOperationReceiptV1 {
            operation_id: operation_id("revocation", "frontier", revision),
            kind: FleetMutationKindV1::RevocationUpdate,
            subject_id: "frontier".into(),
            outcome: FleetMutationOutcomeV1::Updated,
            semantic_digest: update_digest,
            authority_witness: None,
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        match tx.commit().await {
            Ok(()) => Ok(receipt),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }

    pub async fn load_revocation_state(
        &self,
    ) -> Result<Option<DurableRevocationStateV1>, DurableFleetError> {
        let Some(row) = sqlx::query(
            "SELECT authority_epoch, revision, update_json
             FROM fleet_revocation_frontier WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(sqlx_error)?
        else {
            return Ok(None);
        };
        let epoch: i64 = row.try_get("authority_epoch").map_err(sqlx_error)?;
        let revision: i64 = row.try_get("revision").map_err(sqlx_error)?;
        let update_json: String = row.try_get("update_json").map_err(sqlx_error)?;
        let update = decode_json(&update_json)?;
        let ack_rows = sqlx::query(
            "SELECT ack_json FROM fleet_revocation_acks
             WHERE authority_epoch = ? AND revision = ? ORDER BY node_id",
        )
        .bind(epoch)
        .bind(revision)
        .fetch_all(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let acknowledgements = ack_rows
            .into_iter()
            .map(|row| {
                let json: String = row.try_get("ack_json").map_err(sqlx_error)?;
                decode_json(&json)
            })
            .collect::<Result<_, DurableFleetError>>()?;
        Ok(Some(DurableRevocationStateV1 {
            update,
            acknowledgements,
        }))
    }
}
