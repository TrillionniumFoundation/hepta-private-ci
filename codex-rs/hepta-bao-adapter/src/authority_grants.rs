//! Immutable original issuance and independent approved admission records.
use crate::ConsumerPortError;
use crate::authority_role_owner::AuthorityRoleOwner;
use crate::authority_role_owner::original_id;
use crate::role_storage::unavailable;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
const MAX_GRANTS: i64 = 65_536;
impl AuthorityRoleOwner {
    pub async fn issue(&self, operation: &str) -> Result<SignedFinalUseGrant, ConsumerPortError> {
        original_id(operation)?;
        let (mut tx, guard) = self.begin().await?;
        if let Some(grant) = self.grant_in(&mut tx, operation).await? {
            self.commit(tx, guard).await?;
            return Ok(grant); // Expiry never permits minting another nonce.
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authority_role_grant")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        if count >= MAX_GRANTS {
            return Err(ConsumerPortError::Capacity);
        }
        let now = self.protected_wall(&mut tx).await?;
        let mut nonce = [0; 32];
        std::io::Read::read_exact(
            &mut std::fs::File::open("/dev/urandom").map_err(unavailable)?,
            &mut nonce,
        )
        .map_err(unavailable)?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: self.config.issuer_id.clone(),
            authority_epoch: self.governed_head_in(&mut tx).await?.authority_epoch,
            grant_id: format!("secrets.read:{operation}"),
            nonce,
            binding: self.config.frozen_binding.clone(),
            not_before_unix_ms: now,
            expires_at_unix_ms: now
                .checked_add(self.config.grant_lifetime_ms)
                .ok_or(ConsumerPortError::Invalid)?,
        };
        let signature = self
            .keys
            .issuer
            .sign(&grant.signing_bytes().map_err(unavailable)?)
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        let encoding = serde_json::to_vec(&signed).map_err(unavailable)?;
        sqlx::query("INSERT INTO authority_role_grant VALUES(?,?,?)")
            .bind(operation)
            .bind(Digest32::of_bytes(&encoding).as_array().as_slice())
            .bind(encoding)
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        self.commit(tx, guard).await?;
        Ok(signed)
    }

    async fn grant_in(
        &self,
        tx: &mut Transaction<'static, Sqlite>,
        operation: &str,
    ) -> Result<Option<SignedFinalUseGrant>, ConsumerPortError> {
        let row = sqlx::query("SELECT grant_sha256,grant_json FROM authority_role_grant WHERE original_operation_id=?")
            .bind(operation).fetch_optional(&mut **tx).await.map_err(unavailable)?;
        row.map(|row| self.decode_grant(&row, operation))
            .transpose()
    }
    fn decode_grant(
        &self,
        row: &sqlx::sqlite::SqliteRow,
        operation: &str,
    ) -> Result<SignedFinalUseGrant, ConsumerPortError> {
        let encoding: Vec<u8> = row.try_get("grant_json").map_err(unavailable)?;
        let digest: Vec<u8> = row.try_get("grant_sha256").map_err(unavailable)?;
        if encoding.len() > 16_384 || digest != Digest32::of_bytes(&encoding).as_array() {
            return Err(ConsumerPortError::Unavailable);
        }
        let signed: SignedFinalUseGrant = serde_json::from_slice(&encoding).map_err(unavailable)?;
        if signed.grant.signer_id != self.config.issuer_id
            || signed.grant.grant_id != format!("secrets.read:{operation}")
            || signed.grant.binding != self.config.frozen_binding
        {
            return Err(ConsumerPortError::Conflict);
        }
        let signature = Signature::from_slice(&signed.signature).map_err(unavailable)?;
        self.keys
            .issuer
            .verifying_key()
            .verify_strict(
                &signed.grant.signing_bytes().map_err(unavailable)?,
                &signature,
            )
            .map_err(unavailable)?;
        Ok(signed)
    }

    pub async fn begin_original(
        &self,
        operation: &str,
        approval: &SignedFinalUseApproval,
    ) -> Result<([u8; 32], [u8; 32]), ConsumerPortError> {
        original_id(operation)?;
        let (mut tx, guard) = self.begin().await?;
        let grant = self
            .grant_in(&mut tx, operation)
            .await?
            .ok_or(ConsumerPortError::Rejected)?;
        self.keys
            .approval
            .verify(&grant, approval)
            .map_err(unavailable)?;
        let now = self.protected_wall(&mut tx).await?;
        let head = self.governed_head_in(&mut tx).await?;
        if now < grant.grant.not_before_unix_ms
            || now >= grant.grant.expires_at_unix_ms
            || grant.grant.authority_epoch != head.authority_epoch
            || head.revoked_grant_ids.contains(&grant.grant.grant_id)
        {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Rejected);
        }
        if sqlx::query_scalar::<_, i64>(
            "SELECT 1 FROM authority_role_original_begin WHERE original_operation_id=?",
        )
        .bind(operation)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .is_some()
        {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Conflict);
        }
        let grant_sha =
            Digest32::of_bytes(&serde_json::to_vec(&grant).map_err(unavailable)?).into_array();
        let approval_sha =
            Digest32::of_bytes(&serde_json::to_vec(approval).map_err(unavailable)?).into_array();
        sqlx::query("INSERT INTO authority_role_original_begin VALUES(?,?,?,?)")
            .bind(operation)
            .bind(grant_sha.as_slice())
            .bind(approval_sha.as_slice())
            .bind(serde_json::to_vec(approval).map_err(unavailable)?)
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        self.commit(tx, guard).await?;
        Ok((grant_sha, approval_sha))
    }

    pub async fn original_status(
        &self,
        operation: &str,
    ) -> Result<Option<([u8; 32], [u8; 32])>, ConsumerPortError> {
        original_id(operation)?;
        let row = sqlx::query("SELECT g.grant_json,g.grant_sha256,b.approval_json,b.approval_sha256,b.grant_sha256 AS begin_grant_sha256 FROM authority_role_original_begin b JOIN authority_role_grant g USING(original_operation_id) WHERE original_operation_id=?")
            .bind(operation).fetch_optional(&self.pool).await.map_err(unavailable)?;
        row.map(|row| {
            let grant = self.decode_grant(&row, operation)?;
            let grant_sha: [u8; 32] = row
                .try_get::<Vec<u8>, _>("grant_sha256")
                .map_err(unavailable)?
                .try_into()
                .map_err(unavailable)?;
            let begin_grant_sha: Vec<u8> =
                row.try_get("begin_grant_sha256").map_err(unavailable)?;
            let approval_json: Vec<u8> = row.try_get("approval_json").map_err(unavailable)?;
            let approval_sha: [u8; 32] = row
                .try_get::<Vec<u8>, _>("approval_sha256")
                .map_err(unavailable)?
                .try_into()
                .map_err(unavailable)?;
            if begin_grant_sha != grant_sha
                || Digest32::of_bytes(&approval_json).into_array() != approval_sha
            {
                return Err(ConsumerPortError::Unavailable);
            }
            let approval: SignedFinalUseApproval =
                serde_json::from_slice(&approval_json).map_err(unavailable)?;
            self.keys
                .approval
                .verify(&grant, &approval)
                .map_err(unavailable)?;
            Ok((grant_sha, approval_sha))
        })
        .transpose()
    }
}
