use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::{
    NativeBoundaryStatus, NativeDispatch, NativeOwnerAuthority, NativeRequest,
    NativeReservationState, NativeRunOutput, NativeRunStatus,
};
use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

const GRANT_SCHEMA: u32 = 1;
const MANIFEST_SCHEMA: u32 = 1;
const MAX_INPUT_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOKENS: u64 = 1_000_000;
const LOCAL_PROVIDER: &str = "local-model-driver";

type DriverFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, DriverError>> + Send + 'a>>;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceGrantClaims {
    pub schema_version: u32,
    pub issuer_id: String,
    pub authority_epoch: u64,
    pub grant_id: String,
    pub nonce: String,
    pub worker_subject: String,
    pub worker_generation: u64,
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_lease_id: String,
    pub maximum_model_memory_bytes: u64,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_models: usize,
    pub maximum_concurrency: usize,
    pub maximum_tokens_per_request: u64,
    pub maximum_total_usage_tokens: u64,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: String,
    pub semantic_digest: String,
}

impl ResourceGrantClaims {
    fn semantic_bytes(&self) -> Vec<u8> {
        let mut hasher = Sha256::new();
        frame(&mut hasher, b"hepta.local-model.resource-grant.v1");
        frame_u32(&mut hasher, self.schema_version);
        for value in [
            self.issuer_id.as_bytes(),
            self.grant_id.as_bytes(),
            self.nonce.as_bytes(),
            self.worker_subject.as_bytes(),
            self.model_id.as_bytes(),
            self.model_digest.as_bytes(),
            self.weights_digest.as_bytes(),
            self.tokenizer_digest.as_bytes(),
            self.preprocessor_digest.as_bytes(),
            self.quantization_digest.as_bytes(),
            self.runtime_digest.as_bytes(),
            self.device_id.as_bytes(),
            self.device_lease_id.as_bytes(),
            self.revocation_head_digest.as_bytes(),
        ] {
            frame(&mut hasher, value);
        }
        for value in [
            self.authority_epoch,
            self.worker_generation,
            self.maximum_model_memory_bytes,
            self.maximum_aggregate_memory_bytes,
            u64::try_from(self.maximum_models).unwrap_or(u64::MAX),
            u64::try_from(self.maximum_concurrency).unwrap_or(u64::MAX),
            self.maximum_tokens_per_request,
            self.maximum_total_usage_tokens,
            self.not_before_unix_ms,
            self.expires_at_unix_ms,
            self.revocation_revision,
        ] {
            frame_u64(&mut hasher, value);
        }
        hasher.finalize().to_vec()
    }

    fn expected_semantic_digest(&self) -> String {
        digest(&self.semantic_bytes())
    }

    fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = self.semantic_bytes();
        bytes.extend_from_slice(self.semantic_digest.as_bytes());
        bytes
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedResourceGrant {
    pub claims: ResourceGrantClaims,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceRevocationHead {
    pub authority_epoch: u64,
    pub revision: u64,
    pub head_digest: String,
    pub revoked_grant_ids: BTreeSet<String>,
}

pub struct ResourceGrantVerifier {
    issuer_id: String,
    key: VerifyingKey,
    revocations: ResourceRevocationHead,
    consumed_nonces: BTreeSet<String>,
}

impl ResourceGrantVerifier {
    pub fn new(
        issuer_id: String,
        key: [u8; 32],
        revocations: ResourceRevocationHead,
    ) -> Result<Self, LocalModelError> {
        validate_identifier(&issuer_id, "issuer")?;
        validate_revocation_head(&revocations)?;
        let key = VerifyingKey::from_bytes(&key)
            .map_err(|_| LocalModelError::InvalidGrant("malformed verifying key"))?;
        if key.is_weak() {
            return Err(LocalModelError::InvalidGrant("weak verifying key"));
        }
        Ok(Self {
            issuer_id,
            key,
            revocations,
            consumed_nonces: BTreeSet::new(),
        })
    }

    pub fn advance_revocations(
        &mut self,
        next: ResourceRevocationHead,
    ) -> Result<(), LocalModelError> {
        validate_revocation_head(&next)?;
        if next.authority_epoch != self.revocations.authority_epoch
            || next.revision < self.revocations.revision
            || (next.revision == self.revocations.revision && next != self.revocations)
        {
            return Err(LocalModelError::RevocationRollback);
        }
        self.revocations = next;
        Ok(())
    }

    pub fn verify(
        &mut self,
        signed: SignedResourceGrant,
    ) -> Result<VerifiedResourceGrant, LocalModelError> {
        validate_grant_shape(&signed.claims)?;
        let claims = &signed.claims;
        if claims.issuer_id != self.issuer_id
            || claims.authority_epoch != self.revocations.authority_epoch
            || claims.revocation_revision != self.revocations.revision
            || claims.revocation_head_digest != self.revocations.head_digest
            || claims.semantic_digest != claims.expected_semantic_digest()
        {
            return Err(LocalModelError::GrantBinding);
        }
        if self.revocations.revoked_grant_ids.contains(&claims.grant_id) {
            return Err(LocalModelError::GrantRevoked);
        }
        let now = unix_time_ms()?;
        if now < claims.not_before_unix_ms || now >= claims.expires_at_unix_ms {
            return Err(LocalModelError::GrantExpired);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| LocalModelError::InvalidGrant("malformed signature"))?;
        self.key
            .verify_strict(&claims.signing_bytes(), &signature)
            .map_err(|_| LocalModelError::InvalidGrant("signature verification failed"))?;
        if !self.consumed_nonces.insert(claims.nonce.clone()) {
            return Err(LocalModelError::GrantReplay);
        }
        let witness_digest = digest(
            &[
                claims.semantic_digest.as_bytes(),
                signed.signature.as_slice(),
                self.revocations.head_digest.as_bytes(),
            ]
            .concat(),
        );
        Ok(VerifiedResourceGrant {
            claims: signed.claims,
            witness_digest,
        })
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    claims: ResourceGrantClaims,
    witness_digest: String,
}

impl VerifiedResourceGrant {
    #[must_use]
    pub fn claims(&self) -> &ResourceGrantClaims {
        &self.claims
    }

    #[must_use]
    pub fn witness_digest(&self) -> &str {
        &self.witness_digest
    }

    fn revalidate(&self, worker: &str, generation: u64) -> Result<(), LocalModelError> {
        let now = unix_time_ms()?;
        if self.claims.worker_subject != worker || self.claims.worker_generation != generation {
            return Err(LocalModelError::GrantBinding);
        }
        if now < self.claims.not_before_unix_ms || now >= self.claims.expires_at_unix_ms {
            return Err(LocalModelError::GrantExpired);
        }
        Ok(())
    }
}
