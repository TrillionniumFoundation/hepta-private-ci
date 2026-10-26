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
use crate::authority_host_service::ExpectedNotesPolicy;
use crate::notes_model_route::RegisteredNotesModelRoute;

#[path = "root_notes_reservation.rs"]
mod reservation;

const DEPLOYMENT_BOUND: usize = 16 * 1024;
const SEALS: i32 = libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Profile {
    schema: String,
    grant_lifetime_ms: u64,
    bindings: Bindings,
    #[serde(default)]
    expected_notes_policy: Option<ExpectedNotesPolicy>,
    #[serde(default)]
    previous_recovery: Option<PreviousRecovery>,
    #[serde(default)]
    model_route: Option<RegisteredNotesModelRoute>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    model_route: Option<RegisteredNotesModelRoute>,
}

impl PreparedHostAuthoritySession {
    /// Consume the actual Session's first metadata packet, install its exact
    /// original Notes policy on this retained service, then seal
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
        let profile: Profile = crate::authority_host_config::read_root_json(profile_file)?;
        validate_profile(&profile, &self.config.signer_id)?;
        validate_empty_deployment(&deployment)?;
        let (startup_release, session) = reservation::receive(
            bootstrap,
            &session_pidfd,
            self.config.peer_uid,
            self.config.peer_gid,
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
        let prepared = self.with_registered_notes_from_session_policy(
            &startup_release.target,
            profile.grant_lifetime_ms,
            profile.expected_notes_policy.as_ref(),
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
            model_route: profile.model_route,
        };
        let bytes = serde_json::to_vec(&value).map_err(io::Error::other)?;
        seal_deployment(deployment, &bytes)?;
        crate::authority_host_runtime::owner_alive(&session_pidfd, end)?;
        Ok(prepared)
    }
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
    if let Some(previous) = &profile.expected_notes_policy {
        previous.validate(profile.grant_lifetime_ms)?;
    }
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
    if let Some(route) = &profile.model_route {
        // The Root-owned profile supplies its retained registration evidence.
        // Validate before receiving a reservation or registering any Notes
        // policy; this producer never discovers a thread or synthesizes a route.
        let scope = bindings
            .principal_scope_digest
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        route.clone().into_route(scope).map_err(io::Error::other)?;
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
