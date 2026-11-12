//! Register or reopen a Root-derived scoped profile on the retained service.
//! The caller keeps its original historical refusal context around this method.

use super::*;
use crate::authority_host_service::OriginalDerivedLearningMode;

impl HostAuthorityService {
    /// The profile comes from Root's post-freeze derivation, not peer JSON. This
    /// method deliberately owns a fresh invocation of the original writer
    /// context; callers must finish any earlier context before invoking it.
    pub(crate) fn prepare_original_derived_learning_checkpoint(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        profile: HostAuthorityLearningProfileV1,
        mode: OriginalDerivedLearningMode,
        end: Instant,
    ) -> io::Result<RegisteredHostLearningCheckpointV1> {
        require_original_end(end)?;
        if profile.schema_version != 2 || profile.update_scope.is_none() {
            return Err(io::Error::other(
                "original derived Cell learning scope required",
            ));
        }
        let (backend, socket_path) = self.with_learning_profile(
            config,
            registration,
            owner_pidfd,
            &profile,
            |initial, _| {
                require_original_end(end)?;
                let scope = profile.require_cell_scope(&initial)?;
                let binding = scope.binding();
                let socket_path = config
                    .sockets
                    .observation
                    .parent()
                    .ok_or_else(|| io::Error::other("learning socket parent required"))?
                    .join("learning-checkpoint-v1.sock");
                let mut paths: Vec<_> =
                    crate::authority_host_runtime::validate_runtime_lanes(config)?
                        .into_iter()
                        .map(|(_, path)| path)
                        .collect();
                paths.push(&socket_path);
                crate::authority_host_runtime::validate_lane_paths(&paths, config.peer_gid)?;
                let mode = match mode {
                    OriginalDerivedLearningMode::Register => StoreMode::Register,
                    OriginalDerivedLearningMode::Reopen => StoreMode::Reopen,
                };
                require_original_end(end)?;
                let backend = learning_store(&config.state_dir, &initial, mode, Some(scope))?;
                if backend.frozen_scope_binding() != Some(binding) {
                    return Err(io::Error::other(
                        "derived learning store differs from original frozen scope",
                    ));
                }
                require_original_end(end)?;
                Ok((backend, socket_path))
            },
        )?;
        // Includes the actual writer/pidfd/lease/revocation postchecks above.
        require_original_end(end)?;
        Ok(RegisteredHostLearningCheckpointV1 {
            backend: std::sync::Arc::new(backend),
            profile,
            socket_path,
            q24_model: None,
        })
    }
}

fn require_original_end(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other(
            "original derived learning registration deadline expired",
        ));
    }
    Ok(())
}
