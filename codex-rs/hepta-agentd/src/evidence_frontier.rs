//! Externally supplied signed recovery-frontier admission for kernel.evidence.
//!
//! The frontier and signer trust files must be supplied from outside Agent home,
//! run, workspace and fleet roots so restoring owner state cannot silently roll
//! them back as part of the same bundle. This path check does not establish
//! an independent failure domain or freshness if the whole host is rolled back.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SPKI_BYTES;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EvidenceRecoverySnapshotV3;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;

const MAX_FRONTIER_FILE_BYTES: u64 = 64 * 1024;
const MAX_FRONTIER_TRUST_FILE_BYTES: u64 = 8 * 1024;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;
const AUTHENTICATION_PROFILE: &str = "ml_dsa65_v2";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoveryFrontierV4 {
    pub schema_version: u32,
    pub authentication_profile: String,
    pub store_id: String,
    pub frontier_generation: u64,
    pub snapshot: EvidenceRecoverySnapshotV3,
    pub source_commit: String,
    pub source_tree: String,
    pub created_at_unix_ms: u64,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signer_public_key_id_hex: String,
    pub signature_hex: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRecoveryFrontierTrustV2 {
    schema_version: u32,
    authentication_profile: String,
    store_id: String,
    minimum_frontier_generation: u64,
    signer_principal_id: String,
    signer_key_epoch: u64,
    public_spki_hex: String,
    public_key_id_hex: String,
    revoked: bool,
}

impl EvidenceRecoveryFrontierV4 {
    fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != 4
            || self.authentication_profile != AUTHENTICATION_PROFILE
            || self.frontier_generation == 0
            || self.snapshot.schema_version != 3
            || self.snapshot.database_lineage != EVIDENCE_DATABASE_LINEAGE
        {
            return Err(invalid(
                "frontier schema, generation or database lineage is invalid",
            ));
        }
        StableId::new(self.store_id.clone())
            .map_err(|error| invalid(&format!("invalid recovery store id: {error}")))?;
        StableId::new(self.signer_principal_id.clone())
            .map_err(|error| invalid(&format!("invalid frontier signer principal: {error}")))?;
        Generation::new(self.signer_key_epoch)
            .map_err(|error| invalid(&format!("invalid frontier signer epoch: {error}")))?;
        validate_git_identity(&self.source_commit, "source commit")?;
        validate_git_identity(&self.source_tree, "source tree")?;
        let now = current_time_millis()?;
        if self.created_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS) {
            return Err(invalid("frontier creation time is too far in the future"));
        }
        let _: [u8; 32] = canonical_hex_bytes(&self.signer_public_key_id_hex)?;
        let _: [u8; ML_DSA_65_SIGNATURE_BYTES] = canonical_hex_bytes(&self.signature_hex)?;
        Ok(())
    }
}

pub fn evidence_recovery_frontier_signing_bytes(
    frontier: &EvidenceRecoveryFrontierV4,
) -> Result<Vec<u8>, AgentdError> {
    frontier.validate()?;
    let mut bytes = b"hepta.kernel.evidence.recovery-frontier.pq.v4\0".to_vec();
    push_part(&mut bytes, frontier.authentication_profile.as_bytes());
    push_part(&mut bytes, frontier.store_id.as_bytes());
    bytes.extend_from_slice(&frontier.frontier_generation.to_be_bytes());
    push_part(&mut bytes, frontier.snapshot.database_lineage.as_bytes());
    push_part(
        &mut bytes,
        frontier.snapshot.migration_set_sha256.as_str().as_bytes(),
    );
    bytes.extend_from_slice(&frontier.snapshot.qualification_max_seq.to_be_bytes());
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .qualification_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .authbus_replay_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    bytes.extend_from_slice(&frontier.snapshot.provider_effect_rows.to_be_bytes());
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .provider_effect_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    bytes.extend_from_slice(&frontier.snapshot.provider_invocation_rows.to_be_bytes());
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .provider_invocation_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    push_part(&mut bytes, frontier.source_commit.as_bytes());
    push_part(&mut bytes, frontier.source_tree.as_bytes());
    bytes.extend_from_slice(&frontier.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, frontier.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&frontier.signer_key_epoch.to_be_bytes());
    bytes.extend_from_slice(&canonical_hex_bytes::<32>(
        &frontier.signer_public_key_id_hex,
    )?);
    Ok(bytes)
}

pub(crate) struct VerifiedEvidenceRecoveryFrontier(EvidenceRecoveryFrontierV4);

/// Check shared evidence recovery before entry-point bootstrap owners can run.
/// This does not migrate the database, bind its store ID, or authorize effects.
/// `run` repeats the check and owns the later writable admission boundary.
pub async fn preflight_evidence_recovery(config: &AgentdConfig) -> Result<(), AgentdError> {
    load_evidence_recovery_for_config(config)?
        .check_existing_read_only(config.identity())
        .await
}

pub(crate) fn load_evidence_recovery_for_config(
    config: &AgentdConfig,
) -> Result<VerifiedEvidenceRecoveryFrontier, AgentdError> {
    let (frontier, trust) = config.evidence_recovery_frontier_files().ok_or_else(|| {
        recovery_required(
            "PQ recovery frontier and signer trust are required before Agentd startup",
        )
    })?;
    load_evidence_recovery_frontier(config.identity(), frontier, trust)
}

/// Authenticate external recovery authority before opening or migrating SQLite.
pub(crate) fn load_evidence_recovery_frontier(
    identity: &AgentdIdentity,
    frontier_file: &Path,
    signer_trust_file: &Path,
) -> Result<VerifiedEvidenceRecoveryFrontier, AgentdError> {
    let frontier_bytes = read_external_file(frontier_file, identity, MAX_FRONTIER_FILE_BYTES)?;
    let frontier: EvidenceRecoveryFrontierV4 =
        serde_json::from_slice(&frontier_bytes).map_err(|_| {
            recovery_required(
                "an ML-DSA-65 V4 checkpoint covering provider effects and invocations is required",
            )
        })?;
    frontier.validate()?;

    let trust_bytes =
        read_external_file(signer_trust_file, identity, MAX_FRONTIER_TRUST_FILE_BYTES)?;
    let trust: EvidenceRecoveryFrontierTrustV2 = serde_json::from_slice(&trust_bytes)?;
    if trust.schema_version != 2
        || trust.authentication_profile != AUTHENTICATION_PROFILE
        || trust.revoked
        || trust.store_id != frontier.store_id
        || trust.minimum_frontier_generation == 0
        || frontier.frontier_generation < trust.minimum_frontier_generation
        || trust.signer_principal_id != frontier.signer_principal_id
        || trust.signer_key_epoch != frontier.signer_key_epoch
        || trust.public_key_id_hex != frontier.signer_public_key_id_hex
    {
        return Err(recovery_required(
            "frontier signer trust, store scope or generation floor is revoked or mismatched",
        ));
    }
    StableId::new(trust.signer_principal_id.clone())
        .map_err(|error| invalid(&format!("invalid trusted frontier signer: {error}")))?;
    Generation::new(trust.signer_key_epoch)
        .map_err(|error| invalid(&format!("invalid trusted frontier epoch: {error}")))?;
    let verifying_key = PqNativeVerifier::from_pinned_spki(
        &canonical_hex_bytes::<ML_DSA_65_SPKI_BYTES>(&trust.public_spki_hex)?,
        canonical_hex_bytes::<32>(&trust.public_key_id_hex)?,
    )
    .map_err(|_| invalid("invalid trusted frontier ML-DSA-65 public key or key pin"))?;
    let signature = canonical_hex_bytes::<ML_DSA_65_SIGNATURE_BYTES>(&frontier.signature_hex)?;
    verifying_key
        .verify_exact_message(
            &evidence_recovery_frontier_signing_bytes(&frontier)?,
            &signature,
        )
        .map_err(|_| recovery_required("frontier signature verification failed"))?;

    Ok(VerifiedEvidenceRecoveryFrontier(frontier))
}

impl VerifiedEvidenceRecoveryFrontier {
    pub(crate) async fn open(
        self,
        identity: &AgentdIdentity,
    ) -> Result<HeptaEvidenceStore, AgentdError> {
        self.check_existing_read_only(identity).await?;
        let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
            &identity.home_root,
        )?);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .map_err(evidence_error)?;
        if let Err(error) = self.admit(&store).await {
            store.close().await;
            return Err(error);
        }
        Ok(store)
    }

    async fn check_existing_read_only(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        // A missing/old/partial image is not permission to initialize or migrate.
        // Bootstrap and migration must stage the exact image that the external
        // PQ recovery owner approved before ordinary Agentd startup.
        let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
            &identity.home_root,
        )?);
        let observed = HeptaEvidenceStore::open_existing_read_only(&sqlite)
            .await
            .map_err(evidence_error)?;
        let checked = self.check_snapshot(&observed).await;
        observed.close().await;
        checked
    }

    pub(crate) async fn admit(self, store: &HeptaEvidenceStore) -> Result<(), AgentdError> {
        self.check_snapshot(store).await?;
        store
            .bind_recovery_store_id(&self.0.store_id)
            .await
            .map_err(evidence_error)?;
        Ok(())
    }

    async fn check_snapshot(&self, store: &HeptaEvidenceStore) -> Result<(), AgentdError> {
        let frontier = &self.0;
        if let Some(existing_store_id) = store.recovery_store_id().await.map_err(evidence_error)?
            && existing_store_id != frontier.store_id
        {
            return Err(recovery_required(
                "frontier store id does not match the bound evidence database",
            ));
        }

        let actual = store.recovery_snapshot().await.map_err(evidence_error)?;
        if actual != frontier.snapshot {
            return Err(recovery_required(
                "local evidence/replay/effect/invocation frontier does not match the signed checkpoint",
            ));
        }
        Ok(())
    }
}

fn canonical_hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.bytes().any(|byte| byte.is_ascii_uppercase()) {
        return Err(invalid(
            "recovery hexadecimal fields must use lowercase encoding",
        ));
    }
    hex_bytes(value)
}

#[cfg(unix)]
fn read_external_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(invalid("recovery frontier files must use absolute paths"));
    }
    let canonical = path.canonicalize()?;
    let owned_roots = [
        canonical_owned_root(&identity.home_root)?,
        canonical_owned_root(&identity.run_root)?,
        canonical_owned_root(&identity.workspace)?,
        canonical_owned_root(&identity.fleet_root)?,
    ];
    if canonical != path || owned_roots.iter().any(|root| canonical.starts_with(root)) {
        return Err(invalid(
            "recovery frontier files must be canonical and outside Agent-owned home/run/workspace/fleet rollback domains",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > maximum_bytes
    {
        return Err(invalid(
            "recovery frontier files must be bounded, regular and not writable by group/other",
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
        return Err(invalid("recovery frontier file changed while opening"));
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
        return Err(invalid("recovery frontier file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn canonical_owned_root(path: &Path) -> Result<std::path::PathBuf, AgentdError> {
    use std::path::Component;

    if !path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::RootDir | Component::Normal(_)))
    {
        return Err(invalid("Agent-owned roots must be absolute and normalized"));
    }
    let mut ancestor = path;
    let mut missing = Vec::new();
    loop {
        match ancestor.canonicalize() {
            Ok(mut canonical) => {
                if !std::fs::metadata(&canonical)?.is_dir() {
                    return Err(invalid("Agent-owned root ancestor must be a directory"));
                }
                for part in missing.iter().rev() {
                    canonical.push(part);
                }
                return Ok(canonical);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                // Only a genuinely absent normal tail may be retained. Never
                // create it, or treat a dangling alias or access error as absent.
                match std::fs::symlink_metadata(ancestor) {
                    Ok(_) => return Err(invalid("Agent-owned root has an unresolved alias")),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
                let name = ancestor
                    .file_name()
                    .ok_or_else(|| invalid("Agent-owned root has no existing ancestor"))?;
                missing.push(name.to_os_string());
                ancestor = ancestor
                    .parent()
                    .ok_or_else(|| invalid("Agent-owned root has no existing ancestor"))?;
            }
            Err(error) => return Err(error.into()),
        }
    }
}

#[cfg(not(unix))]
fn read_external_file(
    _path: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the signed recovery-frontier profile currently requires Unix file identity checks",
    ))
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), AgentdError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(&format!(
            "{label} must be a 40- or 64-character lowercase hexadecimal object id"
        )));
    }
    Ok(())
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|error| invalid(&format!("system clock overflow: {error}")))
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError {
    recovery_required(&error.to_string())
}

fn recovery_required(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery_required: {message}"))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery: {message}"))
}

#[cfg(all(test, unix))]
#[path = "evidence_frontier_tests.rs"]
mod tests;
