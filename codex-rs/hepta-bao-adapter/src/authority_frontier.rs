//! Governed revocation head and the external local-state CAS are separate.

use crate::ConsumerPortError;
use crate::authority_role_owner::AuthorityRoleOwner;
use crate::authority_role_owner::integer;
use crate::role_storage::unavailable;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use ed25519_dalek::Signature;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

impl AuthorityRoleOwner {
    pub async fn frontier(
        &self,
    ) -> Result<(FinalUseFrontier, FinalUseRevocations), ConsumerPortError> {
        let row = sqlx::query("SELECT authority_epoch,revocation_revision,state_sha256,governed_head_json FROM authority_role_frontier WHERE owner_id=?")
            .bind(&self.config.issuer_id).fetch_one(&self.pool).await.map_err(unavailable)?;
        decode_frontier(&row)
    }

    pub(super) async fn governed_head_in(
        &self,
        tx: &mut Transaction<'static, Sqlite>,
    ) -> Result<FinalUseRevocations, ConsumerPortError> {
        let row = sqlx::query("SELECT authority_epoch,revocation_revision,state_sha256,governed_head_json FROM authority_role_frontier WHERE owner_id=?")
            .bind(&self.config.issuer_id).fetch_one(&mut **tx).await.map_err(unavailable)?;
        decode_frontier(&row).map(|(_, head)| head)
    }

    pub async fn compare_and_set(
        &self,
        expected: FinalUseFrontier,
        next: FinalUseFrontier,
    ) -> Result<(), ConsumerPortError> {
        let (mut tx, guard) = self.begin().await?;
        let row = sqlx::query("SELECT authority_epoch,revocation_revision,state_sha256,governed_head_json FROM authority_role_frontier WHERE owner_id=?")
            .bind(&self.config.issuer_id).fetch_one(&mut *tx).await.map_err(unavailable)?;
        let (actual, allowed) = decode_frontier(&row)?;
        if actual != expected
            || next.state_sha256 == [0; 32]
            || (next.authority_epoch, next.revocation_revision)
                != (allowed.authority_epoch, allowed.revision)
        {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Conflict);
        }
        if next == expected {
            return self.commit(tx, guard).await;
        }
        let seen: Option<i64> = sqlx::query_scalar(
            "SELECT 1 FROM authority_role_frontier_history WHERE state_sha256=?",
        )
        .bind(next.state_sha256.as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if seen.is_some() {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Conflict);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authority_role_frontier_history")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        if count >= 65_536 {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Capacity);
        }
        sqlx::query("INSERT INTO authority_role_frontier_history VALUES(?)")
            .bind(next.state_sha256.as_slice())
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        let changed = sqlx::query("UPDATE authority_role_frontier SET authority_epoch=?,revocation_revision=?,state_sha256=? WHERE owner_id=? AND state_sha256=?")
            .bind(integer(next.authority_epoch)?).bind(integer(next.revocation_revision)?)
            .bind(next.state_sha256.as_slice()).bind(&self.config.issuer_id).bind(expected.state_sha256.as_slice())
            .execute(&mut *tx).await.map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(ConsumerPortError::Unavailable);
        }
        self.commit(tx, guard).await
    }

    pub async fn apply_revocations(
        &self,
        signed: &SignedFinalUseRevocationUpdate,
    ) -> Result<(), ConsumerPortError> {
        if signed.update.distributor_id != self.config.distributor_id {
            return Err(ConsumerPortError::Rejected);
        }
        self.keys
            .revocation
            .verify_strict(
                &signed.update.signing_bytes().map_err(unavailable)?,
                &Signature::from_slice(&signed.signature).map_err(unavailable)?,
            )
            .map_err(unavailable)?;
        let (mut tx, guard) = self.begin().await?;
        let now = self.protected_wall(&mut tx).await?;
        let old = self.governed_head_in(&mut tx).await?;
        let head = &signed.update.head;
        let invalid = now < signed.update.issued_at_unix_ms
            || now >= signed.update.expires_at_unix_ms
            || head.authority_epoch < old.authority_epoch
            || (head.authority_epoch == old.authority_epoch
                && (head.revision < old.revision
                    || !old.revoked_grant_ids.is_subset(&head.revoked_grant_ids)))
            || (head.authority_epoch == old.authority_epoch
                && head.revision == old.revision
                && head != &old);
        if invalid {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Rejected);
        }
        // A newer allowed head does not pretend that the replaceable runtime
        // has already committed its matching nonce state.
        sqlx::query("UPDATE authority_role_frontier SET governed_head_json=? WHERE owner_id=?")
            .bind(serde_json::to_vec(head).map_err(unavailable)?)
            .bind(&self.config.issuer_id)
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        self.commit(tx, guard).await
    }
}

fn decode_frontier(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<(FinalUseFrontier, FinalUseRevocations), ConsumerPortError> {
    let frontier = FinalUseFrontier {
        authority_epoch: u64::try_from(
            row.try_get::<i64, _>("authority_epoch")
                .map_err(unavailable)?,
        )
        .map_err(unavailable)?,
        revocation_revision: u64::try_from(
            row.try_get::<i64, _>("revocation_revision")
                .map_err(unavailable)?,
        )
        .map_err(unavailable)?,
        state_sha256: row
            .try_get::<Vec<u8>, _>("state_sha256")
            .map_err(unavailable)?
            .try_into()
            .map_err(unavailable)?,
    };
    let bytes: Vec<u8> = row.try_get("governed_head_json").map_err(unavailable)?;
    if bytes.len() > 65_536 {
        return Err(ConsumerPortError::Unavailable);
    }
    let head: FinalUseRevocations = serde_json::from_slice(&bytes).map_err(unavailable)?;
    FinalUseFrontier::for_initial_head(&head).map_err(unavailable)?;
    if frontier.state_sha256 == [0; 32]
        || frontier.authority_epoch == 0
        || frontier.revocation_revision == 0
        || frontier.authority_epoch > head.authority_epoch
        || (frontier.authority_epoch == head.authority_epoch
            && frontier.revocation_revision > head.revision)
    {
        return Err(ConsumerPortError::Unavailable);
    }
    Ok((frontier, head))
}
