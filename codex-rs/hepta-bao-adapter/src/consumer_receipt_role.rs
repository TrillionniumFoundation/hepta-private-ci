//! All authority IPC occurs during preflight, before the first credential FD effect.
use super::ConsumerPortError;
use super::consumer_owner::CredentialConsumerOwner;
use super::consumer_receipt_policy::ConsumerReceiptPolicy;
use super::consumer_receipt_wire::PreparedCredentialUse;
use super::consumer_receipt_wire::SignedPreparedCredentialUse;
use super::consumer_server::CredentialConsumerServiceConfig;
use super::consumer_wire::ConsumerIntent;
use super::consumer_wire::SignedConsumerAcknowledgement;
use crate::BaoSecretReceipt;
use crate::role_storage::unavailable;
use crate::role_wire::AuthorityRequest;
use crate::role_wire::AuthorityResponse;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

struct PendingUse {
    token_sha256: [u8; 32],
    source_wall_ms: u64,
    sampled_at: Instant,
    expires_at_ms: u64,
}
pub(super) struct ReceiptConsumerRole {
    pub(super) policy: ConsumerReceiptPolicy,
    pub(super) owner: Arc<CredentialConsumerOwner>,
    pub(super) settlement_key: SigningKey,
    pub(super) source_gate: tokio::sync::Semaphore,
    pending: Mutex<BTreeMap<String, PendingUse>>,
}
impl ReceiptConsumerRole {
    pub async fn open(
        policy: ConsumerReceiptPolicy,
        config: &CredentialConsumerServiceConfig,
        owner: Arc<CredentialConsumerOwner>,
        ack_key: &SigningKey,
        credential_bytes: usize,
    ) -> Result<Self, ConsumerPortError> {
        let profile = policy.validate(
            &config.credential_sha256,
            &ack_key.verifying_key().to_bytes(),
        )?;
        if credential_bytes != policy.credential_bytes
            || policy.authority.connection.peer_uid == rustix::process::geteuid().as_raw()
            || policy.authority.connection.peer_uid == config.allowed_caller_uid
        {
            return Err(ConsumerPortError::Invalid);
        }
        let settlement_key = crate::authority_role_config::load_key(
            &policy.settlement_signing_key_file,
            &policy.settlement_verifying_key,
        )?;
        owner.enroll_receipt_profile(profile).await?;
        Ok(Self {
            policy,
            owner,
            settlement_key,
            source_gate: tokio::sync::Semaphore::new(1),
            pending: Mutex::new(BTreeMap::new()),
        })
    }
    pub async fn prepare(
        &self,
        intent: &ConsumerIntent,
        receipt: &BaoSecretReceipt,
        lifetime_limit_ms: u64,
        ack_key: &SigningKey,
    ) -> Result<SignedPreparedCredentialUse, ConsumerPortError> {
        let requested_at = Instant::now();
        if lifetime_limit_ms == 0 {
            return Err(ConsumerPortError::Rejected);
        }
        intent.validate()?;
        self.policy.verify_receipt(receipt)?;
        // Preserve one ordering from the independent source sample through
        // its FULL persisted floor. Credential authentication never takes this gate.
        let _source_order = self.source_gate.acquire().await.map_err(unavailable)?;
        let (operation, revocations) =
            match self
                .policy
                .authority
                .connection
                .call(&AuthorityRequest::OriginalDetails {
                    original_operation_id: intent.operation_id.clone(),
                })? {
                AuthorityResponse::OriginalDetails {
                    operation,
                    revocations,
                } => (operation, revocations),
                _ => return Err(ConsumerPortError::Rejected),
            };
        let grant = &operation.grant;
        if operation.original_operation_id != intent.operation_id
            || grant.grant.signer_id != self.policy.issuer_id
            || grant.grant.grant_id != format!("secrets.read:{}", intent.operation_id)
            || grant.grant.binding != self.policy.frozen_binding
            || grant.grant.authority_epoch != revocations.authority_epoch
            || revocations
                .revoked_grant_ids
                .contains(&grant.grant.grant_id)
        {
            return Err(ConsumerPortError::Rejected);
        }
        let issuer =
            VerifyingKey::from_bytes(&self.policy.issuer_verifying_key).map_err(unavailable)?;
        issuer
            .verify_strict(
                &grant.grant.signing_bytes().map_err(unavailable)?,
                &Signature::from_slice(&grant.signature).map_err(unavailable)?,
            )
            .map_err(unavailable)?;
        FinalUseApprovalVerifier::new(
            self.policy.approver_id.clone(),
            self.policy.approver_verifying_key,
        )
        .map_err(unavailable)?
        .verify(grant, &operation.approval)
        .map_err(unavailable)?;
        // The caller can only shorten Root policy. Gate/authority preflight time
        // consumes the same original budget rather than starting a new ticket.
        let preparation_lifetime_ms = self.policy.preparation_lifetime_ms.min(
            lifetime_limit_ms
                .checked_sub(
                    u64::try_from(requested_at.elapsed().as_millis()).map_err(unavailable)?,
                )
                .ok_or(ConsumerPortError::Unavailable)?,
        );
        let sampled_at = Instant::now();
        let time = self.policy.authority.trusted_time()?;
        let elapsed = u64::try_from(sampled_at.elapsed().as_millis()).map_err(unavailable)?;
        if elapsed >= preparation_lifetime_ms
            || time.claims.wall_time_ms < grant.grant.not_before_unix_ms
            || time
                .claims
                .wall_time_ms
                .checked_add(elapsed)
                .ok_or(ConsumerPortError::Unavailable)?
                >= grant.grant.expires_at_unix_ms
        {
            return Err(ConsumerPortError::Rejected);
        }
        {
            let mut pending = self.pending.lock().map_err(unavailable)?;
            pending.retain(|_, value| {
                projected_time(value).is_ok_and(|now| now < value.expires_at_ms)
            });
            if pending.len() >= 4 && !pending.contains_key(&intent.operation_id) {
                return Err(ConsumerPortError::Capacity);
            }
        }
        let mut nonce = [0; 32];
        std::io::Read::read_exact(
            &mut std::fs::File::open("/dev/urandom").map_err(unavailable)?,
            &mut nonce,
        )
        .map_err(unavailable)?;
        let preparation = PreparedCredentialUse {
            intent: intent.clone(),
            receipt: receipt.clone(),
            nonce,
            grant_sha256: Digest32::of_bytes(&serde_json::to_vec(grant).map_err(unavailable)?)
                .into_array(),
            approval_sha256: Digest32::of_bytes(
                &serde_json::to_vec(&operation.approval).map_err(unavailable)?,
            )
            .into_array(),
            expires_at_ms: time
                .claims
                .wall_time_ms
                .checked_add(preparation_lifetime_ms)
                .ok_or(ConsumerPortError::Unavailable)?
                .min(grant.grant.expires_at_unix_ms),
        };
        let signature = ack_key
            .sign(&preparation.signing_bytes()?)
            .to_bytes()
            .to_vec();
        let (token, inserted) = self
            .owner
            .retain_preparation(
                &SignedPreparedCredentialUse {
                    preparation,
                    signature,
                },
                &time,
            )
            .await?;
        // Restart cannot reconstruct permission to authenticate from a retained
        // ticket. Only Status/settlement of an actual durable ACK is recoverable.
        if inserted {
            let mut pending = self.pending.lock().map_err(unavailable)?;
            pending.retain(|_, value| {
                projected_time(value).is_ok_and(|now| now < value.expires_at_ms)
            });
            if pending.len() >= 4 && !pending.contains_key(&intent.operation_id) {
                return Err(ConsumerPortError::Capacity);
            }
            pending.insert(
                intent.operation_id.clone(),
                PendingUse {
                    token_sha256: token.preparation.digest()?,
                    source_wall_ms: time.claims.wall_time_ms,
                    sampled_at,
                    expires_at_ms: token.preparation.expires_at_ms,
                },
            );
        }
        Ok(token)
    }
    pub async fn authenticate(
        &self,
        token: &SignedPreparedCredentialUse,
        proof: &[u8; 32],
        credential: &[u8],
        ack_key: &SigningKey,
    ) -> Result<SignedConsumerAcknowledgement, ConsumerPortError> {
        token.verify(&ack_key.verifying_key().to_bytes())?;
        self.policy.verify_receipt(&token.preparation.receipt)?;
        let pending = self
            .pending
            .lock()
            .map_err(unavailable)?
            .remove(&token.preparation.intent.operation_id)
            .ok_or(ConsumerPortError::Unavailable)?;
        if pending.token_sha256 != token.preparation.digest()?
            || projected_time(&pending)? >= pending.expires_at_ms
        {
            return Err(ConsumerPortError::Unavailable);
        }
        // No authority RPC or invalidatable await precedes this first actual
        // credential authentication effect. The nonce is spent even on error.
        token.preparation.verify_proof(credential, proof)?;
        self.owner
            .acknowledge(&token.preparation.intent, ack_key)
            .await
    }
    pub async fn status(
        &self,
        intent: &ConsumerIntent,
    ) -> Result<Option<SignedConsumerAcknowledgement>, ConsumerPortError> {
        self.owner.receipt_status(intent).await
    }
}
fn projected_time(pending: &PendingUse) -> Result<u64, ConsumerPortError> {
    let elapsed = u64::try_from(pending.sampled_at.elapsed().as_millis()).map_err(unavailable)?;
    pending
        .source_wall_ms
        .checked_add(elapsed)
        .ok_or(ConsumerPortError::Unavailable)
}
