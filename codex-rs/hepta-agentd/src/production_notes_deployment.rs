//! Decode finite Notes deployment data from the trusted launcher's original
//! sealed file. These public bindings are not authority and contain no keys,
//! current cut, lease, request text, signed ingress or grant.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNotesLiteralBindings;
use crate::AgentdNotesPreviousRecoveryLaunch;
use crate::AgentdNotesStartupRelease;
use crate::notes_launch_mode::NotesLaunchMode;

pub(super) struct NotesDeployment {
    pub(super) bindings: AgentdNotesLiteralBindings,
    pub(super) peer: NotesUiPeer,
    pub(super) previous_recovery: Option<AgentdNotesPreviousRecoveryLaunch>,
    pub(super) startup_release: Option<AgentdNotesStartupRelease>,
    pub(super) interaction: NotesLaunchMode,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NotesUiPeer {
    pub(super) uid: u32,
    pub(super) pid: u32,
    pub(super) boot_id: String,
    pub(super) process_start_ticks: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: String,
    agent_id: String,
    spawn_generation: u64,
    session: NotesUiPeer,
    bindings: Bindings,
    #[serde(default)]
    interaction: NotesLaunchMode,
    #[serde(default)]
    previous_recovery: Option<PreviousRecovery>,
    #[serde(default)]
    startup_release: Option<StartupRelease>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StartupRelease {
    target: NotesTargetIdentity,
    nonce: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PreviousRecovery {
    helper: PathBuf,
    helper_sha256: String,
    state_directory: PathBuf,
    previous_target: NotesTargetIdentity,
    operation_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Bindings {
    principal_scope: String,
    principal_scope_digest: String,
    issuer_id: String,
    policy_generation: u64,
    locale: String,
    runtime_body_digest: String,
    preference_state_digest: String,
    model_tuple_digest: String,
    prompt_registry_digest: String,
    artifact_set_digest: String,
}

pub(super) fn read(
    mut file: File,
    identity: &AgentdIdentity,
) -> Result<NotesDeployment, AgentdError> {
    let size = file.metadata()?.len();
    if size == 0 || size > 16 * 1024 {
        return Err(invalid("sealed deployment exceeds its bound"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    file.rewind()?;
    let mut bytes = Vec::with_capacity(size as usize);
    file.take(size + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != size {
        return Err(invalid("sealed deployment length changed"));
    }
    let value: Deployment = serde_json::from_slice(&bytes)?;
    // SAFETY: geteuid only reads this process's actual kernel credential.
    let owner = unsafe { libc::geteuid() };
    if value.schema != "hepta.agentd.original_notes_launch.v1"
        || value.agent_id != identity.agent_id.as_str()
        || value.spawn_generation != identity.spawn_generation
        || owner == 0
        || value.session.uid != owner
        || value.session.pid == 0
        || value.session.pid > i32::MAX as u32
        || value.session.process_start_ticks == 0
        || value.session.boot_id.len() != 36
    {
        return Err(invalid(
            "deployment differs from actual Agentd/Session identity",
        ));
    }
    let bindings = value.bindings;
    value.interaction.validate_for(identity)?;
    let frozen = AgentdNotesLiteralBindings {
        principal_scope: bindings.principal_scope,
        principal_scope_digest: digest(&bindings.principal_scope_digest)?,
        issuer_id: bindings.issuer_id,
        policy_generation: Generation::new(bindings.policy_generation)
            .map_err(|error| invalid(&error.to_string()))?,
        locale: bindings.locale,
        runtime_body_digest: digest(&bindings.runtime_body_digest)?,
        preference_state_digest: digest(&bindings.preference_state_digest)?,
        model_tuple_digest: digest(&bindings.model_tuple_digest)?,
        prompt_registry_digest: digest(&bindings.prompt_registry_digest)?,
        artifact_set_digest: digest(&bindings.artifact_set_digest)?,
    };
    let previous_recovery = value
        .previous_recovery
        .map(|previous| {
            Ok::<_, AgentdError>(AgentdNotesPreviousRecoveryLaunch {
                helper: previous.helper,
                helper_sha256: Sha256Digest::parse(previous.helper_sha256)
                    .map_err(AgentdError::Invalid)?,
                state_directory: previous.state_directory,
                previous_target: previous.previous_target,
                operation_id: previous.operation_id,
            })
        })
        .transpose()?;
    let startup_release = value
        .startup_release
        .map(|release| AgentdNotesStartupRelease {
            target: release.target,
            nonce: release.nonce,
        });
    Ok(NotesDeployment {
        bindings: frozen,
        peer: value.session,
        previous_recovery,
        startup_release,
        interaction: value.interaction,
    })
}

fn digest(value: &str) -> Result<Digest32, AgentdError> {
    let digest = value
        .parse::<Digest32>()
        .map_err(|error| invalid(&error.to_string()))?;
    if digest.is_zero() {
        return Err(invalid("original frozen digest is absent"));
    }
    Ok(digest)
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("original Notes deployment: {message}"))
}
