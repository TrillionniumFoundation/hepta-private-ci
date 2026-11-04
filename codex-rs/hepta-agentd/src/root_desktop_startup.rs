//! Joint Session reservation sealed by the same original prepared Root.
use super::PreparedHostAuthoritySession;
use crate::desktop_launch::DesktopInteraction;
use crate::desktop_launch::FrozenBindings;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::time::Instant;
#[path = "root_desktop_reservation.rs"]
mod reservation;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Profile {
    schema: String,
    profile: String,
    grant_lifetime_ms: u64,
    bindings: FrozenBindings,
    interaction: DesktopInteraction,
}
#[derive(Serialize)]
struct Deployment {
    schema: &'static str,
    profile: &'static str,
    agent_id: String,
    spawn_generation: u64,
    session: reservation::SessionBirth,
    bindings: FrozenBindings,
    startup_release: crate::AgentdDesktopStartupRelease,
    interaction: DesktopInteraction,
}
impl PreparedHostAuthoritySession {
    /// Consume the real joint reservation after Root provisioned both exact
    /// policies in its original issuer. SO_PASSCRED must precede Session spawn.
    /// No policy, issuer or ledger is created here. Old Notes recovery is never
    /// inferred. Agentd activates and consumes both ordered offers only after
    /// recovering its one original protected writer.
    pub fn with_desktop_startup_from_session_before(
        mut self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: Instant,
    ) -> io::Result<Self> {
        reservation::remaining(end)?;
        let profile: Profile = crate::authority_host_config::read_root_json(profile_file)?;
        if profile.schema != "hepta.root.desktop_launch_profile.v1"
            || profile.profile != "notes_calculator_v1"
            || profile.grant_lifetime_ms == 0
            || profile.grant_lifetime_ms > 30_000
            || profile.bindings.issuer_id != self.config.signer_id
        {
            return Err(io::Error::other(
                "original Desktop profile differs from retained Root",
            ));
        }
        profile.bindings.validate().map_err(io::Error::other)?;
        profile
            .interaction
            .validate_for(
                &self.registration.registered_identity.identity()?,
                crate::desktop_launch::digest(&profile.bindings.model_tuple_digest)
                    .map_err(io::Error::other)?,
            )
            .map_err(io::Error::other)?;
        super::notes_startup::validate_empty_deployment(&deployment)?;
        let (release, session) = reservation::receive(
            bootstrap,
            &session_pidfd,
            self.config.peer_uid,
            self.config.peer_gid,
            end,
        )?;
        crate::authority_host_runtime::verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        self.service = self
            .service
            .with_notes_from_original_session(&release.notes, profile.grant_lifetime_ms)?;
        self.service = self.service.with_calculator_from_original_session(
            &release.calculator,
            profile.grant_lifetime_ms,
        )?;
        crate::authority_host_runtime::verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        let value = Deployment {
            schema: "hepta.agentd.original_desktop_launch.v1",
            profile: "notes_calculator_v1",
            agent_id: self
                .registration
                .registered_identity
                .agent_id
                .as_str()
                .to_owned(),
            spawn_generation: self.registration.registered_identity.spawn_generation,
            session,
            bindings: profile.bindings,
            startup_release: release,
            interaction: profile.interaction,
        };
        super::notes_startup::seal_deployment(
            deployment,
            &serde_json::to_vec(&value).map_err(io::Error::other)?,
        )?;
        crate::authority_host_runtime::owner_alive(&session_pidfd, end)?;
        reservation::remaining(end)?;
        Ok(self)
    }
}
