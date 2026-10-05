//! Issuer evidence is checked against frozen scope before independent signing.
use crate::ConsumerPortError;
use crate::authority_role_owner::original_id;
use crate::operator_role::OperatorRoleOwner;
use crate::role_client::verify_grant;
use crate::role_storage::unavailable;
use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use sqlx::Row;

impl OperatorRoleOwner {
    pub async fn approve(
        &self,
        grant: &SignedFinalUseGrant,
    ) -> Result<SignedFinalUseApproval, ConsumerPortError> {
        verify_grant(grant, &self.config.issuer_verifying_key)?;
        let operation = grant
            .grant
            .grant_id
            .strip_prefix("secrets.read:")
            .ok_or(ConsumerPortError::Rejected)?;
        original_id(operation)?;
        if grant.grant.signer_id != self.config.issuer_id
            || grant.grant.binding != self.config.frozen_binding
            || grant
                .grant
                .expires_at_unix_ms
                .saturating_sub(grant.grant.not_before_unix_ms)
                > self.config.maximum_grant_lifetime_ms
        {
            return Err(ConsumerPortError::Rejected);
        }
        let grant_encoding = serde_json::to_vec(grant).map_err(unavailable)?;
        let grant_sha = Digest32::of_bytes(&grant_encoding).into_array();
        // Signed authority time is fetched before the private SQL transaction.
        // It carries no authority/operator private key into this role's caller.
        let time = self.config.authority_time.trusted_time()?;
        let head = self.config.root_head()?;
        let (mut tx, guard) = self.begin().await?;
        let existing=sqlx::query("SELECT grant_sha256,grant_json,approval_json FROM operator_role_approval WHERE original_operation_id=?")
            .bind(operation).fetch_optional(&mut *tx).await.map_err(unavailable)?;
        if let Some(row) = existing {
            let original_grant: Vec<u8> = row.try_get("grant_json").map_err(unavailable)?;
            let stored_digest: Vec<u8> = row.try_get("grant_sha256").map_err(unavailable)?;
            if original_grant != grant_encoding || stored_digest != grant_sha {
                self.commit(tx, guard).await?;
                return Err(ConsumerPortError::Conflict);
            }
            let approval: SignedFinalUseApproval = serde_json::from_slice(
                &row.try_get::<Vec<u8>, _>("approval_json")
                    .map_err(unavailable)?,
            )
            .map_err(unavailable)?;
            FinalUseApprovalVerifier::new(
                self.config.approver_id.clone(),
                self.config.approval_verifying_key,
            )
            .map_err(unavailable)?
            .verify(grant, &approval)
            .map_err(unavailable)?;
            self.commit(tx, guard).await?;
            return Ok(approval);
        }
        let now = time.claims.wall_time_ms;
        if now < grant.grant.not_before_unix_ms
            || now >= grant.grant.expires_at_unix_ms
            || grant.grant.authority_epoch != head.authority_epoch
            || head.revoked_grant_ids.contains(&grant.grant.grant_id)
        {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Rejected);
        }
        self.observe_time_head(&mut tx, &time, &head).await?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operator_role_approval")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        if count >= 65_536 {
            self.commit(tx, guard).await?;
            return Err(ConsumerPortError::Capacity);
        }
        let approval = FinalUseApproval::for_grant(self.config.approver_id.clone(), &grant.grant)
            .map_err(unavailable)?;
        let signature = self
            .approval
            .sign(&approval.signing_bytes().map_err(unavailable)?)
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseApproval {
            approval,
            signature,
        };
        sqlx::query("INSERT INTO operator_role_approval VALUES(?,?,?,?)")
            .bind(operation)
            .bind(grant_sha.as_slice())
            .bind(grant_encoding)
            .bind(serde_json::to_vec(&signed).map_err(unavailable)?)
            .execute(&mut *tx)
            .await
            .map_err(unavailable)?;
        self.commit(tx, guard).await?;
        Ok(signed)
    }
}
