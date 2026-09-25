//! Deployment-pinned, root-authenticated bootstrap for the current product host.
//!
//! The descriptor carries public verification material and immutable selection
//! pins only. It never carries signing keys, model bytes, scorer implementation,
//! RNG state, or per-request evidence. Every request is still revalidated against
//! the signed current-owner authority file by the product runner.

use std::io::Read;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIntuitionPolicyHostV2;
use crate::AgentdIntuitionPolicyPinsV2;

const MAX_BOOTSTRAP_BYTES: u64 = 1_048_576;
const BOOTSTRAP_SCHEMA_VERSION: u32 = 1;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct IntuitionPolicyBootstrapFileV1 {
    schema_version: u32,
    agent_id: String,
    spawn_generation: u64,
    owner_implementation_digest: String,
    revocation_frontier_digest: String,
    selected_profile_digest: String,
    policy_generation: u64,
    model_artifact_digest: String,
    scorer_contract_digest: String,
    rng_owner_digest: Option<String>,
    root: LearningTrustRootFileV1,
    distribution: SignedLearningTrustDistributionFileV1,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LearningTrustRootFileV1 {
    root_id: String,
    scope_digest: String,
    verifying_key: Vec<u8>,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignedLearningTrustDistributionFileV1 {
    distribution_id: String,
    generation: u64,
    effective_at: u64,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    signers: Vec<TrustedLearningSignerFileV1>,
    root_id: String,
    issued_at: u64,
    expires_at: u64,
    signature: Vec<u8>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TrustedLearningSignerFileV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
    controller_id: String,
    verifying_key: Vec<u8>,
    roles: Vec<String>,
    revoked_at: Option<u64>,
}

/// Load a deployment-pinned descriptor; its hash must come from trusted host configuration.
/// Descriptor bytes, including identity, selection and root public key, cannot choose this pin.
pub fn load_intuition_policy_bootstrap_v1(
    path: &Path,
    expected_digest: Digest32,
    agent_id: AgentId,
    spawn_generation: u64,
    now: u64,
) -> Result<Arc<AgentdIntuitionPolicyHostV2>, AgentdError> {
    validate_bootstrap_path(path)?;
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let source = options
        .open(path)
        .map_err(|error| AgentdError::Invalid(format!("open intuition bootstrap: {error}")))?;
    let metadata = source
        .metadata()
        .map_err(|error| AgentdError::Invalid(format!("stat open intuition bootstrap: {error}")))?;
    if !metadata.is_file() {
        return Err(AgentdError::Invalid(
            "intuition bootstrap is not a regular file".into(),
        ));
    }
    validate_bootstrap_permissions(&metadata)?;
    let mut bytes = Vec::new();
    source
        .take(MAX_BOOTSTRAP_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| AgentdError::Invalid(format!("read intuition bootstrap: {error}")))?;
    if bytes.len() as u64 > MAX_BOOTSTRAP_BYTES
        || expected_digest.is_zero()
        || Digest32::of_bytes(&bytes) != expected_digest
    {
        return Err(AgentdError::Invalid(
            "intuition bootstrap digest or size mismatch".into(),
        ));
    }
    let file: IntuitionPolicyBootstrapFileV1 = serde_json::from_slice(&bytes)
        .map_err(|error| AgentdError::Invalid(format!("decode intuition bootstrap: {error}")))?;
    if file.schema_version != BOOTSTRAP_SCHEMA_VERSION
        || file.agent_id != agent_id.to_string()
        || file.spawn_generation != spawn_generation
    {
        return Err(AgentdError::Invalid(
            "unsupported intuition bootstrap schema".to_string(),
        ));
    }

    let root = LearningTrustRootV1 {
        root_id: stable_id(&file.root.root_id, "root id")?,
        scope_digest: digest(&file.root.scope_digest, "root scope")?,
        verifying_key: fixed_bytes::<32>(&file.root.verifying_key, "root verifying key")?,
        valid_from: file.root.valid_from,
        expires_at: file.root.expires_at,
        revoked_at: file.root.revoked_at,
    };
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest(&file.distribution.scope_digest, "distribution scope")?,
        objective_digest: digest(
            &file.distribution.objective_digest,
            "distribution objective",
        )?,
        authority_epoch: file.distribution.authority_epoch,
        signers: file
            .distribution
            .signers
            .into_iter()
            .map(parse_signer)
            .collect::<Result<Vec<_>, _>>()?,
    };
    let signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: stable_id(&file.distribution.distribution_id, "distribution id")?,
            generation: file.distribution.generation,
            effective_at: file.distribution.effective_at,
            trust,
        },
        root_id: stable_id(&file.distribution.root_id, "distribution root id")?,
        issued_at: file.distribution.issued_at,
        expires_at: file.distribution.expires_at,
        signature: fixed_bytes::<64>(&file.distribution.signature, "distribution signature")?,
    };
    let activated = activate_learning_trust(&root, signed, None, now)
        .map_err(|error| AgentdError::Invalid(format!("activate intuition trust: {error}")))?;
    let pins = AgentdIntuitionPolicyPinsV2 {
        selected_profile_digest: digest(&file.selected_profile_digest, "selected profile digest")?,
        owner_implementation_digest: digest(
            &file.owner_implementation_digest,
            "owner implementation",
        )?,
        policy_generation: file.policy_generation,
        model_artifact_digest: digest(&file.model_artifact_digest, "model artifact digest")?,
        scorer_contract_digest: digest(&file.scorer_contract_digest, "scorer contract digest")?,
        rng_owner_digest: file
            .rng_owner_digest
            .as_deref()
            .map(|value| digest(value, "rng owner digest"))
            .transpose()?,
        trust_distribution_digest: activated.distribution_digest(),
        revocation_frontier_digest: digest(
            &file.revocation_frontier_digest,
            "selected revocation frontier",
        )?,
    };
    AgentdIntuitionPolicyHostV2::new(agent_id, spawn_generation, Arc::new(activated), pins)
        .map(Arc::new)
        .map_err(|error| AgentdError::Invalid(error.to_string()))
}

fn parse_signer(
    value: TrustedLearningSignerFileV1,
) -> Result<TrustedLearningSignerV1, AgentdError> {
    Ok(TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: stable_id(&value.principal_id, "principal id")?,
            credential_chain_digest: digest(
                &value.credential_chain_digest,
                "credential chain digest",
            )?,
            signing_key_digest: digest(&value.signing_key_digest, "signing key digest")?,
            scope_digest: digest(&value.scope_digest, "principal scope")?,
            authority_epoch: value.authority_epoch,
            authenticated_at: value.authenticated_at,
            expires_at: value.expires_at,
        },
        controller_id: stable_id(&value.controller_id, "controller id")?,
        verifying_key: fixed_bytes::<32>(&value.verifying_key, "signer verifying key")?,
        roles: value
            .roles
            .iter()
            .map(|role| parse_role(role))
            .collect::<Result<Vec<_>, _>>()?,
        revoked_at: value.revoked_at,
    })
}

fn parse_role(value: &str) -> Result<LearningEvidenceRoleV1, AgentdError> {
    match value {
        "generator" => Ok(LearningEvidenceRoleV1::Generator),
        "observer" => Ok(LearningEvidenceRoleV1::Observer),
        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
        "credit_allocator" => Ok(LearningEvidenceRoleV1::CreditAllocator),
        "unlearning_authority" => Ok(LearningEvidenceRoleV1::UnlearningAuthority),
        "selector" => Ok(LearningEvidenceRoleV1::Selector),
        _ => Err(AgentdError::Invalid(format!(
            "unsupported learning evidence role {value:?}"
        ))),
    }
}

fn stable_id(value: &str, label: &str) -> Result<StableId, AgentdError> {
    StableId::new(value).map_err(|error| AgentdError::Invalid(format!("invalid {label}: {error}")))
}

fn digest(value: &str, label: &str) -> Result<Digest32, AgentdError> {
    value
        .parse::<Digest32>()
        .map_err(|error| AgentdError::Invalid(format!("invalid {label}: {error}")))
}

fn fixed_bytes<const N: usize>(value: &[u8], label: &str) -> Result<[u8; N], AgentdError> {
    value
        .try_into()
        .map_err(|_| AgentdError::Invalid(format!("{label} must contain {N} bytes")))
}

fn validate_bootstrap_path(path: &Path) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(
            "intuition bootstrap path must be absolute".to_string(),
        ));
    }
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| AgentdError::Invalid(format!("stat intuition bootstrap: {error}")))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_BOOTSTRAP_BYTES
    {
        return Err(AgentdError::Invalid(
            "intuition bootstrap must be a bounded regular file".to_string(),
        ));
    }
    validate_bootstrap_permissions(&metadata)
}

#[cfg(unix)]
fn validate_bootstrap_permissions(metadata: &std::fs::Metadata) -> Result<(), AgentdError> {
    use std::os::unix::fs::PermissionsExt;

    if metadata.permissions().mode() & 0o022 != 0 {
        return Err(AgentdError::Invalid(
            "intuition bootstrap must not be group/world writable".to_string(),
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_bootstrap_permissions(_metadata: &std::fs::Metadata) -> Result<(), AgentdError> {
    Ok(())
}

#[cfg(test)]
#[path = "intuition_policy_bootstrap_tests.rs"]
mod tests;
