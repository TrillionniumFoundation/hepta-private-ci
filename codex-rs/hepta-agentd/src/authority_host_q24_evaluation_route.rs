//! Seal and bind one original B lane. Preparation retains the actual custodian
//! Arc; the daemon receives only a purpose route and the original Root pidfd.

use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use super::*;
use crate::root_independent_b_protocol::Bootstrap;
use crate::root_independent_b_protocol::PURPOSE;
use crate::root_independent_b_protocol::SOCKET;

#[path = "authority_host_q24_evaluation_serve.rs"]
mod serve;
pub(crate) use serve::serve_optional_until;

pub struct RootIndependentBEvaluationOfferV1 {
    pub(crate) bootstrap: File,
}

pub(crate) struct PreparedRootIndependentBEvaluationV1 {
    runtime: RootIndependentBEvaluationRuntimeV1,
    offer: RootIndependentBEvaluationOfferV1,
}

pub(crate) struct RootIndependentBEvaluationRuntimeV1 {
    host: Arc<OriginalRootIndependentBEvaluationFilesV1>,
    bootstrap: Bootstrap,
    phase: AtomicU8,
    end: Instant,
}

pub(crate) struct BoundRootIndependentBEvaluationV1 {
    runtime: RootIndependentBEvaluationRuntimeV1,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl OriginalRootIndependentBEvaluationFilesV1 {
    pub(crate) fn prepare_original_b(
        self: &Arc<Self>,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        request_end: Instant,
    ) -> io::Result<PreparedRootIndependentBEvaluationV1> {
        if request_end > self.end {
            return Err(io::Error::other("original B route exceeds its session"));
        }
        let end = request_end;
        self.require_original_learning(learning)?;
        let (bootstrap, sealed) = self.record.inspect(end, |enrollment| {
            let state = self
                .state
                .try_lock()
                .map_err(|_| io::Error::other("B custody busy"))?;
            let result = service.with_learning_profile(
                config,
                registration,
                owner,
                &self.profile,
                |initial, writer| {
                    owner_alive(owner, end)?;
                    require_learning(&self.initial, &initial, learning)?;
                    require_files(
                        &state.files,
                        enrollment,
                        service.original_learning_unix_seconds()?,
                    )?;
                    state
                        .files
                        .admitted_protocol(&initial, service.original_learning_unix_seconds()?)?;
                    let before = self
                        .backend
                        .restore(&initial.request)
                        .map_err(io::Error::other)?;
                    let scope = self.profile.require_cell_scope(&initial)?;
                    if let Some(current) = &before {
                        scope.validate_snapshot(current).map_err(io::Error::other)?;
                    }
                    let bootstrap = Bootstrap {
                        purpose: PURPOSE.into(),
                        root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                            uid: 0,
                            pid: std::process::id(),
                            boot_id: registration.boot_id.clone(),
                            process_start_ticks: root_start()?,
                        },
                        consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                            uid: config.peer_uid,
                            pid: registration.peer_pid,
                            boot_id: registration.boot_id.clone(),
                            process_start_ticks: registration.process_start_ticks,
                        },
                        identity: registration.registered_identity.clone(),
                        initial: initial.head_digest.to_string(),
                        scope: scope.binding().to_string(),
                        writer,
                        binding: self.original_binding().to_string(),
                        socket: config
                            .sockets
                            .observation
                            .parent()
                            .ok_or_else(|| io::Error::other("original B socket parent missing"))?
                            .join(SOCKET),
                    };
                    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(
                        &serde_json::to_vec(&bootstrap).map_err(io::Error::other)?,
                    )?;
                    if self
                        .backend
                        .restore(&initial.request)
                        .map_err(io::Error::other)?
                        != before
                    {
                        return Err(io::Error::other(
                            "original B checkpoint changed during route capture",
                        ));
                    }
                    Ok((bootstrap, sealed))
                },
            )?;
            owner_alive(owner, end)?;
            require_files(
                &state.files,
                enrollment,
                service.original_learning_unix_seconds()?,
            )?;
            Ok(result)
        })?;
        Ok(PreparedRootIndependentBEvaluationV1 {
            runtime: RootIndependentBEvaluationRuntimeV1 {
                host: Arc::clone(self),
                bootstrap,
                phase: AtomicU8::new(0),
                end: self.end,
            },
            offer: RootIndependentBEvaluationOfferV1 { bootstrap: sealed },
        })
    }

    pub(in super::super) fn observe_original_binding(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        frame_end: Instant,
    ) -> io::Result<String> {
        let end = self.end.min(frame_end);
        self.record.inspect(end, |enrollment| {
            let state = self
                .state
                .try_lock()
                .map_err(|_| io::Error::other("B custody busy"))?;
            let result = service.with_learning_profile(
                config,
                registration,
                owner,
                &self.profile,
                |initial, _| {
                    owner_alive(owner, end)?;
                    if initial != self.initial {
                        return Err(io::Error::other("original B Initial changed"));
                    }
                    require_files(
                        &state.files,
                        enrollment,
                        service.original_learning_unix_seconds()?,
                    )?;
                    state
                        .files
                        .admitted_protocol(&initial, service.original_learning_unix_seconds()?)?;
                    Ok(initial.head_digest.to_string())
                },
            )?;
            owner_alive(owner, end)?;
            require_files(
                &state.files,
                enrollment,
                service.original_learning_unix_seconds()?,
            )?;
            Ok(result)
        })
    }
}

impl PreparedRootIndependentBEvaluationV1 {
    pub(crate) fn original_custodian(&self) -> Arc<OriginalRootIndependentBEvaluationFilesV1> {
        Arc::clone(&self.runtime.host)
    }
    pub(crate) fn into_original_parts(
        self,
    ) -> (
        RootIndependentBEvaluationRuntimeV1,
        RootIndependentBEvaluationOfferV1,
    ) {
        (self.runtime, self.offer)
    }
}

impl RootIndependentBEvaluationRuntimeV1 {
    pub(crate) fn bind_original(
        self,
        config: &HostAuthorityServiceConfig,
        learning: &Path,
        model: Option<&Path>,
        publication: Option<&Path>,
    ) -> io::Result<BoundRootIndependentBEvaluationV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        let lanes = crate::authority_host_runtime::validate_runtime_lanes(config)?;
        let learning = learning.to_path_buf();
        let model = model.map(Path::to_path_buf);
        let publication = publication.map(Path::to_path_buf);
        let mut paths: Vec<_> = lanes.into_iter().map(|(_, path)| path).collect();
        paths.push(&learning);
        if let Some(path) = &model {
            paths.push(path);
        }
        if let Some(path) = &publication {
            paths.push(path);
        }
        paths.push(&self.bootstrap.socket);
        crate::authority_host_runtime::validate_lane_paths(&paths, config.peer_gid)?;
        let listener = UnixListener::bind(&self.bootstrap.socket)?;
        let metadata = std::fs::symlink_metadata(&self.bootstrap.socket)?;
        let bound = BoundRootIndependentBEvaluationV1 {
            runtime: self,
            listener,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("original B listener custody differs"));
        }
        std::fs::set_permissions(
            &bound.runtime.bootstrap.socket,
            std::fs::Permissions::from_mode(0o660),
        )?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }
}

impl Drop for BoundRootIndependentBEvaluationV1 {
    fn drop(&mut self) {
        self.runtime.phase.store(2, Ordering::Release);
        if std::fs::symlink_metadata(&self.runtime.bootstrap.socket)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.runtime.bootstrap.socket);
        }
    }
}

fn root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, values)| values.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("original B Root incarnation missing"))
}
