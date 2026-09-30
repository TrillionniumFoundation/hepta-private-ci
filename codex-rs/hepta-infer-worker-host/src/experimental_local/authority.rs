use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use super::LocalWorkerError;
use super::digest;
use super::validate_digest;
use super::validate_identity;

const GRANT_SCHEMA_VERSION: u32 = 1;
const MAX_CONFIG_BYTES: usize = 64 * 1024;
const MAX_LOCAL_INPUT_BYTES: usize = 16 * 1024 * 1024;
const MAX_LOCAL_TOKENS: u32 = 1_000_000;

pub trait TrustedClock: Send + Sync {
    fn now_ms(&self) -> Result<u64, LocalWorkerError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemTrustedClock;

impl TrustedClock for SystemTrustedClock {
    fn now_ms(&self) -> Result<u64, LocalWorkerError> {
        let duration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| LocalWorkerError::InvalidGrant("trusted clock before Unix epoch"))?;
        u64::try_from(duration.as_millis()).map_err(|_| LocalWorkerError::ArithmeticOverflow)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceGrantClaims {
    pub schema_version: u32,
    pub issuer: String,
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
    pub device_uuid: String,
    pub device_lease_digest: String,
    pub device_epoch: u64,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_concurrency: u32,
    pub maximum_tokens: u32,
    pub maximum_usage_units: u64,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: String,
    pub semantic_digest: String,
}

impl ResourceGrantClaims {
    pub(crate) fn signing_bytes(&self) -> Result<Vec<u8>, LocalWorkerError> {
        let mut bytes = b"hepta.local-resource-grant.v1\0".to_vec();
        bytes.extend_from_slice(
            &serde_json::to_vec(self)
                .map_err(|_| LocalWorkerError::InvalidGrant("grant encoding"))?,
        );
        Ok(bytes)
    }

    fn expected_semantic_digest(&self) -> Result<String, LocalWorkerError> {
        let mut semantic = self.clone();
        semantic.semantic_digest.clear();
        let encoded = serde_json::to_vec(&semantic)
            .map_err(|_| LocalWorkerError::InvalidGrant("grant semantic encoding"))?;
        Ok(digest(&encoded))
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
pub struct TrustedRevocationFrontier {
    pub authority_epoch: u64,
    pub revision: u64,
    pub head_digest: String,
    pub revoked_grant_ids: BTreeSet<String>,
}

impl TrustedRevocationFrontier {
    fn expected_head_digest(&self) -> Result<String, LocalWorkerError> {
        let encoded = serde_json::to_vec(&(
            "hepta.local-resource-revocations.v1",
            self.authority_epoch,
            self.revision,
            &self.revoked_grant_ids,
        ))
        .map_err(|_| LocalWorkerError::InvalidGrant("revocation encoding"))?;
        Ok(digest(&encoded))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceGrantVerifierConfig {
    expected_issuer: String,
    verifying_key: [u8; 32],
    frontier: TrustedRevocationFrontier,
}

pub struct ResourceGrantVerifier {
    expected_issuer: String,
    verifying_key: VerifyingKey,
    frontier: TrustedRevocationFrontier,
}

impl ResourceGrantVerifier {
    /// Open a verifier only from a protected owner/root configuration. There is
    /// intentionally no public constructor from arbitrary in-memory key bytes.
    pub fn open(path: &Path) -> Result<Self, LocalWorkerError> {
        let config: ResourceGrantVerifierConfig =
            serde_json::from_slice(&read_private_config(path)?)
                .map_err(|_| LocalWorkerError::InvalidGrant("verifier configuration"))?;
        Self::from_trusted_parts(
            config.expected_issuer,
            config.verifying_key,
            config.frontier,
        )
    }

    pub(crate) fn from_trusted_parts(
        expected_issuer: String,
        verifying_key: [u8; 32],
        frontier: TrustedRevocationFrontier,
    ) -> Result<Self, LocalWorkerError> {
        validate_identity(&expected_issuer, "resource grant issuer")?;
        if frontier.authority_epoch == 0 || frontier.revision == 0 {
            return Err(LocalWorkerError::InvalidGrant("authority frontier"));
        }
        validate_digest(&frontier.head_digest, "revocation head")?;
        if frontier.expected_head_digest()? != frontier.head_digest {
            return Err(LocalWorkerError::InvalidGrant(
                "revocation head semantic digest",
            ));
        }
        for grant_id in &frontier.revoked_grant_ids {
            validate_identity(grant_id, "revoked grant")?;
        }
        let verifying_key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| LocalWorkerError::InvalidGrant("verifying key"))?;
        Ok(Self {
            expected_issuer,
            verifying_key,
            frontier,
        })
    }

    pub fn verify<C: TrustedClock>(
        &self,
        signed: SignedResourceGrant,
        clock: &C,
    ) -> Result<VerifiedResourceGrant, LocalWorkerError> {
        validate_claims(&signed.claims)?;
        if signed.claims.issuer != self.expected_issuer {
            return Err(LocalWorkerError::InvalidGrant("issuer mismatch"));
        }
        if signed.claims.authority_epoch != self.frontier.authority_epoch
            || signed.claims.revocation_revision != self.frontier.revision
            || signed.claims.revocation_head_digest != self.frontier.head_digest
        {
            return Err(LocalWorkerError::StaleAuthorityFrontier);
        }
        if self
            .frontier
            .revoked_grant_ids
            .contains(&signed.claims.grant_id)
        {
            return Err(LocalWorkerError::GrantRevoked);
        }
        if signed.claims.expected_semantic_digest()? != signed.claims.semantic_digest {
            return Err(LocalWorkerError::InvalidGrant("semantic digest mismatch"));
        }
        let signature_bytes: [u8; 64] = signed
            .signature
            .as_slice()
            .try_into()
            .map_err(|_| LocalWorkerError::InvalidSignature)?;
        let signing_bytes = signed.claims.signing_bytes()?;
        self.verifying_key
            .verify_strict(&signing_bytes, &Signature::from_bytes(&signature_bytes))
            .map_err(|_| LocalWorkerError::InvalidSignature)?;
        let now_ms = clock.now_ms()?;
        if now_ms < signed.claims.issued_at_ms {
            return Err(LocalWorkerError::GrantNotYetValid);
        }
        if now_ms >= signed.claims.expires_at_ms {
            return Err(LocalWorkerError::GrantExpired);
        }
        let mut witness = b"hepta.verified-local-resource-grant.v1\0".to_vec();
        witness.extend_from_slice(&signing_bytes);
        witness.extend_from_slice(&signature_bytes);
        witness.extend_from_slice(self.frontier.head_digest.as_bytes());
        Ok(VerifiedResourceGrant {
            claims: signed.claims,
            witness_digest: digest(&witness),
        })
    }
}

fn validate_claims(claims: &ResourceGrantClaims) -> Result<(), LocalWorkerError> {
    if claims.schema_version != GRANT_SCHEMA_VERSION {
        return Err(LocalWorkerError::InvalidGrant("schema version"));
    }
    for (value, field) in [
        (&claims.issuer, "resource grant issuer"),
        (&claims.grant_id, "resource grant id"),
        (&claims.nonce, "resource grant nonce"),
        (&claims.worker_subject, "resource grant subject"),
        (&claims.model_id, "resource grant model"),
        (&claims.device_uuid, "resource grant device"),
    ] {
        validate_identity(value, field)?;
    }
    for (value, field) in [
        (&claims.model_digest, "resource grant model digest"),
        (&claims.weights_digest, "resource grant weights digest"),
        (&claims.tokenizer_digest, "resource grant tokenizer digest"),
        (
            &claims.preprocessor_digest,
            "resource grant preprocessor digest",
        ),
        (
            &claims.quantization_digest,
            "resource grant quantization digest",
        ),
        (&claims.runtime_digest, "resource grant runtime digest"),
        (
            &claims.device_lease_digest,
            "resource grant device lease digest",
        ),
        (
            &claims.revocation_head_digest,
            "resource grant revocation head",
        ),
        (&claims.semantic_digest, "resource grant semantic digest"),
    ] {
        validate_digest(value, field)?;
    }
    if claims.authority_epoch == 0
        || claims.worker_generation == 0
        || claims.device_epoch == 0
        || claims.maximum_aggregate_memory_bytes == 0
        || !(1..=256).contains(&claims.maximum_concurrency)
        || claims.maximum_tokens == 0
        || claims.maximum_tokens > MAX_LOCAL_TOKENS
        || claims.maximum_usage_units == 0
        || claims.issued_at_ms >= claims.expires_at_ms
        || claims.revocation_revision == 0
    {
        return Err(LocalWorkerError::InvalidGrant("invalid bounds"));
    }
    Ok(())
}

#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    claims: ResourceGrantClaims,
    witness_digest: String,
}

impl VerifiedResourceGrant {
    pub fn claims(&self) -> &ResourceGrantClaims {
        &self.claims
    }

    pub fn witness_digest(&self) -> &str {
        &self.witness_digest
    }

    pub fn worker_subject(&self) -> &str {
        &self.claims.worker_subject
    }

    pub fn worker_generation(&self) -> u64 {
        self.claims.worker_generation
    }

    pub fn maximum_aggregate_memory_bytes(&self) -> u64 {
        self.claims.maximum_aggregate_memory_bytes
    }

    pub fn maximum_concurrency(&self) -> u32 {
        self.claims.maximum_concurrency
    }

    pub fn maximum_tokens(&self) -> u32 {
        self.claims.maximum_tokens
    }

    pub fn device_epoch(&self) -> u64 {
        self.claims.device_epoch
    }

    pub(super) fn ensure_current<C: TrustedClock>(
        &self,
        clock: &C,
        worker_subject: &str,
        worker_generation: u64,
    ) -> Result<(), LocalWorkerError> {
        if self.claims.worker_subject != worker_subject
            || self.claims.worker_generation != worker_generation
        {
            return Err(LocalWorkerError::InvalidGrant("worker binding"));
        }
        let now_ms = clock.now_ms()?;
        if now_ms < self.claims.issued_at_ms {
            return Err(LocalWorkerError::GrantNotYetValid);
        }
        if now_ms >= self.claims.expires_at_ms {
            return Err(LocalWorkerError::GrantExpired);
        }
        Ok(())
    }

    pub fn bind_deadline<C: TrustedClock>(
        &self,
        clock: &C,
        requested_deadline_ms: u64,
    ) -> Result<TrustedDeadline, LocalWorkerError> {
        let now_ms = clock.now_ms()?;
        let deadline_ms = requested_deadline_ms.min(self.claims.expires_at_ms);
        if deadline_ms <= now_ms {
            return Err(LocalWorkerError::DeadlineExpired);
        }
        Ok(TrustedDeadline { deadline_ms })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TrustedDeadline {
    deadline_ms: u64,
}

impl TrustedDeadline {
    pub fn as_millis(self) -> u64 {
        self.deadline_ms
    }

    pub fn is_expired<C: TrustedClock>(self, clock: &C) -> Result<bool, LocalWorkerError> {
        Ok(clock.now_ms()? >= self.deadline_ms)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalModelManifest {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_uuid: String,
    pub device_lease_digest: String,
    pub expected_resident_memory_bytes: u64,
    pub semantic_digest: String,
}

impl LocalModelManifest {
    fn expected_semantic_digest(&self) -> Result<String, LocalWorkerError> {
        let mut semantic = self.clone();
        semantic.semantic_digest.clear();
        let encoded = serde_json::to_vec(&semantic)
            .map_err(|_| LocalWorkerError::InvalidManifest("manifest encoding"))?;
        Ok(digest(&encoded))
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedModelManifest {
    manifest: LocalModelManifest,
}

impl VerifiedModelManifest {
    pub fn verify(
        grant: &VerifiedResourceGrant,
        manifest: LocalModelManifest,
    ) -> Result<Self, LocalWorkerError> {
        validate_identity(&manifest.model_id, "local model id")?;
        validate_identity(&manifest.device_uuid, "local model device")?;
        for (value, field) in [
            (&manifest.model_digest, "local model digest"),
            (&manifest.weights_digest, "local weights digest"),
            (&manifest.tokenizer_digest, "local tokenizer digest"),
            (&manifest.preprocessor_digest, "local preprocessor digest"),
            (&manifest.quantization_digest, "local quantization digest"),
            (&manifest.runtime_digest, "local runtime digest"),
            (&manifest.device_lease_digest, "local device lease digest"),
            (&manifest.semantic_digest, "local manifest semantic digest"),
        ] {
            validate_digest(value, field)?;
        }
        if manifest.expected_resident_memory_bytes == 0
            || manifest.expected_resident_memory_bytes > grant.claims.maximum_aggregate_memory_bytes
        {
            return Err(LocalWorkerError::InvalidManifest("memory bound"));
        }
        if manifest.expected_semantic_digest()? != manifest.semantic_digest {
            return Err(LocalWorkerError::InvalidManifest(
                "semantic digest mismatch",
            ));
        }
        let claims = &grant.claims;
        if manifest.model_id != claims.model_id
            || manifest.model_digest != claims.model_digest
            || manifest.weights_digest != claims.weights_digest
            || manifest.tokenizer_digest != claims.tokenizer_digest
            || manifest.preprocessor_digest != claims.preprocessor_digest
            || manifest.quantization_digest != claims.quantization_digest
            || manifest.runtime_digest != claims.runtime_digest
            || manifest.device_uuid != claims.device_uuid
            || manifest.device_lease_digest != claims.device_lease_digest
        {
            return Err(LocalWorkerError::InvalidManifest("grant tuple mismatch"));
        }
        Ok(Self { manifest })
    }

    pub fn as_manifest(&self) -> &LocalModelManifest {
        &self.manifest
    }

    pub fn model_id(&self) -> &str {
        &self.manifest.model_id
    }

    pub fn semantic_digest(&self) -> &str {
        &self.manifest.semantic_digest
    }

    pub fn expected_resident_memory_bytes(&self) -> u64 {
        self.manifest.expected_resident_memory_bytes
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedInput {
    bytes: Arc<[u8]>,
    digest: String,
}

impl VerifiedInput {
    pub fn verify(
        bytes: Vec<u8>,
        expected_digest: &str,
        maximum_bytes: usize,
    ) -> Result<Self, LocalWorkerError> {
        validate_digest(expected_digest, "local input digest")?;
        if maximum_bytes == 0
            || maximum_bytes > MAX_LOCAL_INPUT_BYTES
            || bytes.is_empty()
            || bytes.len() > maximum_bytes
        {
            return Err(LocalWorkerError::InvalidInput("input bound"));
        }
        let observed = digest(&bytes);
        if observed != expected_digest {
            return Err(LocalWorkerError::InvalidInput("input digest mismatch"));
        }
        Ok(Self {
            bytes: Arc::from(bytes),
            digest: observed,
        })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }
}

#[cfg(unix)]
fn read_private_config(path: &Path) -> Result<Vec<u8>, LocalWorkerError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute() {
        return Err(LocalWorkerError::InvalidGrant(
            "verifier config path must be absolute",
        ));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| LocalWorkerError::Driver(error.to_string()))?;
    let metadata = file
        .metadata()
        .map_err(|error| LocalWorkerError::Driver(error.to_string()))?;
    let effective_uid = rustix::process::geteuid().as_raw();
    if !metadata.is_file()
        || metadata.mode() & 0o022 != 0
        || metadata.nlink() != 1
        || (metadata.uid() != 0 && metadata.uid() != effective_uid)
    {
        return Err(LocalWorkerError::InvalidGrant(
            "verifier config must be a protected root/owner regular file",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(
            u64::try_from(MAX_CONFIG_BYTES + 1)
                .map_err(|_| LocalWorkerError::ArithmeticOverflow)?,
        )
        .read_to_end(&mut bytes)
        .map_err(|error| LocalWorkerError::Driver(error.to_string()))?;
    if bytes.len() > MAX_CONFIG_BYTES {
        return Err(LocalWorkerError::InvalidGrant(
            "verifier config exceeds 64 KiB",
        ));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_config(_path: &Path) -> Result<Vec<u8>, LocalWorkerError> {
    Err(LocalWorkerError::InvalidGrant(
        "local resource grant verifier configuration requires Unix",
    ))
}
