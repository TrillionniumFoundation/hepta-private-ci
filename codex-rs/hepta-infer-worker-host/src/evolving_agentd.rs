//! Installed model assistance owned by the existing Agentd task supervisor.
//! Pending artifacts produce an advisory Generator turn. They never become
//! weights, calibration, independent holdout evidence or activation authority.
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::AgentdSelfIterationArtifactReadinessV1;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_agentd::assess_self_iteration_pending_inputs_v1;
use codex_hepta_agentd::inspect_self_iteration_artifacts_v1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use crate::AppServerSelfIterationModelPortV1;
use crate::final_use_authorizer::UnixFinalUseAuthorizer;
use crate::native_app_server::AppServerModelDriver;
use crate::native_app_server::NativeWorkerConfig;

pub const HOST_CONFIG_ENV: &str = "HEPTA_SELF_ITERATION_HOST_CONFIG";
pub const HOST_CONFIG_DIGEST_ENV: &str = "HEPTA_SELF_ITERATION_HOST_CONFIG_DIGEST";

/// A checksum-pinned installer descriptor. The environment is supplied by the
/// immutable installed release manifest, never model/request data.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationHostConfigV1 {
    pub version: u32,
    pub agent_id: String,
    pub model: String,
    pub objective_prompt: String,
    pub objective_digest: String,
    pub base_commit_digest: String,
    pub base_tree_digest: String,
    pub grammar_digest: String,
    pub trusted_inputs_directory: PathBuf,
    pub inputs_manifest_filename: String,
    pub inputs_manifest_digest: String,
    pub candidate_generation: u64,
    pub native_journal: PathBuf,
    pub native_record_capacity: usize,
    pub maximum_in_flight: usize,
    pub final_use_authority_config: PathBuf,
    pub proposal_timeout_seconds: u64,
    pub status_file: PathBuf,
}

pub fn compose_installed_model_owner(config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
    let path = std::env::var_os(HOST_CONFIG_ENV)
        .ok_or_else(|| invalid("installed self-iteration host configuration is required"))?;
    let pin: Digest32 = std::env::var(HOST_CONFIG_DIGEST_ENV)
        .map_err(|_| invalid("installed self-iteration host digest is required"))?
        .parse()
        .map_err(|_| invalid("installed host digest"))?;
    let installed = load_host_config(Path::new(&path), pin, config.identity())?;
    let identity = config.identity().clone();
    // These are existing production owners. The model client has public
    // verifying material only; issuer signing material is absent from this host.
    let authorizer = UnixFinalUseAuthorizer::open(&installed.final_use_authority_config)
        .map_err(|error| invalid(error.to_string()))?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: identity.control_socket.clone(),
        agent_id: identity.agent_id.clone(),
        generation: identity.spawn_generation,
        model: installed.model.clone(),
        timeout: Duration::from_secs(installed.proposal_timeout_seconds),
    })
    .map_err(|error| invalid(error.to_string()))?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let control =
        DurableInferenceControl::open(&installed.native_journal, installed.native_record_capacity)
            .map_err(|error| invalid(error.to_string()))?;
    config.with_self_iteration_model_owner(move |cancellation| async move {
        let mut model = AppServerSelfIterationModelPortV1::new(
            driver,
            control,
            installed.maximum_in_flight,
            cancellation.clone(),
        )
        .map_err(|error| invalid(error.to_string()))?;
        run_model_owner(&mut model, installed, identity, cancellation).await
    })
}

pub fn load_host_config(
    path: &Path,
    expected: Digest32,
    identity: &AgentdIdentity,
) -> Result<SelfIterationHostConfigV1, AgentdError> {
    if expected.is_zero() || !path.is_absolute() || path.canonicalize()? != path {
        return Err(invalid("installed host path or pin"));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > 64 * 1024
    {
        return Err(invalid("installed host file bounds"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1
            || metadata.mode() & 0o022 != 0
            || metadata.uid() != 0 && metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(invalid("installed host file ownership or permissions"));
        }
    }
    let file = File::open(path)?;
    let opened = file.metadata()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.dev() != opened.dev() || metadata.ino() != opened.ino() {
            return Err(invalid("host file identity changed"));
        }
    }
    let mut bytes = Vec::new();
    file.take(64 * 1024 + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() || Digest32::of_bytes(&bytes) != expected {
        return Err(invalid("installed host descriptor changed"));
    }
    let installed: SelfIterationHostConfigV1 =
        serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))?;
    if installed.version != 1
        || installed.agent_id != identity.agent_id.to_string()
        || installed.objective_prompt.is_empty()
        || installed.objective_prompt.len() > 2 * 1024
        || parse_digest(&installed.objective_digest)?
            != Digest32::of_bytes(installed.objective_prompt.as_bytes())
        || installed.model.is_empty()
        || installed.model.len() > 256
        || installed.candidate_generation == 0
        || !(1..=16_384).contains(&installed.native_record_capacity)
        || !(1..=8).contains(&installed.maximum_in_flight)
        || !(5..=3600).contains(&installed.proposal_timeout_seconds)
    {
        return Err(invalid("installed model owner identity or budgets"));
    }
    for digest in [
        &installed.base_commit_digest,
        &installed.base_tree_digest,
        &installed.grammar_digest,
        &installed.inputs_manifest_digest,
    ] {
        parse_digest(digest)?;
    }
    for target in [&installed.native_journal, &installed.status_file] {
        if !target.is_absolute()
            || !target.starts_with(&identity.home_root)
            || target.file_name().is_none()
        {
            return Err(invalid(
                "model owner state must remain in its exact private Agent home",
            ));
        }
        private_parent(target)?;
        match std::fs::symlink_metadata(target) {
            Ok(metadata) => {
                if !metadata.is_file() || metadata.file_type().is_symlink() {
                    return Err(invalid("model owner state must be a regular file"));
                }
                #[cfg(unix)]
                {
                    use std::os::unix::fs::MetadataExt;
                    if metadata.nlink() != 1
                        || metadata.mode() & 0o077 != 0
                        || metadata.uid() != rustix::process::geteuid().as_raw()
                    {
                        return Err(invalid("model owner state ownership or permissions"));
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    if !installed.final_use_authority_config.is_absolute() {
        return Err(invalid("final-use authority configuration path"));
    }
    Ok(installed)
}

async fn run_model_owner(
    model: &mut AppServerSelfIterationModelPortV1,
    installed: SelfIterationHostConfigV1,
    identity: AgentdIdentity,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    let mut interval = tokio::time::interval(Duration::from_secs(60));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let client = AgentdClient::new(
        identity.control_socket,
        identity.agent_id,
        identity.spawn_generation,
    )?;
    let mut proposal_attempted = false;
    let mut status = serde_json::json!({
        "version": 1,
        "state": "pending_inputs",
        "generation_ready": false,
        "authority_grants": false,
    });
    loop {
        tokio::select! { _ = cancellation.cancelled() => return Ok(()), _ = interval.tick() => {} }
        // Serial owner maintenance runs at startup and while idle. The future
        // retires its exact bounded native obligations before the next turn.
        match model.maintain_native_control(Duration::from_secs(5)).await {
            Ok(receipt) => {
                let pending = receipt.aborts_unresolved > 0
                    || receipt.terminal_publications_unresolved > 0
                    || receipt.cleanup_error.is_some()
                    || receipt.cleanup.is_some_and(|cleanup| {
                        cleanup.pending_pre_effect > 0
                            || cleanup.unknown_history_retained > 0
                            || cleanup.terminal_cleanup_pending > 0
                            || cleanup.actively_cleaning > 0
                    });
                status["maintenance"] = serde_json::json!({
                    "state": if pending { "pending_native_recovery" } else { "completed_batch" },
                    "aborts_attempted": receipt.aborts_attempted,
                    "aborts_confirmed": receipt.aborts_confirmed,
                    "aborts_unresolved": receipt.aborts_unresolved,
                    "terminal_publications_attempted": receipt.terminal_publications_attempted,
                    "terminal_publications_acknowledged": receipt.terminal_publications_acknowledged,
                    "terminal_publications_unresolved": receipt.terminal_publications_unresolved,
                    "history": receipt.history.map(|history| serde_json::json!({
                        "archived_records": history.archived_records,
                        "resident_native_records": history.resident_native_records,
                        "journal_bytes": history.journal_bytes,
                        "journal_compacted": history.journal_compacted,
                    })),
                    "cleanup": receipt.cleanup.map(|cleanup| serde_json::json!({
                        "pending_pre_effect": cleanup.pending_pre_effect,
                        "unknown_history_retained": cleanup.unknown_history_retained,
                        "terminal_cleanup_pending": cleanup.terminal_cleanup_pending,
                        "actively_cleaning": cleanup.actively_cleaning,
                        "oldest_pending_age_ms": cleanup.oldest_pending_age_ms,
                    })),
                    "diagnostic": receipt.cleanup_error.map(|error| error.chars().take(2048).collect::<String>()),
                });
                publish_status(&installed.status_file, &status)?;
            }
            Err(error) => {
                status["maintenance"] = serde_json::json!({
                    "state": "pending_native_recovery",
                    "diagnostic": error.to_string().chars().take(2048).collect::<String>(),
                });
                publish_status(&installed.status_file, &status)?;
                continue;
            }
        }
        if proposal_attempted {
            continue;
        }
        let health = match client.health().await {
            Ok(health) => health,
            Err(_) => continue,
        };
        if !health.ready || health.fenced {
            continue;
        }
        let readiness = inspect_self_iteration_artifacts_v1(
            &installed.trusted_inputs_directory,
            &installed.inputs_manifest_filename,
            parse_digest(&installed.inputs_manifest_digest)?,
            parse_digest(&installed.objective_digest)?,
            installed.candidate_generation,
            Duration::from_secs(5),
        )?;
        write_status(
            &installed.status_file,
            &mut status,
            "pending_inputs",
            Some(&readiness),
            None,
        )?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| invalid(error.to_string()))?
            .as_secs();
        let envelope = IterationEnvelopeV1 {
            envelope_id: StableId::new(format!(
                "installed.{}.{}",
                installed.agent_id, identity.spawn_generation
            ))
            .map_err(|error| invalid(error.to_string()))?,
            base_commit: parse_digest(&installed.base_commit_digest)?,
            base_tree: parse_digest(&installed.base_tree_digest)?,
            objective_digest: parse_digest(&installed.objective_digest)?,
            grammar_digest: parse_digest(&installed.grammar_digest)?,
            maximum_files: 1,
            maximum_diff_bytes: 64 * 1024,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: now
                .checked_add(installed.proposal_timeout_seconds)
                .ok_or_else(|| invalid("proposal deadline"))?,
        };
        // Exactly one advisory proposal per spawned host. A provider error is
        // durable/pending truth; the periodic loop reconciles it rather than
        // issuing a business retry with a fresh identity.
        proposal_attempted = true;
        let result = assess_self_iteration_pending_inputs_v1(
            model,
            &envelope,
            &installed.objective_prompt,
            &readiness,
        )
        .await;
        match result {
            Ok(proposal) => write_proposal(&installed.status_file, &mut status, &proposal)?,
            Err(error) => write_status(
                &installed.status_file,
                &mut status,
                "pending_model_observation",
                Some(&readiness),
                Some(&error.to_string()),
            )?,
        }
    }
}

fn parse_digest(value: &str) -> Result<Digest32, AgentdError> {
    let digest: Digest32 = value
        .parse()
        .map_err(|_| invalid("installed descriptor digest"))?;
    if digest.is_zero() {
        return Err(invalid("installed descriptor zero digest"));
    }
    Ok(digest)
}
fn invalid(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}
fn private_parent(path: &Path) -> Result<(), AgentdError> {
    let parent = path.parent().ok_or_else(|| invalid("owner state parent"))?;
    if parent.canonicalize()? != parent {
        return Err(invalid("owner state parent symlink"));
    }
    let metadata = std::fs::symlink_metadata(parent)?;
    if !metadata.is_dir() {
        return Err(invalid("owner state parent directory"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 || metadata.uid() != rustix::process::geteuid().as_raw() {
            return Err(invalid("owner state parent must be private"));
        }
    }
    Ok(())
}
fn write_status(
    path: &Path,
    status: &mut serde_json::Value,
    state: &str,
    readiness: Option<&AgentdSelfIterationArtifactReadinessV1>,
    error: Option<&str>,
) -> Result<(), AgentdError> {
    status["state"] = serde_json::json!(state);
    status["inputs"] = serde_json::json!(readiness.map(|value| format!("{value:?}")));
    status["diagnostic"] =
        serde_json::json!(error.map(|message| message.chars().take(2048).collect::<String>()));
    publish_status(path, status)
}
fn write_proposal(
    path: &Path,
    status: &mut serde_json::Value,
    proposal: &codex_hepta_agentd::AgentdSelfIterationPendingProposalV1,
) -> Result<(), AgentdError> {
    status["state"] = serde_json::json!("pending_inputs_advisory_proposal");
    status["inputs"] = serde_json::json!(format!("{:?}", proposal.readiness));
    status["proposal_id"] = serde_json::json!(proposal.assessment.request_id.to_string());
    status["proposal"] = serde_json::json!(proposal.assessment.model_output);
    status["native_run_digest"] =
        serde_json::json!(proposal.assessment.native_run_digest.to_string());
    status["diagnostic"] = serde_json::Value::Null;
    publish_status(path, status)
}
fn publish_status(path: &Path, value: &serde_json::Value) -> Result<(), AgentdError> {
    private_parent(path)?;
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| invalid(error.to_string()))?;
    if bytes.len() > 64 * 1024 {
        return Err(invalid("owner status budget"));
    }
    let temporary = path.with_extension(format!("{}.pending", std::process::id()));
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| {
        let mut file = options.open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&temporary, path)?;
        #[cfg(unix)]
        {
            File::open(path.parent().ok_or_else(|| invalid("status parent"))?)?.sync_all()?;
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}
