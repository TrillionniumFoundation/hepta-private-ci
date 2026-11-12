//! Explicit Root registration and open-only recovery of one learning owner.

use std::fs::File;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
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
    pub(crate) profile: HostAuthorityLearningProfileV1,
    pub(crate) socket_path: PathBuf,
    pub(crate) q24_model:
        Option<crate::authority_host_service::q24_model::RegisteredQ24ModelFactory>,
}

#[derive(Serialize)]
pub struct HostAuthorityLearningRegistrationV1 {
    pub schema_version: u32,
    pub initial_head: String,
    pub writer_proof_digest: String,
    #[serde(skip_serializing_if = "Option::is_none")]
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
        HostAuthorityService::reserve_original_learning_profile(
            self,
            config,
            registration,
            owner_pidfd,
            &profile,
        )
    }

    /// Reserve a typed profile through this same original service and all
    /// original witness checks. Phase callers additionally require their
    /// durable once-claim before entering this body.
    pub(crate) fn reserve_original_learning_profile(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: &HostAuthorityLearningProfileV1,
    ) -> io::Result<HostAuthorityLearningRegistrationV1> {
        self.reserve_original_learning_profile_in_phase(
            config,
            registration,
            owner_pidfd,
            profile,
            None,
        )
    }

    pub(crate) fn reserve_original_learning_profile_in_phase(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: &HostAuthorityLearningProfileV1,
        phase: Option<
            &crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext<
                '_,
            >,
        >,
    ) -> io::Result<HostAuthorityLearningRegistrationV1> {
        self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            profile,
            |initial, proof| {
                let _admission = phase.map(crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext::enter_claimed).transpose()?;
                let scope = profile.frozen_scope(&initial)?;
                let binding = scope.as_ref().map(|scope| scope.binding().to_string());
                if let Some(phase) = phase {
                    phase.require_claimed()?;
                }
                learning_store(&config.state_dir, &initial, StoreMode::Register, scope)?;
                if let Some(phase) = phase {
                    phase.require_claimed()?;
                }
                Ok(HostAuthorityLearningRegistrationV1 {
                    schema_version: profile.schema_version,
                    initial_head: initial.head_digest.to_string(),
                    writer_proof_digest: proof,
                    frozen_scope_binding: binding,
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
        HostAuthorityService::open_original_learning_profile(
            self,
            config,
            registration,
            owner_pidfd,
            profile,
        )
    }

    pub(crate) fn open_original_learning_profile(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: HostAuthorityLearningProfileV1,
    ) -> io::Result<RegisteredHostLearningCheckpointV1> {
        self.open_original_learning_profile_in_phase(
            config,
            registration,
            owner_pidfd,
            profile,
            None,
        )
    }

    pub(crate) fn open_original_learning_profile_in_phase(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: HostAuthorityLearningProfileV1,
        phase: Option<
            &crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext<
                '_,
            >,
        >,
    ) -> io::Result<RegisteredHostLearningCheckpointV1> {
        let backend = self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &profile,
            |initial, _| {
                let _admission = phase.map(crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext::enter_claimed).transpose()?;
                let store = learning_store(
                    &config.state_dir,
                    &initial,
                    StoreMode::Reopen,
                    profile.frozen_scope(&initial)?,
                )?;
                if let Some(phase) = phase {
                    phase.require_claimed()?;
                }
                Ok(store)
            },
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
        if let Some(phase) = phase {
            phase.require_claimed()?;
        }
        Ok(RegisteredHostLearningCheckpointV1 {
            backend,
            profile,
            socket_path,
            q24_model: None,
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
            |initial, proof| {
                let scope = learning.profile.frozen_scope(&initial)?;
                if learning.backend.frozen_scope_binding()
                    != scope.as_ref().map(FrozenLearningScopeV2::binding)
                {
                    return Err(io::Error::other(
                        "registered learning scope differs from handoff",
                    ));
                }
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
                let bundle = HostAuthorityLearningBootstrapV1 {
                    schema_version: learning.profile.schema_version,
                    operation: match scope {
                        Some(_) => crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2,
                        None => crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1,
                    }
                    .into(),
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
                    update_scope: learning.profile.update_scope.clone(),
                    socket_path: learning.socket_path.clone(),
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

    pub(crate) fn with_learning_profile<T>(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: &HostAuthorityLearningProfileV1,
        action: impl FnOnce(LearningIterationSnapshotV1, String) -> io::Result<T>,
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
            let before = self.issuer.revocations()?;
            validate_observation_lease(
                &writer.registration.authority_lease,
                &before,
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            let result = action(initial, proof)?;
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
    mode: StoreMode,
    scope: Option<FrozenLearningScopeV2>,
) -> io::Result<LearningIterationCheckpointOwnerV1> {
    if let Some(scope) = &scope {
        scope.validate_snapshot(initial).map_err(io::Error::other)?;
    }
    RootAuthorityDirectory::open(state_dir).map_err(io::Error::other)?;
    let path = state_dir.join("learning-checkpoint");
    let store = match mode {
        StoreMode::Register => {
            std::fs::DirBuilder::new().mode(0o700).create(&path)?;
            File::open(state_dir)?.sync_all()?;
            let vacant = match &scope {
                Some(scope) => LearningIterationCheckpointRecordV1::vacant_scoped_v2(
                    initial.request.clone(),
                    initial.owners.clone(),
                    scope,
                ),
                None => LearningIterationCheckpointRecordV1::vacant(
                    initial.request.clone(),
                    initial.owners.clone(),
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
            store,
            OWNER.into(),
            initial.request.clone(),
            initial.owners.clone(),
            scope,
        ),
        None => LearningIterationCheckpointOwnerV1::from_registered(
            store,
            OWNER.into(),
            initial.request.clone(),
            initial.owners.clone(),
        ),
    }
    .map_err(io::Error::other)
}

#[cfg(test)]
#[path = "authority_host_learning_registration_tests.rs"]
mod tests;
