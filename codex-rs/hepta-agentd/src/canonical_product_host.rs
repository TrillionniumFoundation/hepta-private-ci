//! Named all-or-none product entrypoints for canonical and shipping Agentd execution.
//!
//! Shipping startup binds the protected host declaration to the exact Agent,
//! trusted configuration files, runtime.codex worker/journal/limits, owner
//! composition identities and production-writer posture before consuming the
//! canonical bootstrap. Compatibility callers continue to use `crate::run`.

use std::path::Path;
use std::str::FromStr;
use std::time::Duration;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdCanonicalRuntimeBootstrapV1;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::ProcessRuntimeCodexExecutorV1;

const SHIPPING_PROFILE_SCHEMA_VERSION: u32 = 1;
const MAX_SHIPPING_PROFILE_BYTES: u64 = 256 * 1024;
const MAX_PROTECTED_PROFILE_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct AgentdShippingProfileV1 {
    schema_version: u32,
    agent_id: String,
    generation: u64,
    runner_configuration_digest: String,
    invocation_provider_digest: String,
    input_provider_digest: String,
    model_provider_policy_digest: String,
    worker_artifact_digest: String,
    final_use_authority_digest: String,
    neuron_owner_binding_digest: String,
    journal_root_digest: String,
    recovery_configuration_digest: String,
    authbus_trust_digest: String,
    authbus_checkpoint_digest: String,
    objective_profile_digest: String,
    prompt_registry_recovery_digest: String,
    production_writer_posture_digest: String,
    enabled_adapters: Vec<String>,
    profile_digest: String,
}

/// One-shot owner of the complete canonical Agentd product composition.
pub struct AgentdCanonicalProductHostV1 {
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    shipping_profile_digest: Option<Digest32>,
}

impl AgentdCanonicalProductHostV1 {
    /// Compatibility typed composition. Shipping builds must use
    /// `new_shipping_from_profile_file` and cannot treat this constructor as a
    /// qualified product profile.
    pub fn new(config: AgentdConfig, bootstrap: AgentdCanonicalRuntimeBootstrapV1) -> Self {
        Self {
            config,
            bootstrap,
            shipping_profile_digest: None,
        }
    }

    /// Construct the exact protected shipping composition.
    ///
    /// The caller supplies identity digests for host-owned code/configuration
    /// that cannot safely be inferred from trait object addresses. Those
    /// digests must be non-zero and are compared with the closed-world profile.
    #[allow(clippy::too_many_arguments)]
    pub fn new_shipping_from_profile_file(
        config: AgentdConfig,
        bootstrap: AgentdCanonicalRuntimeBootstrapV1,
        profile_path: &Path,
        runner_configuration_digest: Digest32,
        invocation_provider_digest: Digest32,
        input_provider_digest: Digest32,
        model_provider_policy_digest: Digest32,
        executor: &ProcessRuntimeCodexExecutorV1,
        queue_capacity: usize,
        maximum_concurrent_jobs: usize,
        recovery_interval: Duration,
    ) -> Result<Self, AgentdError> {
        config.require_intelligence_composition()?;
        for digest in [
            runner_configuration_digest,
            invocation_provider_digest,
            input_provider_digest,
            model_provider_policy_digest,
        ] {
            if digest.is_zero() {
                return Err(AgentdError::Invalid(
                    "shipping composition contains an unbound host component".to_string(),
                ));
            }
        }
        if executor.final_use_authority_digest() != bootstrap.final_use_authority_digest() {
            return Err(AgentdError::GenerationFenced(
                "shipping executor authority differs from the canonical bootstrap".to_string(),
            ));
        }
        let declared = load_profile(profile_path)?;
        let observed = observe_profile(
            &config,
            &bootstrap,
            runner_configuration_digest,
            invocation_provider_digest,
            input_provider_digest,
            model_provider_policy_digest,
            executor,
            queue_capacity,
            maximum_concurrent_jobs,
            recovery_interval,
        )?;
        if declared != observed {
            return Err(AgentdError::GenerationFenced(
                "protected shipping profile differs from the observed Agentd composition"
                    .to_string(),
            ));
        }
        let shipping_profile_digest = parse_digest(&declared.profile_digest, "profile digest")?;
        Ok(Self {
            config,
            bootstrap,
            shipping_profile_digest: Some(shipping_profile_digest),
        })
    }

    pub fn identity(&self) -> &crate::AgentdIdentity {
        self.config.identity()
    }

    pub const fn shipping_profile_digest(&self) -> Option<Digest32> {
        self.shipping_profile_digest
    }

    pub async fn run(self, arg0_paths: Arg0DispatchPaths) -> Result<(), AgentdError> {
        #[cfg(feature = "shipping-product")]
        if self.shipping_profile_digest.is_none() {
            return Err(AgentdError::Invalid(
                "shipping-product Agentd requires the protected shipping constructor; compatibility fallback is disabled"
                    .to_string(),
            ));
        }
        let config = self.bootstrap.install(self.config)?;
        crate::runtime::run(config, arg0_paths).await
    }
}

/// Compatibility typed entrypoint. It fails closed when compiled as the named
/// shipping product because `AgentdCanonicalProductHostV1::run` requires a
/// protected shipping profile in that feature set.
pub async fn run_canonical_product(
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    AgentdCanonicalProductHostV1::new(config, bootstrap)
        .run(arg0_paths)
        .await
}

fn load_profile(path: &Path) -> Result<AgentdShippingProfileV1, AgentdError> {
    let bytes = read_protected(path, MAX_SHIPPING_PROFILE_BYTES, "shipping profile")?;
    let profile: AgentdShippingProfileV1 = serde_json::from_slice(&bytes)?;
    validate_profile(&profile)?;
    Ok(profile)
}

#[allow(clippy::too_many_arguments)]
fn observe_profile(
    config: &AgentdConfig,
    bootstrap: &AgentdCanonicalRuntimeBootstrapV1,
    runner_configuration_digest: Digest32,
    invocation_provider_digest: Digest32,
    input_provider_digest: Digest32,
    model_provider_policy_digest: Digest32,
    executor: &ProcessRuntimeCodexExecutorV1,
    queue_capacity: usize,
    maximum_concurrent_jobs: usize,
    recovery_interval: Duration,
) -> Result<AgentdShippingProfileV1, AgentdError> {
    if queue_capacity == 0
        || maximum_concurrent_jobs == 0
        || maximum_concurrent_jobs > executor.maximum_in_flight()
        || recovery_interval.is_zero()
    {
        return Err(AgentdError::Invalid(
            "shipping recovery limits are invalid".to_string(),
        ));
    }
    let journal = executor.journal_root().to_str().ok_or_else(|| {
        AgentdError::Invalid("runtime.codex journal root must be UTF-8".to_string())
    })?;
    let journal_root_digest = Digest32::of_parts(&[
        b"hepta.runtime-agentd.runtime-codex-journal.v1\0",
        journal.as_bytes(),
    ]);
    let recovery_ms = u64::try_from(recovery_interval.as_millis()).map_err(|_| {
        AgentdError::Invalid("shipping recovery interval exceeds u64 milliseconds".to_string())
    })?;
    let recovery_configuration_digest = Digest32::of_parts(&[
        b"hepta.runtime-agentd.runtime-codex-recovery.v1\0",
        executor.worker_artifact_digest().as_array(),
        journal_root_digest.as_array(),
        &u64::try_from(queue_capacity).unwrap_or(u64::MAX).to_be_bytes(),
        &u64::try_from(maximum_concurrent_jobs)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
        &recovery_ms.to_be_bytes(),
    ]);
    let authbus_trust_digest = digest_required_profile(config.authbus_trust_file(), "AuthBus trust")?;
    let authbus_checkpoint_digest =
        digest_required_profile(config.authbus_checkpoint_file(), "AuthBus checkpoint")?;
    let objective_profile_digest =
        digest_required_profile(config.objective_profile_file(), "Objective profile")?;
    let prompt_registry_recovery_digest = digest_required_profile(
        config.prompt_registry_recovery_checkpoint_file(),
        "prompt-registry recovery checkpoint",
    )?;
    let (writer_installed, production_writer_posture_digest) = production_writer_posture(config)?;
    #[cfg(all(feature = "shipping-product", not(feature = "shipping-read-write")))]
    if writer_installed {
        return Err(AgentdError::Invalid(
            "read-only shipping-product profile forbids a production writer".to_string(),
        ));
    }
    #[cfg(feature = "shipping-read-write")]
    if !writer_installed {
        return Err(AgentdError::Invalid(
            "shipping-read-write profile requires the exact recovered writer owner".to_string(),
        ));
    }
    let enabled_adapters = enabled_adapters(writer_installed);
    let adapters_digest = Digest32::of_bytes(&serde_json::to_vec(&enabled_adapters)?);
    let profile_digest = Digest32::of_parts(&[
        b"hepta.runtime-agentd.shipping-profile.v1\0",
        config.identity().agent_id.as_str().as_bytes(),
        &config.identity().spawn_generation.to_be_bytes(),
        runner_configuration_digest.as_array(),
        invocation_provider_digest.as_array(),
        input_provider_digest.as_array(),
        model_provider_policy_digest.as_array(),
        executor.worker_artifact_digest().as_array(),
        bootstrap.final_use_authority_digest().as_array(),
        bootstrap.neuron_owner_binding_digest().as_array(),
        journal_root_digest.as_array(),
        recovery_configuration_digest.as_array(),
        authbus_trust_digest.as_array(),
        authbus_checkpoint_digest.as_array(),
        objective_profile_digest.as_array(),
        prompt_registry_recovery_digest.as_array(),
        production_writer_posture_digest.as_array(),
        adapters_digest.as_array(),
    ]);
    Ok(AgentdShippingProfileV1 {
        schema_version: SHIPPING_PROFILE_SCHEMA_VERSION,
        agent_id: config.identity().agent_id.to_string(),
        generation: config.identity().spawn_generation,
        runner_configuration_digest: runner_configuration_digest.to_string(),
        invocation_provider_digest: invocation_provider_digest.to_string(),
        input_provider_digest: input_provider_digest.to_string(),
        model_provider_policy_digest: model_provider_policy_digest.to_string(),
        worker_artifact_digest: executor.worker_artifact_digest().to_string(),
        final_use_authority_digest: bootstrap.final_use_authority_digest().to_string(),
        neuron_owner_binding_digest: bootstrap.neuron_owner_binding_digest().to_string(),
        journal_root_digest: journal_root_digest.to_string(),
        recovery_configuration_digest: recovery_configuration_digest.to_string(),
        authbus_trust_digest: authbus_trust_digest.to_string(),
        authbus_checkpoint_digest: authbus_checkpoint_digest.to_string(),
        objective_profile_digest: objective_profile_digest.to_string(),
        prompt_registry_recovery_digest: prompt_registry_recovery_digest.to_string(),
        production_writer_posture_digest: production_writer_posture_digest.to_string(),
        enabled_adapters,
        profile_digest: profile_digest.to_string(),
    })
}

fn validate_profile(profile: &AgentdShippingProfileV1) -> Result<(), AgentdError> {
    if profile.schema_version != SHIPPING_PROFILE_SCHEMA_VERSION
        || profile.agent_id.is_empty()
        || profile.generation == 0
        || profile.enabled_adapters.is_empty()
        || profile.enabled_adapters.len() > 32
    {
        return Err(AgentdError::Invalid(
            "invalid runtime.agentd shipping profile shape".to_string(),
        ));
    }
    let mut previous: Option<&str> = None;
    for adapter in &profile.enabled_adapters {
        if adapter.is_empty()
            || adapter.len() > 128
            || adapter.as_bytes().contains(&0)
            || previous.is_some_and(|value| value >= adapter.as_str())
        {
            return Err(AgentdError::Invalid(
                "shipping adapters must be unique, sorted, bounded identifiers".to_string(),
            ));
        }
        previous = Some(adapter);
    }
    for (value, label) in [
        (&profile.runner_configuration_digest, "runner digest"),
        (&profile.invocation_provider_digest, "invocation provider digest"),
        (&profile.input_provider_digest, "input provider digest"),
        (&profile.model_provider_policy_digest, "model policy digest"),
        (&profile.worker_artifact_digest, "worker digest"),
        (&profile.final_use_authority_digest, "final-use authority digest"),
        (&profile.neuron_owner_binding_digest, "Neuron owner digest"),
        (&profile.journal_root_digest, "journal digest"),
        (&profile.recovery_configuration_digest, "recovery digest"),
        (&profile.authbus_trust_digest, "AuthBus trust digest"),
        (&profile.authbus_checkpoint_digest, "AuthBus checkpoint digest"),
        (&profile.objective_profile_digest, "Objective profile digest"),
        (
            &profile.prompt_registry_recovery_digest,
            "prompt recovery digest",
        ),
        (
            &profile.production_writer_posture_digest,
            "production writer posture digest",
        ),
        (&profile.profile_digest, "profile digest"),
    ] {
        parse_digest(value, label)?;
    }
    Ok(())
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, AgentdError> {
    let digest = Digest32::from_str(value)
        .map_err(|_| AgentdError::Invalid(format!("shipping {label} is invalid")))?;
    if digest.is_zero() {
        return Err(AgentdError::Invalid(format!(
            "shipping {label} must be non-zero"
        )));
    }
    Ok(digest)
}

fn enabled_adapters(writer: bool) -> Vec<String> {
    let mut values = vec![
        "app-server".to_string(),
        "canonical-intelligence".to_string(),
        "runtime-codex".to_string(),
        "shipping-product".to_string(),
    ];
    if writer {
        values.push("cognitive-write".to_string());
    }
    values.sort();
    values
}

fn digest_required_profile(path: Option<&Path>, label: &str) -> Result<Digest32, AgentdError> {
    let path = path.ok_or_else(|| AgentdError::Invalid(format!("shipping product requires {label}")))?;
    let bytes = read_protected(path, MAX_PROTECTED_PROFILE_BYTES, label)?;
    let canonical = path
        .to_str()
        .ok_or_else(|| AgentdError::Invalid(format!("{label} path must be UTF-8")))?;
    Ok(Digest32::of_parts(&[
        b"hepta.runtime-agentd.protected-profile-file.v1\0",
        label.as_bytes(),
        canonical.as_bytes(),
        Digest32::of_bytes(&bytes).as_array(),
    ]))
}

fn read_protected(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(AgentdError::Invalid(format!(
            "{label} path must be absolute, canonical and symlink-free"
        )));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a bounded regular file"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/other writable"
            )));
        }
    }
    Ok(std::fs::read(path)?)
}

fn production_writer_posture(config: &AgentdConfig) -> Result<(bool, Digest32), AgentdError> {
    let Some(host) = config.production_writer_host() else {
        return Ok((
            false,
            Digest32::of_bytes(b"hepta.runtime-agentd.production-writer.disabled.v1"),
        ));
    };
    let writer = host.writer();
    let authority = writer.authority();
    let fencing = authority.fencing_token_digest().map_err(|error| {
        AgentdError::Invalid(format!("production writer fencing identity unavailable: {error}"))
    })?;
    let database = writer.database_path().to_str().ok_or_else(|| {
        AgentdError::Invalid("production writer database path must be UTF-8".to_string())
    })?;
    Ok((
        true,
        Digest32::of_parts(&[
            b"hepta.runtime-agentd.production-writer.enabled.v1\0",
            writer.owner_agent_id().as_str().as_bytes(),
            &writer.generation().to_be_bytes(),
            writer.lease_id().as_bytes(),
            database.as_bytes(),
            authority.grant_digest.as_str().as_bytes(),
            &authority.authority_epoch.to_be_bytes(),
            &authority.owner_epoch.to_be_bytes(),
            &authority.lease_expires_at_unix_seconds.to_be_bytes(),
            fencing.as_str().as_bytes(),
        ]),
    ))
}
