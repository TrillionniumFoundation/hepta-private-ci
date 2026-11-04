//! Distinct joint deployment from the original Root's sealed, read-only FD.
//! Called only after the real Root handoff. These bounded public bindings do
//! not create a grant, writer, thread, recovery request or replacement catalog.

use std::fs::File;
use std::io::Read;
use std::io::Seek;

use serde::Deserialize;

use crate::AgentdDesktopStartupRelease;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNotesLiteralBindings;
use crate::AgentdNotesUiPeer;
use crate::DesktopThreadSeedReceipt;
use crate::desktop_launch::DesktopInteraction;
use crate::desktop_launch::FrozenBindings;
use crate::text_session::AgentdTextSessionConfig;

pub(super) struct DesktopDeployment {
    pub(super) bindings: AgentdNotesLiteralBindings,
    // This existing type describes the actual Session lifetime, not an App
    // identity. Calculator retains its own target type and destination.
    pub(super) peer: AgentdNotesUiPeer,
    pub(super) startup_release: AgentdDesktopStartupRelease,
    pub(super) route: AgentdTextSessionConfig,
    pub(super) seed: DesktopThreadSeedReceipt,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SessionBirth {
    uid: u32,
    pid: u32,
    boot_id: String,
    process_start_ticks: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: String,
    profile: String,
    agent_id: String,
    spawn_generation: u64,
    session: SessionBirth,
    bindings: FrozenBindings,
    startup_release: AgentdDesktopStartupRelease,
    interaction: DesktopInteraction,
}

impl Deployment {
    fn validate_identity(
        &self,
        agent_id: &str,
        spawn_generation: u64,
        owner: u32,
    ) -> Result<(), AgentdError> {
        if self.schema != "hepta.agentd.original_desktop_launch.v1"
            || self.profile != "notes_calculator_v1"
            || self.agent_id != agent_id
            || self.spawn_generation != spawn_generation
            || owner == 0
            || self.session.uid != owner
            || self.session.pid == 0
            || self.session.pid > i32::MAX as u32
            || self.session.process_start_ticks == 0
            || self.session.boot_id.len() != 36
        {
            return Err(invalid("profile or actual Agentd/Session identity differs"));
        }
        self.startup_release.validate()
    }
}

pub(super) fn read(
    mut file: File,
    identity: &AgentdIdentity,
) -> Result<DesktopDeployment, AgentdError> {
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
    // SAFETY: geteuid reads this process's actual post-handoff credential.
    let owner = unsafe { libc::geteuid() };
    value.validate_identity(identity.agent_id.as_str(), identity.spawn_generation, owner)?;
    let bindings = value.bindings.into_original()?;
    value
        .interaction
        .validate_for(identity, bindings.model_tuple_digest)?;
    let DesktopInteraction::OriginalDesktopThreadToolV1 { route, seed } = value.interaction;
    Ok(DesktopDeployment {
        bindings,
        peer: AgentdNotesUiPeer {
            uid: value.session.uid,
            pid: value.session.pid,
            boot_id: value.session.boot_id,
            process_start_ticks: value.session.process_start_ticks,
        },
        startup_release: value.startup_release,
        route,
        seed,
    })
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("original Desktop deployment: {message}"))
}

#[cfg(test)]
#[path = "production_desktop_deployment_tests.rs"]
mod tests;
