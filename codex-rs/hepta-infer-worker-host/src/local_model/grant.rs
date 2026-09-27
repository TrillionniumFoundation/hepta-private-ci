use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};

use super::{
    digest, validate_digest, validate_identity, Error, TrustedClock, TrustedDeadline,
    MAX_DEADLINE_HORIZON_MS, MAX_TOKENS,
};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceGrantClaims {
    pub issuer: String,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub grant_id: String,
    pub nonce: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_digest: String,
    pub maximum_model_memory_bytes: u64,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_kv_memory_bytes: u64,
    pub maximum_transient_memory_bytes: u64,
    pub maximum_concurrent_requests: usize,
    pub maximum_tokens: u32,
    pub expires_at_ms: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedResourceGrant {
    pub claims: ResourceGrantClaims,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug)]
struct GrantRevocationState {
    authority_epoch: u64,
    revision: u64,
    revoked_nonces: BTreeSet<String>,
}

#[derive(Clone, Debug)]
pub struct ResourceGrantVerifier {
    issuer: String,
    verifying_key: VerifyingKey,
    revocations: Arc<Mutex<GrantRevocationState>>,
}

impl ResourceGrantVerifier {
    pub fn new(
        issuer: String,
        verifying_key: [u8; 32],
        authority_epoch: u64,
        revocation_revision: u64,
        revoked_nonces: BTreeSet<String>,
    ) -> Result<Self, Error> {
        validate_identity(&issuer, "issuer")?;
        if authority_epoch == 0 {
            return Err(Error::InvalidGrant("authority epoch"));
        }
        Ok(Self {
            issuer,
            verifying_key: VerifyingKey::from_bytes(&verifying_key)
                .map_err(|_| Error::Signature)?,
            revocations: Arc::new(Mutex::new(GrantRevocationState {
                authority_epoch,
                revision: revocation_revision,
                revoked_nonces,
            })),
        })
    }

    pub fn update_revocations(
        &self,
        authority_epoch: u64,
        revision: u64,
        revoked_nonces: BTreeSet<String>,
    ) -> Result<(), Error> {
        let mut current = self
            .revocations
            .lock()
            .map_err(|_| Error::LockPoisoned)?;
        if authority_epoch < current.authority_epoch
            || (authority_epoch == current.authority_epoch
                && revision < current.revision)
        {
            return Err(Error::InvalidGrant("revocation rollback"));
        }
        if authority_epoch == current.authority_epoch
            && revision == current.revision
            && revoked_nonces != current.revoked_nonces
        {
            return Err(Error::InvalidGrant("revocation fork"));
        }
        current.authority_epoch = authority_epoch;
        current.revision = revision;
        current.revoked_nonces = revoked_nonces;
        Ok(())
    }

    pub fn verify(
        &self,
        signed: &SignedResourceGrant,
        now_ms: u64,
        expected_worker_id: &str,
        expected_generation: u64,
    ) -> Result<VerifiedResourceGrant, Error> {
        validate_claims(&signed.claims)?;
        validate_identity(expected_worker_id, "expected worker")?;
        let revocations = self
            .revocations
            .lock()
            .map_err(|_| Error::LockPoisoned)?
            .clone();
        if signed.claims.issuer != self.issuer
            || signed.claims.authority_epoch != revocations.authority_epoch
            || signed.claims.revocation_revision > revocations.revision
            || signed.claims.worker_id != expected_worker_id
            || signed.claims.worker_generation != expected_generation
            || expected_generation == 0
            || now_ms >= signed.claims.expires_at_ms
            || revocations.revoked_nonces.contains(&signed.claims.nonce)
        {
            return Err(Error::InvalidGrant("authority binding"));
        }
        if resource_grant_semantic_digest(&signed.claims)?
            != signed.claims.semantic_digest
        {
            return Err(Error::InvalidGrant("semantic digest"));
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| Error::Signature)?;
        let message = resource_grant_signing_bytes(&signed.claims)?;
        self.verifying_key
            .verify_strict(&message, &signature)
            .map_err(|_| Error::Signature)?;
        let mut witness = message;
        witness.extend_from_slice(&signed.signature);
        Ok(VerifiedResourceGrant {
            claims: signed.claims.clone(),
            witness_digest: digest(&witness),
            revocations: Arc::clone(&self.revocations),
        })
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    pub(crate) claims: ResourceGrantClaims,
    pub(crate) witness_digest: String,
    revocations: Arc<Mutex<GrantRevocationState>>,
}

impl VerifiedResourceGrant {
    pub fn grant_id(&self) -> &str {
        &self.claims.grant_id
    }

    pub fn witness_digest(&self) -> &str {
        &self.witness_digest
    }

    pub fn expires_at_ms(&self) -> u64 {
        self.claims.expires_at_ms
    }

    pub fn maximum_tokens(&self) -> u32 {
        self.claims.maximum_tokens
    }

    pub(crate) fn validate_live(
        &self,
        now_ms: u64,
        worker_id: &str,
        generation: u64,
    ) -> Result<(), Error> {
        let revocations = self
            .revocations
            .lock()
            .map_err(|_| Error::LockPoisoned)?;
        if self.claims.worker_id != worker_id
            || self.claims.worker_generation != generation
            || now_ms >= self.claims.expires_at_ms
            || revocations.authority_epoch != self.claims.authority_epoch
            || revocations.revision < self.claims.revocation_revision
            || revocations.revoked_nonces.contains(&self.claims.nonce)
        {
            return Err(Error::InvalidGrant(
                "expired, revoked or wrong worker generation",
            ));
        }
        Ok(())
    }

    pub fn verify_manifest(
        &self,
        manifest: ModelManifestEvidence,
    ) -> Result<VerifiedModelManifest, Error> {
        validate_manifest(&manifest)?;
        if manifest.model_id != self.claims.model_id
            || manifest.model_digest != self.claims.model_digest
            || manifest.weights_digest != self.claims.weights_digest
            || manifest.tokenizer_digest != self.claims.tokenizer_digest
            || manifest.preprocessor_digest != self.claims.preprocessor_digest
            || manifest.quantization_digest != self.claims.quantization_digest
            || manifest.runtime_digest != self.claims.runtime_digest
            || manifest.device_id != self.claims.device_id
            || manifest.device_digest != self.claims.device_digest
            || manifest.declared_weight_bytes
                > self.claims.maximum_model_memory_bytes
            || manifest.maximum_kv_memory_bytes
                > self.claims.maximum_kv_memory_bytes
            || manifest.maximum_transient_memory_bytes
                > self.claims.maximum_transient_memory_bytes
            || manifest.maximum_tokens > self.claims.maximum_tokens
        {
            return Err(Error::InvalidManifest("grant tuple mismatch"));
        }
        Ok(VerifiedModelManifest { manifest })
    }

    pub fn verify_deadline<C: TrustedClock>(
        &self,
        clock: &C,
        deadline_ms: u64,
    ) -> Result<TrustedDeadline, Error> {
        let now_ms = clock.now_ms()?;
        if deadline_ms <= now_ms
            || deadline_ms > self.claims.expires_at_ms
            || deadline_ms.saturating_sub(now_ms)
                > MAX_DEADLINE_HORIZON_MS
        {
            return Err(Error::InvalidDeadline);
        }
        Ok(TrustedDeadline {
            absolute_ms: deadline_ms,
            instant: clock.instant_for(deadline_ms)?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifestEvidence {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_digest: String,
    pub declared_weight_bytes: u64,
    pub maximum_kv_memory_bytes: u64,
    pub maximum_transient_memory_bytes: u64,
    pub maximum_tokens: u32,
}

#[derive(Clone, Debug)]
pub struct VerifiedModelManifest {
    pub(crate) manifest: ModelManifestEvidence,
}

impl VerifiedModelManifest {
    pub fn evidence(&self) -> &ModelManifestEvidence {
        &self.manifest
    }
}

pub fn resource_grant_semantic_digest(
    claims: &ResourceGrantClaims,
) -> Result<String, Error> {
    let mut canonical = claims.clone();
    canonical.semantic_digest.clear();
    let bytes = serde_json::to_vec(&(
        "hepta.local-resource-grant.semantic.v1",
        canonical,
    ))
    .map_err(|_| Error::InvalidGrant("serialization"))?;
    Ok(digest(&bytes))
}

pub fn resource_grant_signing_bytes(
    claims: &ResourceGrantClaims,
) -> Result<Vec<u8>, Error> {
    serde_json::to_vec(&("hepta.local-resource-grant.signed.v1", claims))
        .map_err(|_| Error::InvalidGrant("serialization"))
}

fn validate_claims(claims: &ResourceGrantClaims) -> Result<(), Error> {
    for (value, field) in [
        (&claims.issuer, "issuer"),
        (&claims.grant_id, "grant"),
        (&claims.nonce, "nonce"),
        (&claims.worker_id, "worker"),
        (&claims.model_id, "model"),
        (&claims.device_id, "device"),
    ] {
        validate_identity(value, field)?;
    }
    for (value, field) in [
        (&claims.model_digest, "model"),
        (&claims.weights_digest, "weights"),
        (&claims.tokenizer_digest, "tokenizer"),
        (&claims.preprocessor_digest, "preprocessor"),
        (&claims.quantization_digest, "quantization"),
        (&claims.runtime_digest, "runtime"),
        (&claims.device_digest, "device"),
        (&claims.semantic_digest, "semantic"),
    ] {
        validate_digest(value, field)?;
    }
    if claims.authority_epoch == 0
        || claims.worker_generation == 0
        || claims.maximum_model_memory_bytes == 0
        || claims.maximum_aggregate_memory_bytes
            < claims.maximum_model_memory_bytes
        || claims.maximum_kv_memory_bytes == 0
        || claims.maximum_transient_memory_bytes == 0
        || claims.maximum_concurrent_requests == 0
        || claims.maximum_tokens == 0
        || claims.maximum_tokens > MAX_TOKENS
        || claims.expires_at_ms == 0
    {
        return Err(Error::InvalidGrant("bounds"));
    }
    Ok(())
}

fn validate_manifest(manifest: &ModelManifestEvidence) -> Result<(), Error> {
    validate_identity(&manifest.model_id, "model")?;
    validate_identity(&manifest.device_id, "device")?;
    for (value, field) in [
        (&manifest.model_digest, "model"),
        (&manifest.weights_digest, "weights"),
        (&manifest.tokenizer_digest, "tokenizer"),
        (&manifest.preprocessor_digest, "preprocessor"),
        (&manifest.quantization_digest, "quantization"),
        (&manifest.runtime_digest, "runtime"),
        (&manifest.device_digest, "device"),
    ] {
        validate_digest(value, field)?;
    }
    if manifest.declared_weight_bytes == 0
        || manifest.maximum_kv_memory_bytes == 0
        || manifest.maximum_transient_memory_bytes == 0
        || manifest.maximum_tokens == 0
        || manifest.maximum_tokens > MAX_TOKENS
    {
        return Err(Error::InvalidManifest("bounds"));
    }
    Ok(())
}
