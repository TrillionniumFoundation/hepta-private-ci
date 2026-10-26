//! Original Root startup caller for one actual staged Notes application. The
//! private profile provides public compiler bindings, never Session identity.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::PreparedHostAuthoritySession;
use crate::notes_launch_mode::NotesLaunchMode;

#[path = "root_notes_reservation.rs"]
mod reservation;

const DEPLOYMENT_BOUND: usize = 16 * 1024;
const SEALS: i32 = libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;

/// Existing original policy metadata, not a grant or a new Session identity.
/// The successor target is accepted only from the actual Reserved packet.
pub struct RootNotesPolicyPredecessor<'a> {
    pub target: &'a NotesTargetIdentity,
    pub grant_lifetime_ms: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Profile {
    schema: String,
    grant_lifetime_ms: u64,
    bindings: Bindings,
    #[serde(default)]
    interaction: NotesLaunchMode,
    #[serde(default)]
    previous_recovery: Option<PreviousRecovery>,
}

#[derive(Deserialize, Serialize)]
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

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PreviousRecovery {
    helper: PathBuf,
    helper_sha256: String,
    state_directory: PathBuf,
    previous_target: NotesTargetIdentity,
    operation_id: String,
}

#[derive(Serialize)]
struct Deployment {
    schema: &'static str,
    agent_id: String,
    spawn_generation: u64,
    session: reservation::SessionBirth,
    bindings: Bindings,
    previous_recovery: Option<PreviousRecovery>,
    startup_release: reservation::StartupRelease,
    interaction: NotesLaunchMode,
}

impl PreparedHostAuthoritySession {
    /// Consume the actual Session's first metadata packet, install its exact
    /// pre-existing original Notes policy on this retained service, then seal
    /// the already inherited read-only deployment. Root must have created the
    /// anonymous pair and enabled SO_PASSCRED before spawning Session. Agentd
    /// holds a duplicate but may not read it until the late Root handoff.
    /// No Activate, application FD offer or attached acknowledgement is made
    /// here; only the recovered original Agentd factory can perform those.
    pub fn with_notes_startup_from_session(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
    ) -> io::Result<Self> {
        let end = std::time::Instant::now() + std::time::Duration::from_secs(30);
        self.with_notes_startup_from_session_before(
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
            end,
        )
    }

    /// Preserve the trusted launcher's already running startup episode across
    /// metadata peeking, original owner registration and this sole consume.
    /// Expiry consumes this prepared service; it cannot rearm a reservation.
    pub fn with_notes_startup_from_session_before(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: std::time::Instant,
    ) -> io::Result<Self> {
        self.with_notes_startup_selected(
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
            end,
            /*previous*/ None,
        )
    }

    /// Same-boot successor startup after original physical Current recovery.
    /// Only the actual new Session Reserved target replaces the old policy;
    /// old operations remain recovery-only under their original identity.
    pub fn with_notes_recovery_startup_from_session_before(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: std::time::Instant,
        previous: RootNotesPolicyPredecessor<'_>,
    ) -> io::Result<Self> {
        self.with_notes_startup_selected(
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
            end,
            Some(previous),
        )
    }

    fn with_notes_startup_selected(
        self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
        end: std::time::Instant,
        previous: Option<RootNotesPolicyPredecessor<'_>>,
    ) -> io::Result<Self> {
        reservation::remaining(end)?;
        let profile: Profile = crate::authority_host_config::read_root_json(profile_file)?;
        validate_profile(&profile, &self.config.signer_id)?;
        profile
            .interaction
            .validate_for(&self.registration.registered_identity.identity()?)
            .map_err(io::Error::other)?;
        profile
            .interaction
            .validate_model_tuple(
                profile
                    .bindings
                    .model_tuple_digest
                    .parse::<Digest32>()
                    .map_err(io::Error::other)?,
            )
            .map_err(io::Error::other)?;
        validate_empty_deployment(&deployment)?;
        let (startup_release, session) = reservation::receive(
            bootstrap,
            &session_pidfd,
            self.config.peer_uid,
            self.config.peer_gid,
            end,
        )?;
        if let Some(previous) = &profile.previous_recovery {
            previous
                .previous_target
                .validate()
                .map_err(io::Error::other)?;
            StableId::new(&previous.operation_id).map_err(io::Error::other)?;
            Sha256Digest::parse(previous.helper_sha256.clone()).map_err(io::Error::other)?;
            if previous.previous_target == startup_release.target
                || !previous.helper.is_absolute()
                || !previous.state_directory.is_absolute()
            {
                return Err(io::Error::other(
                    "old Notes recovery requires its distinct actual target and absolute frozen paths",
                ));
            }
        }
        if let Some(previous) = previous {
            validate_recovery_policy(&profile, &previous, &startup_release.target)?;
            // The original writer registration must be a genuine successor;
            // a fresh source cannot turn this method into policy provisioning.
            let writer = self
                .config
                .writer
                .as_ref()
                .ok_or_else(|| io::Error::other("original successor writer required"))?;
            if writer.local_lease_generation <= 1 || self.fresh_filesystem {
                return Err(io::Error::other(
                    "original recovered successor required for Notes policy replacement",
                ));
            }
            // Authenticated same-object physical Current observation, never a
            // cached receipt or a replacement cut supplied by the launcher.
            self.observe_physical_current()?;
            self.service.replace_notes_policy_for_registered_successor(
                previous.target,
                previous.grant_lifetime_ms,
                &startup_release.target,
                profile.grant_lifetime_ms,
            )?;
            reservation::remaining(end)?;
        }
        let prepared = self.with_registered_notes_from_session(
            &startup_release.target,
            profile.grant_lifetime_ms,
        )?;
        let value = Deployment {
            schema: "hepta.agentd.original_notes_launch.v1",
            agent_id: prepared
                .registration
                .registered_identity
                .agent_id
                .as_str()
                .to_owned(),
            spawn_generation: prepared.registration.registered_identity.spawn_generation,
            session,
            bindings: profile.bindings,
            previous_recovery: profile.previous_recovery,
            startup_release,
            interaction: profile.interaction,
        };
        let bytes = serde_json::to_vec(&value).map_err(io::Error::other)?;
        seal_deployment(deployment, &bytes)?;
        crate::authority_host_runtime::owner_alive(&session_pidfd, end)?;
        Ok(prepared)
    }
}

fn validate_recovery_policy(
    profile: &Profile,
    previous: &RootNotesPolicyPredecessor<'_>,
    target: &NotesTargetIdentity,
) -> io::Result<()> {
    previous.target.validate().map_err(io::Error::other)?;
    if previous.grant_lifetime_ms == 0
        || previous.target == target
        || profile
            .previous_recovery
            .as_ref()
            .is_none_or(|old| old.previous_target != *previous.target)
    {
        return Err(io::Error::other(
            "recovery must name its exact original old Notes policy and distinct actual Reserved target",
        ));
    }
    Ok(())
}

fn validate_profile(profile: &Profile, issuer_id: &str) -> io::Result<()> {
    let bindings = &profile.bindings;
    if profile.schema != "hepta.root.notes_launch_profile.v1"
        || profile.grant_lifetime_ms == 0
        || bindings.issuer_id != issuer_id
        || bindings.principal_scope.is_empty()
        || !matches!(bindings.locale.as_str(), "en-US" | "zh-CN")
    {
        return Err(io::Error::other(
            "original Notes launch profile differs from the registered issuer",
        ));
    }
    Generation::new(bindings.policy_generation).map_err(io::Error::other)?;
    for digest in [
        &bindings.principal_scope_digest,
        &bindings.runtime_body_digest,
        &bindings.preference_state_digest,
        &bindings.model_tuple_digest,
        &bindings.prompt_registry_digest,
        &bindings.artifact_set_digest,
    ] {
        if digest
            .parse::<Digest32>()
            .map_err(io::Error::other)?
            .is_zero()
        {
            return Err(io::Error::other("original Notes frozen digest is absent"));
        }
    }
    Ok(())
}

fn validate_empty_deployment(file: &File) -> io::Result<()> {
    let metadata = file.metadata()?;
    // SAFETY: both fcntl operations read metadata of the retained live file.
    let (flags, seals) = unsafe {
        (
            libc::fcntl(file.as_raw_fd(), libc::F_GETFL),
            libc::fcntl(file.as_raw_fd(), libc::F_GET_SEALS),
        )
    };
    // SAFETY: geteuid reads this process's current kernel credential.
    if unsafe { libc::geteuid() } != 0
        || flags < 0
        || flags & libc::O_ACCMODE != libc::O_RDWR
        || seals != 0
        || !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 0
        || metadata.len() != 0
        || metadata.mode() & 0o7777 != 0o600
    {
        return Err(io::Error::other(
            "Notes deployment requires an empty writable Root0600 sealable memfd",
        ));
    }
    Ok(())
}

fn seal_deployment(mut file: File, bytes: &[u8]) -> io::Result<()> {
    validate_empty_deployment(&file)?;
    if bytes.is_empty() || bytes.len() > DEPLOYMENT_BOUND {
        return Err(io::Error::other(
            "original Notes sealed deployment exceeds bound",
        ));
    }
    file.rewind()?;
    file.write_all(bytes)?;
    // SAFETY: these operations affect only the held Root-owned memfd. The
    // consumer has an independently opened read-only file description and
    // remains behind late Root handoff; dup of this O_RDWR file is not allowed.
    if unsafe { libc::fchmod(file.as_raw_fd(), 0o400) } != 0
        || unsafe { libc::fcntl(file.as_raw_fd(), libc::F_ADD_SEALS, SEALS) } != 0
    {
        return Err(io::Error::last_os_error());
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, bytes.len() as u64)?;
    file.rewind()?;
    let mut actual = Vec::with_capacity(bytes.len());
    Read::by_ref(&mut file)
        .take(DEPLOYMENT_BOUND as u64 + 1)
        .read_to_end(&mut actual)?;
    if actual != bytes {
        return Err(io::Error::other(
            "original Notes sealed deployment readback differs",
        ));
    }
    file.rewind()
}

#[cfg(test)]
#[path = "root_notes_startup_tests.rs"]
mod tests;
