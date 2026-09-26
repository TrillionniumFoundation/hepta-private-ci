//! Trusted-host bootstrap for the single cognitive production writer.
//!
//! The host consumes an independently retained signed current-cut manifest, a
//! signed live authority/revocation state, signer trust and a separately stored
//! opaque token. Every file is bounded, identity-checked and outside the Agent
//! rollback domain. The live verifier rereads authority state before each write.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveRecoveryAnchor;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::CognitiveScope;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::LedgerSourceKind;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryLifecycleState;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::MemoryVerification;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionCognitiveMutationReceiptV1;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_cognitive_store::bootstrap::COGNITIVE_BOOTSTRAP_SCHEMA_VERSION;
use codex_hepta_cognitive_store::bootstrap::CognitiveAuthorityStateV1;
use codex_hepta_cognitive_store::bootstrap::CognitiveBootstrapTrustV1;
use codex_hepta_cognitive_store::bootstrap::CognitiveProductionBootstrapV1;
use codex_hepta_cognitive_store::bootstrap::cognitive_authority_state_sha256;
use codex_hepta_cognitive_store::bootstrap::cognitive_authority_state_signing_bytes;
use codex_hepta_cognitive_store::bootstrap::cognitive_production_bootstrap_sha256;
use codex_hepta_cognitive_store::bootstrap::cognitive_production_bootstrap_signing_bytes;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Serialize;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdProductionWriterHost;
use crate::authbus_trust::hex_bytes;

const MAX_BOOTSTRAP_BYTES: u64 = 128 * 1024;
const MAX_AUTHORITY_STATE_BYTES: u64 = 64 * 1024;
const MAX_TRUST_BYTES: u64 = 8 * 1024;
const MAX_TOKEN_BYTES: u64 = 4 * 1024;
const BOOTSTRAP_RECEIPT_NAMESPACE: &str = "hepta.cognitive.bootstrap-receipt.v1";
const BOOTSTRAP_CANARY_NAMESPACE: &str = "hepta.cognitive.bootstrap-canary.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveProductionBootstrapFilesV1 {
    pub bootstrap_file: PathBuf,
    pub authority_state_file: PathBuf,
    pub signer_trust_file: PathBuf,
    pub authority_token_file: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CognitiveProductionBootstrapReceiptV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: AgentId,
    pub bootstrap_sha256: Sha256Digest,
    pub authority_state_sha256: Sha256Digest,
    pub recovered_state_sha256: Sha256Digest,
    pub lease_id: String,
    pub writer_generation: u64,
    pub rollback_generation_floor: u64,
    pub opened_at_unix_ms: u64,
    pub receipt_sha256: Sha256Digest,
}

impl CognitiveProductionBootstrapReceiptV1 {
    fn compute_receipt_sha256(&self) -> Sha256Digest {
        let mut bytes = b"hepta.cognitive.bootstrap-receipt.v1\0".to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        push_part(&mut bytes, self.namespace.as_bytes());
        push_part(&mut bytes, self.agent_id.as_str().as_bytes());
        push_digest(&mut bytes, &self.bootstrap_sha256);
        push_digest(&mut bytes, &self.authority_state_sha256);
        push_digest(&mut bytes, &self.recovered_state_sha256);
        push_part(&mut bytes, self.lease_id.as_bytes());
        bytes.extend_from_slice(&self.writer_generation.to_be_bytes());
        bytes.extend_from_slice(&self.rollback_generation_floor.to_be_bytes());
        bytes.extend_from_slice(&self.opened_at_unix_ms.to_be_bytes());
        Sha256Digest::for_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != COGNITIVE_BOOTSTRAP_SCHEMA_VERSION
            || self.namespace != BOOTSTRAP_RECEIPT_NAMESPACE
            || self.writer_generation == 0
            || self.rollback_generation_floor <= self.writer_generation
            || self.opened_at_unix_ms == 0
            || self.receipt_sha256 != self.compute_receipt_sha256()
        {
            return Err(invalid("stale or malformed cognitive bootstrap receipt"));
        }
        Ok(())
    }
}

pub struct CognitiveProductionBootstrapOutcomeV1 {
    host: Arc<AgentdProductionWriterHost>,
    manifest: CognitiveProductionBootstrapV1,
    authority_state: CognitiveAuthorityStateV1,
    receipt: CognitiveProductionBootstrapReceiptV1,
}

impl CognitiveProductionBootstrapOutcomeV1 {
    pub fn host(&self) -> Arc<AgentdProductionWriterHost> {
        Arc::clone(&self.host)
    }

    pub fn manifest(&self) -> &CognitiveProductionBootstrapV1 {
        &self.manifest
    }

    pub fn authority_state(&self) -> &CognitiveAuthorityStateV1 {
        &self.authority_state
    }

    pub fn receipt(&self) -> &CognitiveProductionBootstrapReceiptV1 {
        &self.receipt
    }

    pub fn into_host(self) -> Arc<AgentdProductionWriterHost> {
        self.host
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CognitiveBootstrapCanaryReceiptV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: AgentId,
    pub canary_id: String,
    pub memory_id: String,
    pub remembered_revision: u64,
    pub tombstone_revision: u64,
    pub remember_receipt_sha256: Sha256Digest,
    pub tombstone_receipt_sha256: Sha256Digest,
    pub before_state_sha256: Sha256Digest,
    pub after_state_sha256: Sha256Digest,
    pub completed_at_unix_ms: u64,
    pub receipt_sha256: Sha256Digest,
}

impl CognitiveBootstrapCanaryReceiptV1 {
    fn compute_receipt_sha256(&self) -> Sha256Digest {
        let mut bytes = b"hepta.cognitive.bootstrap-canary.v1\0".to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        push_part(&mut bytes, self.namespace.as_bytes());
        push_part(&mut bytes, self.agent_id.as_str().as_bytes());
        push_part(&mut bytes, self.canary_id.as_bytes());
        push_part(&mut bytes, self.memory_id.as_bytes());
        bytes.extend_from_slice(&self.remembered_revision.to_be_bytes());
        bytes.extend_from_slice(&self.tombstone_revision.to_be_bytes());
        push_digest(&mut bytes, &self.remember_receipt_sha256);
        push_digest(&mut bytes, &self.tombstone_receipt_sha256);
        push_digest(&mut bytes, &self.before_state_sha256);
        push_digest(&mut bytes, &self.after_state_sha256);
        bytes.extend_from_slice(&self.completed_at_unix_ms.to_be_bytes());
        Sha256Digest::for_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != COGNITIVE_BOOTSTRAP_SCHEMA_VERSION
            || self.namespace != BOOTSTRAP_CANARY_NAMESPACE
            || self.remembered_revision == 0
            || self.tombstone_revision != self.remembered_revision.saturating_add(1)
            || self.before_state_sha256 == self.after_state_sha256
            || self.completed_at_unix_ms == 0
            || self.receipt_sha256 != self.compute_receipt_sha256()
        {
            return Err(invalid("stale or malformed cognitive bootstrap canary receipt"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ObservedAuthorityState {
    revision: u64,
    digest: Sha256Digest,
}

struct LiveSignedCognitiveAuthorityVerifier {
    identity: AgentdIdentity,
    authority_state_file: PathBuf,
    signer_trust_file: PathBuf,
    expected_lease_id: String,
    expected_generation: u64,
    expected_token_sha256: Sha256Digest,
    expected_public_key_hex: String,
    observed: Mutex<ObservedAuthorityState>,
}

impl LiveSignedCognitiveAuthorityVerifier {
    fn verify_live(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), AgentdError> {
        let now = current_time_millis()?;
        let trust = load_trust(&self.identity, &self.signer_trust_file)?;
        if trust.revoked || trust.public_key_hex != self.expected_public_key_hex {
            return Err(fenced("cognitive authority signer trust is revoked or changed"));
        }
        let state = load_authority_state(
            &self.identity,
            &self.authority_state_file,
            &trust,
            now,
        )?;
        if &state.agent_id != expected_agent
            || state.agent_id != authority.agent_id
            || state.lease_id != self.expected_lease_id
            || state.writer_generation != self.expected_generation
            || state.token_sha256 != self.expected_token_sha256
            || state.grant_digest != authority.grant_digest
            || state.authority_epoch != authority.authority_epoch
            || state.owner_epoch != authority.owner_epoch
            || state.lease_expires_at_unix_seconds
                != authority.lease_expires_at_unix_seconds
        {
            return Err(fenced("live cognitive authority state no longer matches the opened writer"));
        }

        let digest = cognitive_authority_state_sha256(&state).map_err(contract_error)?;
        let mut observed = self
            .observed
            .lock()
            .map_err(|_| fenced("live cognitive authority state lock is poisoned"))?;
        match state.state_revision.cmp(&observed.revision) {
            std::cmp::Ordering::Less => {
                return Err(fenced("live cognitive authority state regressed"));
            }
            std::cmp::Ordering::Equal if digest != observed.digest => {
                return Err(fenced(
                    "live cognitive authority state changed without advancing revision",
                ));
            }
            std::cmp::Ordering::Equal => {}
            std::cmp::Ordering::Greater => {
                if state.state_revision != observed.revision.saturating_add(1)
                    || state.predecessor_state_sha256.as_ref() != Some(&observed.digest)
                {
                    return Err(fenced(
                        "live cognitive authority successor is not the exact next signed state",
                    ));
                }
                observed.revision = state.state_revision;
                observed.digest = digest;
            }
        }
        if state.revoked {
            return Err(fenced("live cognitive production authority is revoked"));
        }
        Ok(())
    }
}

impl ProductionAuthorityVerifier for LiveSignedCognitiveAuthorityVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self.verify_live(authority, expected_agent)
            .map_err(|error| error.to_string())
    }
}

pub async fn open_cognitive_production_host_from_signed_bootstrap(
    config: &AgentdConfig,
    files: &CognitiveProductionBootstrapFilesV1,
) -> Result<CognitiveProductionBootstrapOutcomeV1, AgentdError> {
    let now = current_time_millis()?;
    let identity = config.identity();
    let trust = load_trust(identity, &files.signer_trust_file)?;
    if trust.revoked {
        return Err(fenced("cognitive bootstrap signer is revoked"));
    }
    let bootstrap = load_bootstrap(identity, &files.bootstrap_file, &trust, now)?;
    let state = load_authority_state(identity, &files.authority_state_file, &trust, now)?;
    let state_digest = cognitive_authority_state_sha256(&state).map_err(contract_error)?;
    if bootstrap.agent_id != identity.agent_id
        || state.agent_id != identity.agent_id
        || bootstrap.authority_state_sha256 != state_digest
        || bootstrap.lease_id != state.lease_id
        || bootstrap.writer_generation != state.writer_generation
        || state.revoked
    {
        return Err(fenced(
            "signed cognitive bootstrap, authority state and Agent identity do not agree",
        ));
    }

    let token_bytes = read_external_file(
        &files.authority_token_file,
        identity,
        MAX_TOKEN_BYTES,
        true,
    )?;
    if Sha256Digest::for_bytes(&token_bytes) != state.token_sha256 {
        return Err(fenced("opaque cognitive authority token digest mismatch"));
    }
    let token = ProductionAuthorityToken::from_verified_bytes(token_bytes)?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        state.agent_id.clone(),
        state.grant_digest.clone(),
        state.authority_epoch,
        state.owner_epoch,
        state.lease_expires_at_unix_seconds,
        token,
    )?;
    let verifier = Arc::new(LiveSignedCognitiveAuthorityVerifier {
        identity: identity.clone(),
        authority_state_file: files.authority_state_file.clone(),
        signer_trust_file: files.signer_trust_file.clone(),
        expected_lease_id: state.lease_id.clone(),
        expected_generation: state.writer_generation,
        expected_token_sha256: state.token_sha256.clone(),
        expected_public_key_hex: trust.public_key_hex.clone(),
        observed: Mutex::new(ObservedAuthorityState {
            revision: state.state_revision,
            digest: state_digest.clone(),
        }),
    });
    verifier.verify_live(&authority, &identity.agent_id)?;
    let trait_verifier: Arc<dyn ProductionAuthorityVerifier> = verifier;
    let host = Arc::new(
        AgentdProductionWriterHost::open_with_recovery(
            config,
            CognitiveRecoveryRequirement::ExactCurrentCut(&bootstrap.recovery_anchor),
            authority,
            trait_verifier,
            bootstrap.lease_id.clone(),
            bootstrap.writer_generation,
        )
        .await?,
    );
    let recovered = host.writer().recovery_anchor().await?;
    if recovered != bootstrap.recovery_anchor {
        return Err(fenced(
            "recovered cognitive generation differs from the signed current cut",
        ));
    }

    let mut receipt = CognitiveProductionBootstrapReceiptV1 {
        schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
        namespace: BOOTSTRAP_RECEIPT_NAMESPACE.to_string(),
        agent_id: identity.agent_id.clone(),
        bootstrap_sha256: cognitive_production_bootstrap_sha256(&bootstrap)
            .map_err(contract_error)?,
        authority_state_sha256: state_digest,
        recovered_state_sha256: recovered.state_digest,
        lease_id: bootstrap.lease_id.clone(),
        writer_generation: bootstrap.writer_generation,
        rollback_generation_floor: bootstrap.rollback_generation_floor,
        opened_at_unix_ms: now,
        receipt_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    receipt.receipt_sha256 = receipt.compute_receipt_sha256();
    receipt.validate()?;
    Ok(CognitiveProductionBootstrapOutcomeV1 {
        host,
        manifest: bootstrap,
        authority_state: state,
        receipt,
    })
}

pub async fn execute_cognitive_bootstrap_canary(
    outcome: &CognitiveProductionBootstrapOutcomeV1,
) -> Result<CognitiveBootstrapCanaryReceiptV1, AgentdError> {
    let manifest = outcome.manifest();
    let host = outcome.host();
    let before = host.writer().recovery_anchor().await?;
    let now_seconds = current_time_millis()? / 1000;
    let observed_at = i64::try_from(now_seconds)
        .map_err(|_| invalid("current time exceeds signed cognitive record range"))?;
    let scope = CognitiveScope::AgentPrivate;
    let access = CognitiveAccess::agent_private(manifest.agent_id.clone());
    let content = format!("Hepta cognitive production bootstrap canary {}", manifest.canary_id);
    let source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("cognitive-bootstrap-canary:{}:remember", manifest.canary_id),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: observed_at,
    };
    let draft = MemoryDraft {
        stable_key: format!("cognitive-bootstrap-canary-{}", manifest.canary_id),
        revision: MemoryRevisionDraft {
            scope: scope.clone(),
            content,
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: observed_at,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    let remembered = host
        .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
        .await?;
    remembered.validate()?;

    let memory_id = remembered.write.memory.id.memory_id.clone();
    let remembered_revision = remembered.write.memory.id.revision;
    let reason = format!(
        "Hepta cognitive production bootstrap canary {} completed",
        manifest.canary_id
    );
    let forget_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("cognitive-bootstrap-canary:{}:forget", manifest.canary_id),
        content: reason.as_bytes().to_vec(),
        observed_at_unix_seconds: observed_at,
    };
    let forget = ForgetMemoryDraft {
        scope,
        reason,
        valid_from_unix_seconds: observed_at,
        citations: Vec::new(),
    };
    let tombstoned = host
        .forget_with_kg(
            &access,
            &memory_id,
            remembered_revision,
            &forget_source,
            &forget,
        )
        .await?;
    tombstoned.validate()?;
    let after = host.writer().recovery_anchor().await?;

    let mut receipt = CognitiveBootstrapCanaryReceiptV1 {
        schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
        namespace: BOOTSTRAP_CANARY_NAMESPACE.to_string(),
        agent_id: manifest.agent_id.clone(),
        canary_id: manifest.canary_id.clone(),
        memory_id: memory_id.as_str().to_string(),
        remembered_revision,
        tombstone_revision: tombstoned.write.memory.id.revision,
        remember_receipt_sha256: remembered.receipt_sha256,
        tombstone_receipt_sha256: tombstoned.receipt_sha256,
        before_state_sha256: before.state_digest,
        after_state_sha256: after.state_digest,
        completed_at_unix_ms: current_time_millis()?,
        receipt_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    receipt.receipt_sha256 = receipt.compute_receipt_sha256();
    receipt.validate()?;
    Ok(receipt)
}

fn load_trust(
    identity: &AgentdIdentity,
    path: &Path,
) -> Result<CognitiveBootstrapTrustV1, AgentdError> {
    let bytes = read_external_file(path, identity, MAX_TRUST_BYTES, false)?;
    let trust: CognitiveBootstrapTrustV1 = serde_json::from_slice(&bytes)?;
    trust.validate().map_err(contract_error)?;
    Ok(trust)
}

fn load_bootstrap(
    identity: &AgentdIdentity,
    path: &Path,
    trust: &CognitiveBootstrapTrustV1,
    now_unix_ms: u64,
) -> Result<CognitiveProductionBootstrapV1, AgentdError> {
    let bytes = read_external_file(path, identity, MAX_BOOTSTRAP_BYTES, false)?;
    let bootstrap: CognitiveProductionBootstrapV1 = serde_json::from_slice(&bytes)?;
    bootstrap.validate_at(now_unix_ms).map_err(contract_error)?;
    verify_signed_bytes(
        trust,
        &bootstrap.signer_principal_id,
        bootstrap.signer_key_epoch,
        &bootstrap.signature_hex,
        &cognitive_production_bootstrap_signing_bytes(&bootstrap).map_err(contract_error)?,
    )?;
    Ok(bootstrap)
}

fn load_authority_state(
    identity: &AgentdIdentity,
    path: &Path,
    trust: &CognitiveBootstrapTrustV1,
    now_unix_ms: u64,
) -> Result<CognitiveAuthorityStateV1, AgentdError> {
    let bytes = read_external_file(path, identity, MAX_AUTHORITY_STATE_BYTES, false)?;
    let state: CognitiveAuthorityStateV1 = serde_json::from_slice(&bytes)?;
    state.validate_at(now_unix_ms).map_err(contract_error)?;
    verify_signed_bytes(
        trust,
        &state.signer_principal_id,
        state.signer_key_epoch,
        &state.signature_hex,
        &cognitive_authority_state_signing_bytes(&state).map_err(contract_error)?,
    )?;
    Ok(state)
}

fn verify_signed_bytes(
    trust: &CognitiveBootstrapTrustV1,
    signer_principal_id: &str,
    signer_key_epoch: u64,
    signature_hex: &str,
    signing_bytes: &[u8],
) -> Result<(), AgentdError> {
    if trust.revoked
        || trust.signer_principal_id != signer_principal_id
        || trust.signer_key_epoch != signer_key_epoch
    {
        return Err(fenced("cognitive bootstrap signer trust mismatch"));
    }
    let verifying_key = VerifyingKey::from_bytes(&hex_bytes(&trust.public_key_hex)?)
        .map_err(|_| invalid("invalid cognitive bootstrap Ed25519 public key"))?;
    let signature = Signature::from_bytes(&hex_bytes(signature_hex)?);
    verifying_key
        .verify_strict(signing_bytes, &signature)
        .map_err(|_| fenced("cognitive bootstrap signature verification failed"))
}

#[cfg(unix)]
fn read_external_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
    secret: bool,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(invalid("cognitive bootstrap files must use absolute paths"));
    }
    let canonical = path.canonicalize()?;
    let home = identity.home_root.canonicalize()?;
    let fleet = Path::new(&identity.fleet_root).canonicalize()?;
    if canonical != path || canonical.starts_with(&home) || canonical.starts_with(&fleet) {
        return Err(invalid(
            "cognitive bootstrap files must be canonical and outside the Agent/fleet rollback domain",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    let forbidden_mode = if secret { 0o077 } else { 0o022 };
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & forbidden_mode != 0
        || before.len() == 0
        || before.len() > maximum_bytes
    {
        return Err(invalid(
            "cognitive bootstrap file permissions, identity or size are invalid",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity_tuple = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity_tuple(&opened) != identity_tuple(&before) {
        return Err(fenced("cognitive bootstrap file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(fenced("cognitive bootstrap file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_external_file(
    _path: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
    _secret: bool,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "signed cognitive production bootstrap currently requires Unix file identity checks",
    ))
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|error| invalid(&format!("system clock overflow: {error}")))
}

fn contract_error(error: impl std::fmt::Display) -> AgentdError {
    invalid(&format!("cognitive bootstrap contract: {error}"))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("cognitive production bootstrap: {message}"))
}

fn fenced(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(format!("cognitive production bootstrap: {message}"))
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn push_digest(bytes: &mut Vec<u8>, digest: &Sha256Digest) {
    push_part(bytes, digest.as_str().as_bytes());
}
