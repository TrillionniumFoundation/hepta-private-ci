//! Capture and serve using one retained set of the original Root objects.

use super::*;

#[path = "root_agentd_filesystem.rs"]
mod filesystem;

#[path = "root_notes_startup.rs"]
mod notes_startup;

/// One Root session's immutable registration, retained actual process handle
/// and original service. This wrapper is not Clone and creates no additional
/// issuer, clock, checkpoint or consumer owner during bootstrap capture.
pub struct PreparedHostAuthoritySession {
    config: HostAuthorityServiceConfig,
    registration: HostAuthorityRegistration,
    owner_pidfd: OwnedFd,
    service: HostAuthorityService,
    fresh_filesystem: bool,
}

impl PreparedHostAuthoritySession {
    /// Explicit Root startup from the already authorized original config and
    /// actual child registration. Open the original authority owners first,
    /// then prepare/publish the fresh DB under those same owners. No issuer,
    /// policy, lease or Registry generation is created by this entry point.
    /// Existing/partial data is an error, never an automatic recovery fallback.
    pub async fn prepare_fresh_from_registered(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
        let service = open_registered_writer(&config, &registration, &owner_pidfd)?;
        let fresh =
            crate::FreshHostCognitiveState::prepare(&registration.registered_identity).await?;
        let service =
            service.initialize_fresh_heads(&config, &registration, &owner_pidfd, fresh)?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: true,
        })
    }

    /// Publish an explicitly prepared fresh original DB and fresh protected
    /// heads, retaining the same service for subsequent capture and serving.
    /// Issuer, clock, writer lease and proof must already be registered by the
    /// original administrative factories. This is never a recovery fallback.
    pub fn initialize_fresh(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
        fresh: crate::FreshHostCognitiveState,
    ) -> io::Result<Self> {
        let config = read_root_json(config_file)?;
        let registration = read_root_json(registration_file)?;
        let service = open_registered_writer(&config, &registration, &owner_pidfd)?
            .initialize_fresh_heads(&config, &registration, &owner_pidfd, fresh)?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: true,
        })
    }

    /// Open existing Root state once through the original service factory.
    /// No file, lease, signer, consumer or checkpoint is initialized here.
    pub fn open(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        let config = read_root_json(config_file)?;
        let registration = read_root_json(registration_file)?;
        let service = open_registered_service(&config, &registration, &owner_pidfd)?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: false,
        })
    }

    /// Release only the freshly published Agent's original data directories
    /// to its dedicated UID/GID. Its original Registry, lifecycle, release
    /// state and writer-lock path remain exclusively writable by Root. This
    /// first composition is restricted to one Agent; it is never a recovery
    /// fallback, recursive chown of an existing workspace or authority reset.
    /// The returned fixed parent is used by `seal_bootstrap` for the original
    /// two local FinalUse journals. Existing/partial consumer state is refused.
    pub fn handoff_fresh_agent_filesystem(mut self) -> io::Result<(Self, std::path::PathBuf)> {
        if !self.fresh_filesystem {
            return Err(io::Error::other(
                "filesystem handoff requires this session's original fresh publication",
            ));
        }
        let end = Instant::now() + std::time::Duration::from_secs(30);
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        let identity = self.registration.registered_identity.identity()?;
        let parent = filesystem::handoff_fresh_filesystem(
            &identity,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.config.state_dir,
        )?;
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        self.fresh_filesystem = false;
        Ok((self, parent))
    }

    /// Read and seal this same service's original heads, then retain it for
    /// serving. The paths/config/proof/owner cannot be replaced at this call.
    /// The returned descriptor is an observation; live owner checks remain
    /// mandatory when the daemon connects to the five original lanes.
    pub fn seal_bootstrap(&self, consumer_state_root: &Path) -> io::Result<File> {
        self.service.seal_registered_bootstrap(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            consumer_state_root,
        )
    }

    /// Trusted Root obtains this target from the original Session's Reserved
    /// capability before forwarding that same offer/endpoint to Agentd. This
    /// is a one-time startup composition, never a peer JSON registration path.
    /// The exact pre-existing issuer policy must match; no policy, issuer or
    /// lease Registry is opened or created by this method.
    pub fn with_registered_notes_from_session(
        mut self,
        target: &codex_hepta_memory::NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        let end = Instant::now() + std::time::Duration::from_secs(30);
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        self.service = self
            .service
            .with_notes_from_original_session(target, lifetime_ms)?;
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        Ok(self)
    }

    /// Consume this retained service and serve its original fixed lanes.
    pub fn serve(self) -> io::Result<()> {
        self.serve_selected(/*text_ui*/ None)
    }

    /// Serve this same retained session and the original native text lane.
    /// The original profile, peer, socket and text registration checks apply.
    pub fn serve_with_text(self, text_file: &Path, ui_pidfd: OwnedFd) -> io::Result<()> {
        self.serve_selected(Some((text_file, ui_pidfd)))
    }

    /// Launch the native UI from this SAME already prepared Root session.
    /// Fresh publication/handoff and native serving cannot reopen the exclusive
    /// clock/issuer/checkpoint owners. The original protected launch checks
    /// still run and both files must equal this retained registration/config.
    pub fn launch_native(
        self,
        config_file: &Path,
        registration_file: &Path,
        profile_file: &Path,
    ) -> io::Result<()> {
        let (config, profile) = crate::authority_host_native_launch::inputs(
            config_file,
            registration_file,
            profile_file,
            &self.owner_pidfd,
        )?;
        let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
        if serde_json::to_vec(&config).map_err(io::Error::other)?
            != serde_json::to_vec(&self.config).map_err(io::Error::other)?
            || serde_json::to_vec(&registration).map_err(io::Error::other)?
                != serde_json::to_vec(&self.registration).map_err(io::Error::other)?
        {
            return Err(io::Error::other(
                "native launch changed the retained original Root inputs",
            ));
        }
        crate::authority_host_native_launch::launch_prepared_native(
            self,
            config,
            profile,
            profile_file,
        )
    }

    fn serve_selected(self, text_ui: Option<(&Path, OwnedFd)>) -> io::Result<()> {
        let Self {
            config,
            registration,
            owner_pidfd,
            service,
            ..
        } = self;
        if text_ui.is_some()
            && config.issuer_record_profile
                != crate::authority_host_config::HostIssuerRecordProfile::TextRecovery
        {
            return Err(io::Error::other(
                "native text requires the explicit text_recovery issuer record profile",
            ));
        }
        if let Some((text_file, ui_pidfd)) = text_ui {
            let text: crate::HostAuthorityTextUiRegistration = read_root_json(text_file)?;
            if text.peer_uid != config.peer_uid {
                return Err(io::Error::other(
                    "text UI must share the registered Agentd owner UID for its existing private ingress",
                ));
            }
            text.validate(&service)?;
            let service = service.with_live_human_text(text.clone(), ui_pidfd.try_clone()?)?;
            if [
                &config.sockets.observation,
                &config.sockets.issuer,
                &config.sockets.checkpoint,
            ]
            .into_iter()
            .chain(config.sockets.device_frontier.iter())
            .chain(config.sockets.notes_frontier.iter())
            .any(|path| path == &text.socket_path)
            {
                return Err(io::Error::other("text UI requires a distinct private lane"));
            }
            std::thread::scope(|scope| {
                let worker = scope.spawn(|| {
                    service.serve_text_ui(
                        &text,
                        &ui_pidfd,
                        &owner_pidfd,
                        std::time::Duration::from_millis(config.timeout_ms),
                        std::time::Duration::from_millis(config.lifetime_ms),
                    )
                });
                let original = serve_lanes(&service, &config, &registration, &owner_pidfd);
                let ui = worker
                    .join()
                    .map_err(|_| io::Error::other("text UI lane panicked"))?;
                original.and(ui)
            })
        } else {
            serve_lanes(&service, &config, &registration, &owner_pidfd)
        }
    }
}
