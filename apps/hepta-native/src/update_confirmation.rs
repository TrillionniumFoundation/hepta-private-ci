//! Candidate readiness and helper acknowledgement share one durable owner fence.
use super::PendingUpdateStatus;
use super::UpdateManager;
use super::transition_pending;
use super::validate_running_handoff;
use crate::error::ShellError;
use crate::update_handoff::UpdateHandoff;
use crate::update_handoff::UpdateReadiness;
use crate::update_storage::lock_update_handoff;
use crate::update_storage::lock_update_root;
use crate::update_storage::persist_json_atomic;

impl UpdateManager {
    /// Fence an unsuccessful startup before terminating its process. `true`
    /// means cancellation won the owner transaction; `false` means the candidate
    /// already committed confirmation and the helper must leave it running.
    pub fn cancel_unconfirmed_restart(&self, handoff: &UpdateHandoff) -> Result<bool, ShellError> {
        self.cancel_at_boundary(handoff, || Ok(()))
    }

    pub(super) fn cancel_at_boundary(
        &self,
        handoff: &UpdateHandoff,
        observe: impl FnOnce() -> Result<(), ShellError>,
    ) -> Result<bool, ShellError> {
        let _lock = lock_update_handoff(&self.private_root)?;
        let mut pending = self
            .load_pending()?
            .ok_or_else(|| ShellError::Update("missing pending restart cancellation".into()))?;
        if pending.handoff.as_ref() != Some(handoff) {
            return Err(ShellError::Update(
                "restart cancellation handoff changed".into(),
            ));
        }
        if pending.status == PendingUpdateStatus::Confirmed {
            return Ok(false);
        }
        if pending.status == PendingUpdateStatus::RollbackStarted {
            return Ok(true);
        }
        if pending.status != PendingUpdateStatus::ActivatedUnconfirmed {
            return Err(ShellError::Update(
                "restart cancellation lacks an unconfirmed candidate".into(),
            ));
        }
        observe()?;
        transition_pending(
            &self.private_root,
            &self.pending_path(),
            &mut pending,
            PendingUpdateStatus::RollbackStarted,
            Some("candidate startup acknowledgement was abandoned".into()),
        )?;
        Ok(true)
    }

    pub(crate) fn confirm_running_process(
        &self,
        handoff: &UpdateHandoff,
        session: &crate::model::SessionIncarnation,
        view: &crate::model::RuntimeView,
    ) -> Result<(), ShellError> {
        let lock = lock_update_root(&self.private_root)?;
        let mut pending = self
            .load_pending()?
            .ok_or_else(|| ShellError::Update("missing pending activation".into()))?;
        validate_running_handoff(&pending, handoff)?;
        session.validate()?;
        view.validate()?;
        if view.session_id != session.session_id || view.session_generation != session.generation {
            return Err(ShellError::Update(
                "update readiness has mixed session identity".into(),
            ));
        }
        pending.readiness = Some(UpdateReadiness {
            process_id: std::process::id(),
            session: session.clone(),
            view_digest: view.digest.clone(),
            view_revision: view.revision,
            binary_digest: pending.manifest.package_digest.clone(),
        });
        // Readiness alone does not make the update terminal: a helper that
        // disappears before its acknowledgement must still leave recoverable
        // activation state. The stdin watcher commits only after observing C.
        persist_json_atomic(&self.private_root, &self.pending_path(), &pending)?;
        drop(lock);
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            let current = self.load_pending()?.ok_or_else(|| {
                ShellError::Update("pending update disappeared before acknowledgement".into())
            })?;
            if current.handoff.as_ref() != Some(handoff)
                || current
                    .readiness
                    .as_ref()
                    .is_none_or(|ready| ready.process_id != std::process::id())
            {
                return Err(ShellError::Update(
                    "update readiness changed before acknowledgement".into(),
                ));
            }
            if current.status == PendingUpdateStatus::Confirmed {
                return Ok(());
            }
            if current.status != PendingUpdateStatus::ActivatedUnconfirmed {
                return Err(ShellError::Update(
                    "helper did not acknowledge product readiness".into(),
                ));
            }
            if std::time::Instant::now() >= deadline {
                // A concurrent C may already have committed confirmation. Fence
                // the losing branch before the GUI handles a readiness failure.
                if !self.cancel_unconfirmed_restart(handoff)? {
                    return Ok(());
                }
                return Err(ShellError::Update(
                    "helper did not acknowledge product readiness".into(),
                ));
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }

    pub(crate) fn acknowledge_running_process(
        &self,
        handoff: &UpdateHandoff,
    ) -> Result<(), ShellError> {
        self.acknowledge_at_boundary(handoff, || Ok(()))
    }

    pub(super) fn acknowledge_at_boundary(
        &self,
        handoff: &UpdateHandoff,
        observe: impl FnOnce() -> Result<(), ShellError>,
    ) -> Result<(), ShellError> {
        let _lock = lock_update_handoff(&self.private_root)?;
        let mut pending = self
            .load_pending()?
            .ok_or_else(|| ShellError::Update("missing pending acknowledgement".into()))?;
        validate_running_handoff(&pending, handoff)?;
        if pending
            .readiness
            .as_ref()
            .is_none_or(|ready| ready.process_id != std::process::id())
        {
            return Err(ShellError::Update(
                "helper acknowledgement lacks process-bound readiness".into(),
            ));
        }
        observe()?;
        transition_pending(
            &self.private_root,
            &self.pending_path(),
            &mut pending,
            PendingUpdateStatus::Confirmed,
            None,
        )
    }
}
