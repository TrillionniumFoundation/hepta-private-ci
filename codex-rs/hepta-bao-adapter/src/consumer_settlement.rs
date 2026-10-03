//! Consumer-owned evidence is derived from its FULL receipt and real signed ACK.
use super::ConsumerPortError;
use super::consumer_receipt_role::ReceiptConsumerRole;
use super::consumer_wire::MAX_CONSUMER_OPERATIONS;
use crate::role_storage::unavailable;
use codex_hepta_authbus::SettlementEvidenceClaims;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SettlementAttestation {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub reservation_id: String,
    pub operation_id: String,
    pub observed_cost: u64,
    pub terminal_evidence_digest: [u8; 32],
    pub observed_at_ms: u64,
    pub expires_at_ms: u64,
    pub signature: Vec<u8>,
}
impl SettlementAttestation {
    pub fn from_signed(evidence: SignedSettlementEvidence) -> Self {
        let claims = evidence.claims;
        Self {
            issuer_id: claims.issuer_id.as_str().to_owned(),
            key_epoch: claims.key_epoch.get(),
            reservation_id: claims.reservation_id.as_str().to_owned(),
            operation_id: claims.operation_id.as_str().to_owned(),
            observed_cost: claims.observed_cost,
            terminal_evidence_digest: claims.terminal_evidence_digest.into_array(),
            observed_at_ms: claims.observed_at_ms,
            expires_at_ms: claims.expires_at_ms,
            signature: evidence.signature.to_vec(),
        }
    }
    pub fn verify(
        self,
        issuer: &str,
        epoch: u64,
        key: &[u8; 32],
    ) -> Result<SignedSettlementEvidence, ConsumerPortError> {
        if self.issuer_id != issuer
            || self.key_epoch != epoch
            || self.observed_cost == 0
            || self.observed_at_ms == 0
            || self.expires_at_ms <= self.observed_at_ms
            || self.terminal_evidence_digest == [0; 32]
        {
            return Err(ConsumerPortError::Rejected);
        }
        let claims = SettlementEvidenceClaims {
            issuer_id: StableId::new(self.issuer_id).map_err(unavailable)?,
            key_epoch: Generation::new(self.key_epoch).map_err(unavailable)?,
            reservation_id: StableId::new(self.reservation_id).map_err(unavailable)?,
            operation_id: StableId::new(self.operation_id).map_err(unavailable)?,
            status: SettlementStatus::Completed,
            observed_cost: self.observed_cost,
            terminal_evidence_digest: Digest32::from_array(self.terminal_evidence_digest),
            observed_at_ms: self.observed_at_ms,
            expires_at_ms: self.expires_at_ms,
        };
        let signature: [u8; 64] = self.signature.try_into().map_err(unavailable)?;
        let key = VerifyingKey::from_bytes(key).map_err(unavailable)?;
        if key.is_weak() {
            return Err(ConsumerPortError::Invalid);
        }
        key.verify_strict(&claims.signing_bytes(), &Signature::from_bytes(&signature))
            .map_err(unavailable)?;
        Ok(SignedSettlementEvidence { claims, signature })
    }
}
impl ReceiptConsumerRole {
    pub async fn settlement(
        &self,
        operation: &str,
        reservation: &str,
    ) -> Result<SettlementAttestation, ConsumerPortError> {
        crate::authority_role_owner::original_id(operation)?;
        StableId::new(reservation).map_err(unavailable)?;
        let token = self
            .owner
            .receipt_preparation(operation)
            .await?
            .ok_or(ConsumerPortError::Rejected)?;
        self.policy.verify_receipt(&token.preparation.receipt)?;
        let ack = self
            .owner
            .receipt_status(&token.preparation.intent)
            .await?
            .ok_or(ConsumerPortError::Rejected)?;
        let terminal = token
            .preparation
            .receipt
            .evidence_digest()
            .map_err(unavailable)?;
        let ack_digest =
            Digest32::of_bytes(&serde_json::to_vec(&ack).map_err(unavailable)?).into_array();
        // The time authority is independent. No caller status, cost, observed
        // time or terminal digest is accepted as an evidence source.
        let _source_order = self.source_gate.acquire().await.map_err(unavailable)?;
        let time = self.policy.authority.trusted_time()?;
        let (mut tx, guard) = self.owner.begin_receipt().await?;
        self.owner.retain_source_floor(&mut tx, &time).await?;
        let retained = sqlx::query("SELECT reservation_id,receipt_sha256,acknowledgement_sha256,cost FROM credential_settlement_binding WHERE operation_id=?")
            .bind(operation).fetch_optional(&mut *tx).await.map_err(unavailable)?;
        if let Some(row) = retained {
            let res: String = row.try_get("reservation_id").map_err(unavailable)?;
            let receipt: Vec<u8> = row.try_get("receipt_sha256").map_err(unavailable)?;
            let acknowledgement: Vec<u8> =
                row.try_get("acknowledgement_sha256").map_err(unavailable)?;
            let cost: i64 = row.try_get("cost").map_err(unavailable)?;
            if res != reservation
                || receipt != terminal
                || acknowledgement != ack_digest
                || u64::try_from(cost).map_err(unavailable)? != self.policy.cost
            {
                self.owner.commit_receipt(tx, guard).await?;
                return Err(ConsumerPortError::Conflict);
            }
        } else {
            let already: Option<String> = sqlx::query_scalar(
                "SELECT operation_id FROM credential_settlement_binding WHERE reservation_id=?",
            )
            .bind(reservation)
            .fetch_optional(&mut *tx)
            .await
            .map_err(unavailable)?;
            if already.is_some() {
                self.owner.commit_receipt(tx, guard).await?;
                return Err(ConsumerPortError::Conflict);
            }
            sqlx::query("INSERT INTO credential_settlement_binding VALUES(?,?,?,?,?)")
                .bind(operation)
                .bind(reservation)
                .bind(terminal.as_slice())
                .bind(ack_digest.as_slice())
                .bind(i64::try_from(self.policy.cost).map_err(unavailable)?)
                .execute(&mut *tx)
                .await
                .map_err(unavailable)?;
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM credential_settlement_evidence")
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
        let claims = SettlementEvidenceClaims {
            issuer_id: StableId::new(&self.policy.settlement_issuer_id).map_err(unavailable)?,
            key_epoch: Generation::new(self.policy.settlement_key_epoch).map_err(unavailable)?,
            reservation_id: StableId::new(reservation).map_err(unavailable)?,
            operation_id: StableId::new(operation).map_err(unavailable)?,
            status: SettlementStatus::Completed,
            observed_cost: self.policy.cost,
            terminal_evidence_digest: Digest32::from_array(terminal),
            observed_at_ms: time.claims.wall_time_ms,
            expires_at_ms: time
                .claims
                .wall_time_ms
                .checked_add(self.policy.settlement_lifetime_ms)
                .ok_or(ConsumerPortError::Unavailable)?,
        };
        let signature = self.settlement_key.sign(&claims.signing_bytes()).to_bytes();
        let evidence =
            SettlementAttestation::from_signed(SignedSettlementEvidence { claims, signature });
        let encoding = serde_json::to_vec(&evidence).map_err(unavailable)?;
        let digest = Digest32::of_bytes(&encoding);
        let retained: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT evidence_json FROM credential_settlement_evidence WHERE evidence_sha256=?",
        )
        .bind(digest.as_array().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if let Some(retained) = retained {
            if retained != encoding {
                return Err(ConsumerPortError::Unavailable);
            }
            self.owner.commit_receipt(tx, guard).await?;
            return Ok(evidence);
        }
        if count >= MAX_CONSUMER_OPERATIONS {
            return Err(ConsumerPortError::Capacity);
        }
        sqlx::query("INSERT INTO credential_settlement_evidence(operation_id,evidence_sha256,evidence_json) VALUES(?,?,?)")
            .bind(operation).bind(Digest32::of_bytes(&encoding).as_array().as_slice()).bind(encoding)
            .execute(&mut *tx).await.map_err(unavailable)?;
        self.owner.commit_receipt(tx, guard).await?;
        Ok(evidence)
    }
}
