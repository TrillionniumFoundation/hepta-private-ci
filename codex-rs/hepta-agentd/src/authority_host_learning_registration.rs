//! Explicit Root registration and open-only recovery of one learning owner.

use std::fs::File;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use serde::Serialize;

use super::*;
use crate::HostAuthorityLearningBootstrapV1;
use crate::HostAuthorityLearningProfileV1;
use crate::LearningIterationCheckpointOwnerV1;
use crate::LearningIterationCheckpointRecordV1;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::read_root_json;
use crate::authority_host_runtime::verify_pinned_process;

const OWNER: &str = "root-learning-checkpoint-v1";

pub(crate) struct RegisteredHostLearningCheckpointV1 {
    pub(crate) backend: LearningIterationCheckpointOwnerV1,
    profile: HostAuthorityLearningProfileV1,
    pub(crate) socket_path: PathBuf,
}

#[derive(Serialize)]
pub struct HostAuthorityLearningRegistrationV1 {
    pub schema_version: u32,
    pub initial_head: String,
    pub writer_proof_digest: String,
    pub frozen_scope_binding: Option<String>,
    pub production_ready: bool,
}

enum StoreMode {
    Register,
    Reopen,
}

impl HostAuthorityService {
    pub(crate) fn register_learning_checkpoint(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile_file: &Path,
    ) -> io::Result<HostAuthorityLearningRegistrationV1> {
        let profile = read_root_json(profile_file)?;
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &profile,
            |initial, scope, proof| {
                learning_store(&config.state_dir, &initial, scope.as_ref(), StoreMode::Register)?;
                Ok(HostAuthorityLearningRegistrationV1 {
                    schema_version: if scope.is_some() { 2 } else { 1 },
                    initial_head: initial.head_digest.to_string(),
                    writer_proof_digest: proof,
                    frozen_scope_binding: scope.map(|scope| scope.binding().to_string()),
                    production_ready: false,
                })
            },
        )
    }

    pub(crate) fn open_registered_learning_checkpoint(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile_file: &Path,
    ) -> io::Result<RegisteredHostLearningCheckpointV1> {
        let profile = read_root_json(profile_file)?;
        let backend = self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &profile,
            |initial, scope, _| learning_store(&config.state_dir, &initial, scope.as_ref(), StoreMode::Reopen),
        )?;
        let socket_path = config
            .sockets
            .observation
            .parent()
            .ok_or_else(|| io::Error::other("learning socket parent required"))?
            .join("learning-checkpoint-v1.sock");
        let mut paths: Vec<_> = crate::authority_host_runtime::validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        paths.push(&socket_path);
        crate::authority_host_runtime::validate_lane_paths(&paths, config.peer_gid)?;
        Ok(RegisteredHostLearningCheckpointV1 {
            backend,
            profile,
            socket_path,
        })
    }

    pub(crate) fn seal_learning_checkpoint(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
    ) -> io::Result<File> {
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &learning.profile,
            |initial, _scope, proof| {
                let before = learning
                    .backend
                    .restore(&initial.request)
                    .map_err(io::Error::other)?;
                let stat = std::fs::read_to_string("/proc/self/stat")?;
                let start = stat
                    .rsplit_once(") ")
                    .and_then(|(_, fields)| fields.split_whitespace().nth(19))
                    .and_then(|value| value.parse::<u64>().ok())
                    .filter(|value| *value != 0)
                    .ok_or_else(|| io::Error::other("missing Root process identity"))?;
                let (schema_version, operation, update_scope) = learning.profile.bootstrap_profile();
                let bundle = HostAuthorityLearningBootstrapV1 {
                    schema_version,
                    operation: operation.into(),
                    root: CognitiveCheckpointPeerLifetime {
                        uid: 0,
                        pid: std::process::id(),
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: start,
                    },
                    consumer: CognitiveCheckpointPeerLifetime {
                        uid: config.peer_uid,
                        pid: registration.peer_pid,
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: registration.process_start_ticks,
                    },
                    registered_identity: registration.registered_identity.clone(),
                    writer_proof_digest: proof,
                    initial_snapshot: learning.profile.encoded_initial().to_owned(),
                    socket_path: learning.socket_path.clone(),
                    update_scope,
                };
                let bytes = serde_json::to_vec(&bundle).map_err(io::Error::other)?;
                let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&bytes)?;
                if learning
                    .backend
                    .restore(&initial.request)
                    .map_err(io::Error::other)?
                    != before
                {
                    return Err(io::Error::other(
                        "learning CURRENT changed during handoff capture",
                    ));
                }
                Ok(sealed)
            },
        )
    }

    fn with_learning_profile<T>(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: &HostAuthorityLearningProfileV1,
        action: impl FnOnce(LearningIterationSnapshotV1, Option<FrozenLearningScopeV2>, String) -> io::Result<T>,
    ) -> io::Result<T> {
        config.required_bind.verify()?;
        RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        if config.schema_version != 1
            || registration.schema_version != 1
            || config.peer_uid == 0
            || config.peer_gid == 0
            || !(1..=500).contains(&config.timeout_ms)
            || !(1..=300_000).contains(&config.lifetime_ms)
            || !config
                .state_dir
                .starts_with(&config.required_bind.mountpoint)
            || registration.registered_identity.identity()? != self.identity
        {
            return Err(io::Error::other(
                "original bounded Root learning registration required",
            ));
        }
        let end = Instant::now() + Duration::from_millis(config.timeout_ms);
        verify_pinned_process(
            registration,
            config.peer_uid,
            config.peer_gid,
            owner_pidfd,
            end,
        )?;
        self.check_logind_lifetime()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        if config.writer.as_ref() != Some(&writer.registration) {
            return Err(io::Error::other(
                "Root learning writer differs from retained config",
            ));
        }
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("original learning writer proof changed"));
            }
            let proof = writer
                .proof
                .sha256()
                .map_err(io::Error::other)?
                .as_str()
                .to_owned();
            let initial = profile.require_binding(&self.identity, &proof)?;
            let scope = profile.frozen_scope(&initial)?;
            let before = self.issuer.revocations()?;
            validate_observation_lease(
                &writer.registration.authority_lease,
                &before,
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            let result = action(initial, scope, proof)?;
            if self.issuer.revocations()? != before
                || self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?
                    != writer.proof
            {
                return Err(io::Error::other(
                    "learning registration outcome uncertain; original authority changed",
                ));
            }
            validate_observation_lease(
                &writer.registration.authority_lease,
                &before,
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            self.check_logind_lifetime()?;
            verify_pinned_process(
                registration,
                config.peer_uid,
                config.peer_gid,
                owner_pidfd,
                end,
            )?;
            Ok(result)
        })
    }
}

fn learning_store(
    state_dir: &Path,
    initial: &LearningIterationSnapshotV1,
    scope: Option<&FrozenLearningScopeV2>,
    mode: StoreMode,
) -> io::Result<LearningIterationCheckpointOwnerV1> {
    RootAuthorityDirectory::open(state_dir).map_err(io::Error::other)?;
    let path = state_dir.join("learning-checkpoint");
    let store = match mode {
        StoreMode::Register => {
            std::fs::DirBuilder::new().mode(0o700).create(&path)?;
            File::open(state_dir)?.sync_all()?;
            let vacant = match scope {
                Some(scope) => LearningIterationCheckpointRecordV1::vacant_scoped_v2(
                    initial.request.clone(), initial.owners.clone(), scope,
                ),
                None => LearningIterationCheckpointRecordV1::vacant(
                    initial.request.clone(), initial.owners.clone(),
                ),
            }
            .map_err(io::Error::other)?;
            HostAuthorityFrontierStore::initialize(
                RootAuthorityDirectory::open(&path).map_err(io::Error::other)?,
                OWNER.into(),
                vacant,
            )
        }
        StoreMode::Reopen => HostAuthorityFrontierStore::open(
            RootAuthorityDirectory::open(&path).map_err(io::Error::other)?,
            OWNER.into(),
        ),
    }
    .map_err(io::Error::other)?;
    match scope {
        Some(scope) => LearningIterationCheckpointOwnerV1::from_registered_scoped_v2(
            store, OWNER.into(), initial.request.clone(), initial.owners.clone(), scope.clone(),
        ),
        None => LearningIterationCheckpointOwnerV1::from_registered(
            store, OWNER.into(), initial.request.clone(), initial.owners.clone(),
        ),
    }
    .map_err(io::Error::other)
}

#[cfg(test)]
#[path = "authority_host_learning_registration_tests.rs"]
mod tests;
