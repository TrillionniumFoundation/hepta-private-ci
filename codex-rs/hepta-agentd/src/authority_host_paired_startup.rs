//! Bind a frozen plan to the original Root writer before the original UI runs.
//! Held material descriptors remain unread until late consent admission.

use super::*;
use crate::HostAuthorityPairedTrainingBootstrapV1;
use crate::HostAuthorityPairedTrainingProfileV1;
use crate::RootPairedTrainingPlanV1;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::read_root_json;
use crate::authority_host_runtime::verify_pinned_process;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

pub(crate) struct RegisteredPairedTrainingPlan {
    pub(crate) plan: RootPairedTrainingPlanV1,
    profile: HostAuthorityPairedTrainingProfileV1,
    pub(crate) failure: File,
    pub(crate) correction: File,
    pub(crate) socket_path: PathBuf,
}

impl HostAuthorityService {
    pub(crate) fn prepare_original_paired_training(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        profile_file: &Path,
        failure: File,
        correction: File,
    ) -> io::Result<RegisteredPairedTrainingPlan> {
        let profile: HostAuthorityPairedTrainingProfileV1 = read_root_json(profile_file)?;
        let plan = self.with_original_paired_profile(
            config,
            registration,
            owner,
            &profile,
            |plan, _proof| Ok(plan),
        )?;
        let socket_path = config
            .sockets
            .observation
            .parent()
            .ok_or_else(|| io::Error::other("original paired socket parent missing"))?
            .join("paired-training-v1.sock");
        let mut paths: Vec<_> = crate::authority_host_runtime::validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        paths.push(&socket_path);
        crate::authority_host_runtime::validate_lane_paths(&paths, config.peer_gid)?;
        Ok(RegisteredPairedTrainingPlan {
            plan,
            profile,
            failure,
            correction,
            socket_path,
        })
    }

    pub(crate) fn seal_original_paired_training(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        paired: &RegisteredPairedTrainingPlan,
    ) -> io::Result<File> {
        self.with_original_paired_profile(
            config,
            registration,
            owner,
            &paired.profile,
            |plan, proof| {
                if plan != paired.plan {
                    return Err(io::Error::other(
                        "original paired plan changed before sealing",
                    ));
                }
                let stat = std::fs::read_to_string("/proc/self/stat")?;
                let start = stat
                    .rsplit_once(") ")
                    .and_then(|(_, fields)| fields.split_whitespace().nth(19))
                    .and_then(|value| value.parse::<u64>().ok())
                    .filter(|value| *value != 0)
                    .ok_or_else(|| io::Error::other("original Root process identity missing"))?;
                let bundle = HostAuthorityPairedTrainingBootstrapV1 {
                    schema_version: 1,
                    operation: crate::HOST_AUTHORITY_PAIRED_TRAINING_BOOTSTRAP_V1.into(),
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
                    socket_path: paired.socket_path.clone(),
                    profile: paired.profile.clone(),
                };
                crate::authority_host_bootstrap_seal::seal_bytes(
                    &serde_json::to_vec(&bundle).map_err(io::Error::other)?,
                )
            },
        )
    }

    pub(super) fn with_original_paired_profile<T>(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        profile: &HostAuthorityPairedTrainingProfileV1,
        action: impl FnOnce(RootPairedTrainingPlanV1, String) -> io::Result<T>,
    ) -> io::Result<T> {
        // SAFETY: read the actual process credentials; never change identity.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || config.schema_version != 1
            || registration.schema_version != 1
            || config.peer_uid == 0
            || config.peer_gid == 0
            || !(1..=500).contains(&config.timeout_ms)
            || !(1..=300_000).contains(&config.lifetime_ms)
            || config.issuer_record_profile
                != crate::authority_host_config::HostIssuerRecordProfile::TextRecovery
            || !config
                .state_dir
                .starts_with(&config.required_bind.mountpoint)
            || registration.registered_identity.identity()? != self.identity
            || self.logind_session.is_none()
            || self.root_registry.is_none()
            || self.paired.is_some()
            || self.paired_training.is_some()
        {
            return Err(io::Error::other(
                "original Root paired startup owners required",
            ));
        }
        config.required_bind.verify()?;
        codex_hepta_contracts::RootAuthorityDirectory::open(&config.state_dir)
            .map_err(io::Error::other)?;
        let end = Instant::now() + Duration::from_millis(config.timeout_ms);
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        self.check_logind_lifetime()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original paired writer required"))?;
        if config.writer.as_ref() != Some(&writer.registration) {
            return Err(io::Error::other(
                "paired startup changed the original writer",
            ));
        }
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("original paired writer proof changed"));
            }
            let proof = writer
                .proof
                .sha256()
                .map_err(io::Error::other)?
                .as_str()
                .to_owned();
            let plan = profile.require_binding(&self.identity, &proof)?;
            let before = self.issuer.revocations()?;
            let result = action(plan, proof)?;
            if self.issuer.revocations()? != before
                || self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?
                    != writer.proof
            {
                return Err(io::Error::other(
                    "paired startup authority changed during capture",
                ));
            }
            self.check_logind_lifetime()?;
            verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
            Ok(result)
        })
    }
}
