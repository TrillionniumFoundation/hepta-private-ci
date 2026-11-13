//! Joint Session reservation sealed by the same original prepared Root.
use super::PreparedHostAuthoritySession;
use crate::RootDesktopPolicy;
use crate::desktop_launch::DesktopInteraction;
use crate::desktop_launch::FrozenBindings;
use crate::desktop_previous_recovery::DesktopPreviousRecovery;
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
    #[serde(
        default,
        deserialize_with = "crate::desktop_previous_recovery::deserialize_present"
    )]
    previous_recovery: Option<DesktopPreviousRecovery>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    previous_recovery: Option<DesktopPreviousRecovery>,
}
impl PreparedHostAuthoritySession {
    /// Consume the real joint reservation after Root provisioned both exact
    /// policies in its original issuer. SO_PASSCRED must precede Session spawn.
    /// No policy, issuer or ledger is created here.
    pub fn with_desktop_startup_from_session_before(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: Instant,
    ) -> io::Result<Self> {
        self.with_desktop_startup_selected(
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
            end,
            None,
        )
    }

    /// Recover the physical original Current, then replace the exact old pair
    /// with the actual new Reserved pair in one original issuer CAS. Previous
    /// targets remain recovery-only; their requests cannot acquire grants.
    pub fn with_desktop_recovery_startup_from_session_before(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: Instant,
        previous: RootDesktopPolicy<'_>,
    ) -> io::Result<Self> {
        self.with_desktop_startup_selected(
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
            end,
            Some(previous),
        )
    }

    fn with_desktop_startup_selected(
        mut self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: Instant,
        previous: Option<RootDesktopPolicy<'_>>,
    ) -> io::Result<Self> {
        reservation::remaining(end)?;
        let profile: Profile = crate::authority_host_config::read_root_json(profile_file)?;
        validate_profile(&profile, &self.config.signer_id, previous.is_some())?;
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
        let recovery = previous.is_some();
        if let Some(previous) = previous {
            validate_recovery_policy(&profile, &previous, &release)?;
            let writer = self
                .config
                .writer
                .as_ref()
                .ok_or_else(|| io::Error::other("original successor writer required"))?;
            if writer.local_lease_generation <= 1 || self.fresh_filesystem {
                return Err(io::Error::other(
                    "original recovered successor required for joint policy replacement",
                ));
            }
            // Read the original physical Current on this retained service;
            // no caller-supplied cut or historical receipt replaces it.
            self.observe_physical_current()?;
            self.service
                .replace_desktop_policy_for_registered_successor(
                    previous,
                    RootDesktopPolicy {
                        notes: &release.notes,
                        calculator: &release.calculator,
                        grant_lifetime_ms: profile.grant_lifetime_ms,
                    },
                )?;
            reservation::remaining(end)?;
        }
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
            schema: if recovery {
                "hepta.agentd.original_desktop_launch.v2"
            } else {
                "hepta.agentd.original_desktop_launch.v1"
            },
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
            previous_recovery: profile.previous_recovery,
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

fn validate_profile(profile: &Profile, issuer: &str, recovery: bool) -> io::Result<()> {
    let schema = if recovery {
        "hepta.root.desktop_launch_profile.v2"
    } else {
        "hepta.root.desktop_launch_profile.v1"
    };
    if profile.schema != schema
        || profile.profile != "notes_calculator_v1"
        || !(1..=30_000).contains(&profile.grant_lifetime_ms)
        || profile.bindings.issuer_id != issuer
        || profile.previous_recovery.is_some() != recovery
    {
        return Err(io::Error::other(
            "original Desktop profile differs from retained Root or recovery selection",
        ));
    }
    if let Some(previous) = &profile.previous_recovery {
        previous.validate().map_err(io::Error::other)?;
    }
    Ok(())
}

fn validate_recovery_policy(
    profile: &Profile,
    previous: &RootDesktopPolicy<'_>,
    release: &crate::AgentdDesktopStartupRelease,
) -> io::Result<()> {
    previous.notes.validate().map_err(io::Error::other)?;
    previous.calculator.validate().map_err(io::Error::other)?;
    release.validate().map_err(io::Error::other)?;
    let recorded = profile
        .previous_recovery
        .as_ref()
        .ok_or_else(|| io::Error::other("original joint previous targets required"))?;
    if !(1..=30_000).contains(&previous.grant_lifetime_ms)
        || recorded.notes.previous_target != *previous.notes
        || recorded.calculator.previous_target != *previous.calculator
        || previous.notes.session_instance != previous.calculator.session_instance
        || previous.notes.session_instance == release.notes.session_instance
        || previous.notes == &release.notes
        || previous.calculator == &release.calculator
    {
        return Err(io::Error::other(
            "joint recovery must name the exact previous policies and distinct actual Reserved pair",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "root_desktop_startup_tests.rs"]
mod tests;
