use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::time::Instant;

use super::LocalRuntimeError;

const MAX_SIGNATURE_BYTES: usize = 4 * 1024;
const MAX_INPUT_BYTES: usize = 4 * 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;

pub trait TrustedClock: Send + Sync {
    fn unix_time_ms(&self) -> Result<u64, LocalRuntimeError>;
    fn monotonic_now(&self) -> Instant;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemTrustedClock;

impl TrustedClock for SystemTrustedClock {
    fn unix_time_ms(&self) -> Result<u64, LocalRuntimeError> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| LocalRuntimeError::Clock(error.to_string()))?;
        u64::try_from(elapsed.as_millis())
            .map_err(|_| LocalRuntimeError::Clock("wall clock overflow".to_string()))
    }

    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceGrantClaims {
    pub issuer_id: StableId,
    pub grant_id: StableId,
    pub nonce: StableId,
    pub authority_epoch: u64,
    pub worker_subject: StableId,
    pub worker_generation: Generation,
    pub model_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_id: StableId,
    pub artifact_descriptor_digest: Digest32,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_concurrency: usize,
    pub maximum_tokens: u32,
    pub expires_at_ms: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: Digest32,
    pub semantic_digest: Digest32,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedResourceGrant {
    pub claims: ResourceGrantClaims,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityVerification {
    pub signer_id: StableId,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub witness_digest: Digest32,
    /// The authority port must durably claim the nonce, not merely validate a
    /// detached signature in memory.
    pub replay_protected: bool,
}

pub trait ResourceGrantAuthority: Send + Sync {
    fn claim(
        &self,
        grant: &SignedResourceGrant,
        canonical_semantic_digest: Digest32,
    ) -> Result<AuthorityVerification, LocalRuntimeError>;
}

pub struct GrantVerifier<A, C> {
    authority: A,
    clock: C,
}

impl<A, C> GrantVerifier<A, C>
where
    A: ResourceGrantAuthority,
    C: TrustedClock,
{
    pub fn new(authority: A, clock: C) -> Self {
        Self { authority, clock }
    }

    pub fn verify(
        &self,
        signed: SignedResourceGrant,
    ) -> Result<VerifiedResourceGrant, LocalRuntimeError> {
        validate_grant_claims(&signed.claims)?;
        if signed.signature.is_empty() || signed.signature.len() > MAX_SIGNATURE_BYTES {
            return Err(LocalRuntimeError::InvalidGrant("signature size"));
        }
        let canonical = grant_semantic_digest(&signed.claims);
        if canonical != signed.claims.semantic_digest {
            return Err(LocalRuntimeError::InvalidGrant("semantic digest"));
        }
        if signed.claims.revoked {
            return Err(LocalRuntimeError::Revoked);
        }
        let now_ms = self.clock.unix_time_ms()?;
        if now_ms >= signed.claims.expires_at_ms {
            return Err(LocalRuntimeError::Expired);
        }
        let verification = self.authority.claim(&signed, canonical)?;
        if verification.signer_id != signed.claims.issuer_id
            || verification.authority_epoch != signed.claims.authority_epoch
            || verification.revocation_revision < signed.claims.revocation_revision
            || verification.witness_digest.is_zero()
            || !verification.replay_protected
        {
            return Err(LocalRuntimeError::Authority(
                "authority witness does not match the exact grant".to_string(),
            ));
        }
        Ok(VerifiedResourceGrant {
            claims: signed.claims,
            authority_witness_digest: verification.witness_digest,
            verified_at_ms: now_ms,
        })
    }
}

#[derive(Debug)]
pub struct VerifiedResourceGrant {
    claims: ResourceGrantClaims,
    authority_witness_digest: Digest32,
    verified_at_ms: u64,
}

impl VerifiedResourceGrant {
    pub fn claims(&self) -> &ResourceGrantClaims {
        &self.claims
    }

    pub fn authority_witness_digest(&self) -> Digest32 {
        self.authority_witness_digest
    }

    pub fn verified_at_ms(&self) -> u64 {
        self.verified_at_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifestClaims {
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_id: StableId,
    pub artifact_descriptor_digest: Digest32,
    pub expected_weight_bytes: u64,
    pub maximum_tokens: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactVerification {
    pub witness_digest: Digest32,
    pub manifest_digest: Digest32,
    pub device_id: StableId,
    pub runtime_digest: Digest32,
    pub observed_weight_bytes: u64,
    pub physical_bytes_observed: bool,
}

pub trait ModelArtifactAuthority: Send + Sync {
    fn attest(
        &self,
        manifest: &ModelManifestClaims,
        grant: &VerifiedResourceGrant,
        canonical_manifest_digest: Digest32,
    ) -> Result<ArtifactVerification, LocalRuntimeError>;
}

pub struct ManifestVerifier<A> {
    authority: A,
}

impl<A> ManifestVerifier<A>
where
    A: ModelArtifactAuthority,
{
    pub fn new(authority: A) -> Self {
        Self { authority }
    }

    pub fn verify(
        &self,
        manifest: ModelManifestClaims,
        grant: &VerifiedResourceGrant,
    ) -> Result<VerifiedModelManifest, LocalRuntimeError> {
        validate_manifest(&manifest)?;
        let grant_claims = grant.claims();
        if manifest.model_digest != grant_claims.model_digest
            || manifest.weights_digest != grant_claims.weights_digest
            || manifest.tokenizer_digest != grant_claims.tokenizer_digest
            || manifest.preprocessor_digest != grant_claims.preprocessor_digest
            || manifest.quantization_digest != grant_claims.quantization_digest
            || manifest.runtime_digest != grant_claims.runtime_digest
            || manifest.device_id != grant_claims.device_id
            || manifest.artifact_descriptor_digest != grant_claims.artifact_descriptor_digest
            || manifest.maximum_tokens > grant_claims.maximum_tokens
            || manifest.expected_weight_bytes > grant_claims.maximum_aggregate_memory_bytes
        {
            return Err(LocalRuntimeError::InvalidManifest("grant tuple mismatch"));
        }
        let canonical = manifest_semantic_digest(&manifest);
        let attestation = self.authority.attest(&manifest, grant, canonical)?;
        if attestation.witness_digest.is_zero()
            || attestation.manifest_digest != canonical
            || attestation.device_id != manifest.device_id
            || attestation.runtime_digest != manifest.runtime_digest
            || attestation.observed_weight_bytes != manifest.expected_weight_bytes
            || !attestation.physical_bytes_observed
        {
            return Err(LocalRuntimeError::Artifact(
                "artifact authority did not prove the exact physical tuple".to_string(),
            ));
        }
        Ok(VerifiedModelManifest {
            claims: manifest,
            semantic_digest: canonical,
            artifact_witness_digest: attestation.witness_digest,
        })
    }
}

#[derive(Debug)]
pub struct VerifiedModelManifest {
    claims: ModelManifestClaims,
    semantic_digest: Digest32,
    artifact_witness_digest: Digest32,
}

impl VerifiedModelManifest {
    pub fn claims(&self) -> &ModelManifestClaims {
        &self.claims
    }

    pub fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    pub fn artifact_witness_digest(&self) -> Digest32 {
        self.artifact_witness_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InputEnvelope {
    pub operation_id: StableId,
    pub bytes: Vec<u8>,
    pub payload_digest: Digest32,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub kv_memory_bytes: u64,
    pub transient_memory_bytes: u64,
}

pub struct InputVerifier<C> {
    clock: C,
}

impl<C> InputVerifier<C>
where
    C: TrustedClock,
{
    pub fn new(clock: C) -> Self {
        Self { clock }
    }

    pub fn verify(
        &self,
        envelope: InputEnvelope,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
    ) -> Result<VerifiedInput, LocalRuntimeError> {
        if envelope.bytes.is_empty() || envelope.bytes.len() > MAX_INPUT_BYTES {
            return Err(LocalRuntimeError::InvalidInput("input size"));
        }
        let observed_payload = Digest32::of_bytes(&envelope.bytes);
        if observed_payload != envelope.payload_digest {
            return Err(LocalRuntimeError::InvalidInput("payload digest"));
        }
        if envelope.maximum_tokens == 0
            || envelope.maximum_tokens > MAX_TOKENS
            || envelope.maximum_tokens > grant.claims().maximum_tokens
            || envelope.maximum_tokens > manifest.claims().maximum_tokens
        {
            return Err(LocalRuntimeError::InvalidInput("token limit"));
        }
        let requested_memory = envelope
            .kv_memory_bytes
            .checked_add(envelope.transient_memory_bytes)
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
        if requested_memory > grant.claims().maximum_aggregate_memory_bytes {
            return Err(LocalRuntimeError::InvalidInput("request memory"));
        }
        if envelope.deadline_ms > grant.claims().expires_at_ms {
            return Err(LocalRuntimeError::InvalidInput("deadline exceeds grant"));
        }
        let now_ms = self.clock.unix_time_ms()?;
        if now_ms >= envelope.deadline_ms {
            return Err(LocalRuntimeError::Expired);
        }
        let delta_ms = envelope
            .deadline_ms
            .checked_sub(now_ms)
            .ok_or(LocalRuntimeError::Expired)?;
        let deadline = TrustedDeadline {
            instant: self.clock.monotonic_now() + Duration::from_millis(delta_ms),
            absolute_unix_ms: envelope.deadline_ms,
        };
        let semantic_digest = input_semantic_digest(&envelope);
        Ok(VerifiedInput {
            operation_id: envelope.operation_id,
            bytes: envelope.bytes,
            payload_digest: envelope.payload_digest,
            maximum_tokens: envelope.maximum_tokens,
            deadline,
            kv_memory_bytes: envelope.kv_memory_bytes,
            transient_memory_bytes: envelope.transient_memory_bytes,
            semantic_digest,
        })
    }
}

#[derive(Clone, Debug)]
pub struct TrustedDeadline {
    instant: Instant,
    absolute_unix_ms: u64,
}

impl TrustedDeadline {
    pub fn instant(&self) -> Instant {
        self.instant
    }

    pub fn absolute_unix_ms(&self) -> u64 {
        self.absolute_unix_ms
    }

    pub fn is_elapsed(&self) -> bool {
        Instant::now() >= self.instant
    }
}

#[derive(Debug)]
pub struct VerifiedInput {
    operation_id: StableId,
    bytes: Vec<u8>,
    payload_digest: Digest32,
    maximum_tokens: u32,
    deadline: TrustedDeadline,
    kv_memory_bytes: u64,
    transient_memory_bytes: u64,
    semantic_digest: Digest32,
}

impl VerifiedInput {
    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    pub fn maximum_tokens(&self) -> u32 {
        self.maximum_tokens
    }

    pub fn deadline(&self) -> &TrustedDeadline {
        &self.deadline
    }

    pub fn kv_memory_bytes(&self) -> u64 {
        self.kv_memory_bytes
    }

    pub fn transient_memory_bytes(&self) -> u64 {
        self.transient_memory_bytes
    }

    pub fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }
}

pub fn grant_semantic_digest(claims: &ResourceGrantClaims) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.local-resource-grant.v1");
    push_id(&mut bytes, &claims.issuer_id);
    push_id(&mut bytes, &claims.grant_id);
    push_id(&mut bytes, &claims.nonce);
    bytes.extend_from_slice(&claims.authority_epoch.to_be_bytes());
    push_id(&mut bytes, &claims.worker_subject);
    bytes.extend_from_slice(&claims.worker_generation.get().to_be_bytes());
    push_digest(&mut bytes, claims.model_digest);
    push_digest(&mut bytes, claims.weights_digest);
    push_digest(&mut bytes, claims.tokenizer_digest);
    push_digest(&mut bytes, claims.preprocessor_digest);
    push_digest(&mut bytes, claims.quantization_digest);
    push_digest(&mut bytes, claims.runtime_digest);
    push_id(&mut bytes, &claims.device_id);
    push_digest(&mut bytes, claims.artifact_descriptor_digest);
    bytes.extend_from_slice(&claims.maximum_aggregate_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(&u64::try_from(claims.maximum_concurrency).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(&claims.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&claims.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(&claims.revocation_revision.to_be_bytes());
    push_digest(&mut bytes, claims.revocation_head_digest);
    bytes.push(u8::from(claims.revoked));
    Digest32::of_bytes(&bytes)
}

pub fn manifest_semantic_digest(claims: &ModelManifestClaims) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.local-model-manifest.v1");
    push_id(&mut bytes, &claims.model_id);
    push_digest(&mut bytes, claims.model_digest);
    push_digest(&mut bytes, claims.weights_digest);
    push_digest(&mut bytes, claims.tokenizer_digest);
    push_digest(&mut bytes, claims.preprocessor_digest);
    push_digest(&mut bytes, claims.quantization_digest);
    push_digest(&mut bytes, claims.runtime_digest);
    push_id(&mut bytes, &claims.device_id);
    push_digest(&mut bytes, claims.artifact_descriptor_digest);
    bytes.extend_from_slice(&claims.expected_weight_bytes.to_be_bytes());
    bytes.extend_from_slice(&claims.maximum_tokens.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn input_semantic_digest(envelope: &InputEnvelope) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.local-model-input.v1");
    push_id(&mut bytes, &envelope.operation_id);
    push_digest(&mut bytes, envelope.payload_digest);
    bytes.extend_from_slice(&envelope.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&envelope.deadline_ms.to_be_bytes());
    bytes.extend_from_slice(&envelope.kv_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(&envelope.transient_memory_bytes.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn validate_grant_claims(claims: &ResourceGrantClaims) -> Result<(), LocalRuntimeError> {
    if claims.authority_epoch == 0
        || claims.worker_generation.get() == 0
        || claims.maximum_aggregate_memory_bytes == 0
        || claims.maximum_concurrency == 0
        || claims.maximum_tokens == 0
        || claims.maximum_tokens > MAX_TOKENS
        || claims.expires_at_ms == 0
        || claims.revocation_revision == 0
    {
        return Err(LocalRuntimeError::InvalidGrant("numeric bounds"));
    }
    for digest in [
        claims.model_digest,
        claims.weights_digest,
        claims.tokenizer_digest,
        claims.preprocessor_digest,
        claims.quantization_digest,
        claims.runtime_digest,
        claims.artifact_descriptor_digest,
        claims.revocation_head_digest,
        claims.semantic_digest,
    ] {
        if digest.is_zero() {
            return Err(LocalRuntimeError::InvalidGrant("zero digest"));
        }
    }
    Ok(())
}

fn validate_manifest(manifest: &ModelManifestClaims) -> Result<(), LocalRuntimeError> {
    if manifest.expected_weight_bytes == 0
        || manifest.maximum_tokens == 0
        || manifest.maximum_tokens > MAX_TOKENS
    {
        return Err(LocalRuntimeError::InvalidManifest("numeric bounds"));
    }
    for digest in [
        manifest.model_digest,
        manifest.weights_digest,
        manifest.tokenizer_digest,
        manifest.preprocessor_digest,
        manifest.quantization_digest,
        manifest.runtime_digest,
        manifest.artifact_descriptor_digest,
    ] {
        if digest.is_zero() {
            return Err(LocalRuntimeError::InvalidManifest("zero digest"));
        }
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
