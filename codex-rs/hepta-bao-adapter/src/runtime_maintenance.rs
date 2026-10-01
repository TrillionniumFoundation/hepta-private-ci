//! Explicit Root intent changes only the original policy while its daemon is offline.
use crate::ConsumerPortError;
use crate::local_endpoint::BoundSocket;
use crate::runtime_config::SecretsRuntimeServiceConfig;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::AuthPolicy;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::TrustedTimeSample;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RootPolicyIntent {
    schema_version: u32,
    runtime_configuration_sha256: [u8; 32],
    expected_policy_revision: u64,
    change: PolicyChange,
}
#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum PolicyChange {
    Renew { expires_at_ms: u64 },
    Revoke {},
}
/// Public metadata of the original revision CAS; no grant or operation is issued.
#[derive(Debug, Eq, PartialEq, Serialize)]
pub struct SecretsPolicyMaintenanceResult {
    pub policy_id: String,
    pub revision: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub already_applied: bool,
}

/// Execute a Root-owned intent as the enrolled runtime UID. Taking the daemon's
/// exact stable writer lock excludes live admission and retains it until the
/// original AuthBus pool is physically closed. Only existing owner files open.
pub async fn maintain_secrets_runtime_policy(
    configuration: &Path,
    intent_path: &Path,
) -> Result<SecretsPolicyMaintenanceResult, ConsumerPortError> {
    let (config, digest): (SecretsRuntimeServiceConfig, _) =
        crate::private_files::read_root_configuration_bound(configuration)?;
    let intent: RootPolicyIntent = crate::private_files::read_root_configuration(intent_path)?;
    if intent.schema_version != 1
        || intent.runtime_configuration_sha256 != digest
        || intent.expected_policy_revision == 0
        || configuration.parent() != intent_path.parent()
        || config.service.service_uid != rustix::process::geteuid().as_raw()
        || config.roles.runtime_uid != config.service.service_uid
        || !config.authbus_database.try_exists().map_err(unavailable)?
        || !config
            .authbus_checkpoint
            .try_exists()
            .map_err(unavailable)?
    {
        return Err(ConsumerPortError::Invalid);
    }
    let _endpoint = BoundSocket::bind(&config.service.socket_path, config.service.ipc_group_gid)?;
    let host = AuthBusAuthorityHost::open(
        &config.authbus_database,
        config.authbus_checkpoint.clone(),
        &config.authbus_owner_id,
    )
    .await
    .map_err(unavailable)?;
    let result = async {
        let attestation = config.roles.authority.trusted_time()?;
        let time = host
            .observe_trusted_time_attestation(&attestation)
            .await
            .map_err(unavailable)?;
        let original = PolicySpec {
            policy_id: StableId::new(&config.policy_id).map_err(unavailable)?,
            principal: StableId::new(&config.request.subject_id).map_err(unavailable)?,
            action: StableId::new("action:bao-read").map_err(unavailable)?,
            scope_digest: Digest32::from_array(config.roles.frozen_binding.scope_sha256),
            effect: PolicyEffect::Allow,
            not_before_ms: config.policy_not_before_ms,
            expires_at_ms: config.policy_expires_at_ms,
        };
        apply_policy_intent(&host, original, &intent, time).await
    }
    .await;
    // No timeout/cancellation path pretends that a committed DB mutation did
    // not happen. The same intent can observe its exact successor revision.
    host.close().await;
    result
}

async fn apply_policy_intent(
    host: &AuthBusAuthorityHost,
    mut original: PolicySpec,
    intent: &RootPolicyIntent,
    time: TrustedTimeSample,
) -> Result<SecretsPolicyMaintenanceResult, ConsumerPortError> {
    let current = host
        .policy_snapshot(&original.policy_id)
        .await
        .map_err(unavailable)?;
    if current.policy_id != original.policy_id
        || current.principal != original.principal
        || current.action != original.action
        || current.scope_digest != original.scope_digest
        || current.effect != original.effect
        || current.not_before_ms != original.not_before_ms
    {
        return Err(ConsumerPortError::Conflict);
    }
    let successor = intent
        .expected_policy_revision
        .checked_add(1)
        .ok_or(ConsumerPortError::Invalid)?;
    let target_expiry = match intent.change {
        PolicyChange::Renew { expires_at_ms } => {
            if expires_at_ms <= original.expires_at_ms || current.revoked {
                return Err(ConsumerPortError::Rejected);
            }
            expires_at_ms
        }
        PolicyChange::Revoke {} => original.expires_at_ms,
    };
    let target_revoked = matches!(intent.change, PolicyChange::Revoke {});
    if current.revision == successor
        && current.expires_at_ms == target_expiry
        && current.revoked == target_revoked
    {
        return Ok(result(current, true));
    }
    if current.revision != intent.expected_policy_revision
        || current.expires_at_ms != original.expires_at_ms
        || current.revoked
    {
        return Err(ConsumerPortError::Conflict);
    }
    if matches!(intent.change, PolicyChange::Renew { .. })
        && (target_expiry <= time.wall_time_ms()
            || target_expiry.saturating_sub(time.wall_time_ms()) > 30 * 86_400_000)
    {
        return Err(ConsumerPortError::Rejected);
    }
    let changed = match intent.change {
        PolicyChange::Renew { .. } => {
            original.expires_at_ms = target_expiry;
            host.replace_policy(original, intent.expected_policy_revision, time)
                .await
        }
        PolicyChange::Revoke {} => {
            host.revoke_policy(&original.policy_id, intent.expected_policy_revision, time)
                .await
        }
    }
    .map_err(unavailable)?;
    Ok(result(changed, false))
}
fn result(policy: AuthPolicy, already_applied: bool) -> SecretsPolicyMaintenanceResult {
    SecretsPolicyMaintenanceResult {
        policy_id: policy.policy_id.to_string(),
        revision: policy.revision,
        expires_at_ms: policy.expires_at_ms,
        revoked: policy.revoked,
        already_applied,
    }
}
fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}

#[cfg(test)]
#[path = "runtime_maintenance_tests.rs"]
mod tests;
