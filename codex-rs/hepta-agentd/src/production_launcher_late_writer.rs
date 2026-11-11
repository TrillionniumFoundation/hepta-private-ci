//! Original non-Root entry after a real Supervisor Starting transition.
//! No cached launch, writer proof, Root session or retained Config is revived.

use super::*;

impl AgentdProductionLaunch {
    /// Receive a new launch in the already dedicated non-Root recipient of a
    /// real Supervisor Starting admission. This adapter does not retire an old
    /// peer, create Starting, or carry an earlier process's retained capabilities.
    /// The trusted host must already have performed the original writer admission.
    ///
    /// The existing argument parser still requires the actual selected primary
    /// runtime and distinct inherited descriptors. For this explicit entry,
    /// `--root-production-handoff-fd` carries the original THREE-right writer
    /// purpose; the ordinary two-right bootstrap is never a fallback.
    ///
    /// `expected` is only an exact identity comparison. Actual authority comes
    /// from the original sealed handoff, live five-lane session and Root0600
    /// writer descriptor. A refusal or cancellation consumes this attempt.
    pub async fn receive_original_late_writer(
        arguments: Vec<OsString>,
        expected: &AgentdIdentity,
    ) -> Result<(AgentdConfig, Self, Vec<OsString>), AgentdError> {
        let (selected, ordinary) = inputs::parse(arguments)?;
        let LaunchInputs {
            handoff,
            learning_handoff,
            q24_model_handoff,
            publication_handoff,
            initial_handoff,
            uid,
            gid,
            control,
            app_server,
            primary,
            bootstrap_deadline,
            notes,
            notes_ui,
            lifetime,
        } = selected.ok_or_else(|| {
            AgentdError::Invalid("original late writer requires a complete production launch".into())
        })?;
        require_late_owner(uid, gid)?;
        let session_end = Instant::now() + lifetime;
        let (bootstrap, root_pidfd, writer) = crate::receive_root_production_writer_handoff(
            handoff,
            remaining(bootstrap_deadline)?,
        )?;
        let learning = learning_handoff
            .map(|handoff| {
                crate::receive_root_learning_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )
            })
            .transpose()?;
        let q24_model = q24_model_handoff
            .map(|handoff| {
                crate::receive_root_q24_model_factory_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )
            })
            .transpose()?;
        let publication = publication_handoff
            .map(|handoff| {
                crate::receive_root_generation_publication_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )
            })
            .transpose()?;
        let initial_publication = initial_handoff
            .map(|handoff| {
                crate::receive_root_generation_initial_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )
            })
            .transpose()?;
        // Preserve the original accept barrier: all five actual lanes precede
        // writer loading and any optional learning/Model exchange.
        let root = crate::receive_root_production_inputs(
            bootstrap,
            root_pidfd,
            expected,
            remaining(bootstrap_deadline)?.min(Duration::from_millis(500)),
            original_session_remaining(session_end)?,
        )
        .await?;
        let mut config = AgentdConfig::from_root_writer_handoff(
            &root,
            writer,
            std::env::current_dir()?,
        )?
        .with_root_bound_sockets(control, app_server)?;
        if config.identity() != expected {
            return Err(AgentdError::GenerationFenced(
                "late writer loaded another original Starting identity".into(),
            ));
        }
        let mut model_factory = None;
        if let Some(learning) = learning {
            let learning: crate::RootLearningHandoffV1 = learning;
            let inputs = learning
                .connect(
                    &root,
                    config.identity(),
                    remaining(bootstrap_deadline)?.min(Duration::from_millis(500)),
                    original_session_remaining(session_end)?,
                )
                .await?;
            if let Some(model) = q24_model {
                let model: crate::RootQ24ModelFactoryHandoffV1 = model;
                model_factory = Some(
                    model
                        .connect(
                            &root,
                            &inputs,
                            config.identity(),
                            remaining(bootstrap_deadline)?.min(Duration::from_millis(500)),
                            original_session_remaining(session_end)?,
                        )
                        .await?,
                );
            }
            config = config.with_root_learning_inputs(inputs)?;
        }
        require_late_owner(uid, gid)?;
        remaining(bootstrap_deadline)?;
        original_session_remaining(session_end)?;
        root.session
            .verifier()
            .verify_sender_process_binding(
                &root.session.authority(),
                &config.identity().agent_id,
                &root.bootstrap.writer.local_lease_id,
                root.bootstrap.writer.local_lease_generation,
                config.identity().spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        Ok((
            config,
            Self {
                root,
                inputs: RuntimeInputs {
                    primary,
                    notes,
                    notes_ui,
                },
                q24_model: model_factory,
                publication,
                initial_publication,
            },
            ordinary,
        ))
    }
}

fn require_late_owner(uid: u32, gid: u32) -> Result<(), AgentdError> {
    // SAFETY: these calls only read this process's actual kernel credentials.
    let actual = unsafe {
        (
            libc::getuid(),
            libc::geteuid(),
            libc::getgid(),
            libc::getegid(),
        )
    };
    if uid == 0 || gid == 0 || actual != (uid, uid, gid, gid) {
        return Err(AgentdError::Invalid(
            "late writer requires its already dedicated actual non-Root owner".into(),
        ));
    }
    Ok(())
}

fn original_session_remaining(deadline: Instant) -> Result<Duration, AgentdError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
        .ok_or_else(|| AgentdError::Protocol("original late Root session lifetime expired".into()))
}

#[cfg(test)]
#[path = "production_launcher_late_writer_tests.rs"]
mod tests;
