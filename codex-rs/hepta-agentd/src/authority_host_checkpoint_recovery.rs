//! Retained same-boot admission for the original expired Current CAS.
use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;

impl HostCognitiveCheckpoint {
    /// Historical read after this publisher retired. A closed live transport is
    /// never reopened: only its complete durable Current can be observed. The
    /// Root caller separately checks its held pidfd and full millisecond lease.
    pub(crate) fn current_for_retired_capture(
        &self,
        registration: &HostCognitiveCheckpointRegistration,
    ) -> Result<CognitiveCheckpointReceipt, AuthorityTrustError> {
        let _guard = self
            .exchange_lock
            .try_lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if registration != &self.registration {
            return Err(AuthorityTrustError::Invalid);
        }
        let head = self.load()?;
        let expiry = head
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1000)
            .ok_or(AuthorityTrustError::Invalid)?;
        if head.phase != CognitiveCheckpointPhase::Current || self.clock.now_unix_ms()? < expiry {
            return Err(AuthorityTrustError::Invalid);
        }
        let retired = RetiredCheckpointPublisher::observe(head.peer_lifetime.clone())?;
        let token = token_for(&head)?;
        if self.load()? != head {
            return Err(AuthorityTrustError::Conflict);
        }
        retired.require_retired()?;
        Ok(CognitiveCheckpointReceipt { head, token })
    }
}

/// Captured from the actual protected predecessor before any writer rotation.
/// The value retains the original store, clock, receipt and kernel retirement
/// proof. It cannot be reconstructed from successor JSON after an uncertain CAS.
pub(crate) struct RetiredCurrentRecovery {
    directory: Arc<RootAuthorityDirectory>,
    previous: CognitiveCheckpointReceipt,
    predecessor: RetiredCheckpointPublisher,
    clock: Arc<dyn AuthorityClock>,
}

impl RetiredCurrentRecovery {
    pub(crate) fn capture(
        directory: Arc<RootAuthorityDirectory>,
        previous: CognitiveCheckpointReceipt,
        registration: HostCognitiveCheckpointRegistration,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        let old = HostCognitiveCheckpoint::open(directory.clone(), registration, clock.clone())?;
        let head = old.load()?;
        if head != previous.head
            || token_for(&head)? != previous.token
            || head.phase != CognitiveCheckpointPhase::Current
            || clock.now_unix_ms()? < head.writer_binding.expires_at_unix_seconds * 1000
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let predecessor = RetiredCheckpointPublisher::observe(head.peer_lifetime.clone())?;
        if old.load()? != head {
            return Err(AuthorityTrustError::Conflict);
        }
        Ok(Self {
            directory,
            previous,
            predecessor,
            clock,
        })
    }

    /// The caller must hold the new writer's original Registry dispatch fence.
    /// Retry uses this same retained predecessor and the exact same successor.
    /// An already-adopted head is read back, never promoted from Dirty or reset.
    pub(crate) fn adopt_or_reconcile(
        &self,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
    ) -> Result<HostCognitiveCheckpoint, AuthorityTrustError> {
        let next = adoption::adopted_head(
            &self.previous,
            &self.predecessor.lifetime,
            &registration,
            &successor.lifetime,
        )?;
        self.predecessor.require_retired()?;
        successor.require_alive()?;
        if self.clock.now_unix_ms()?
            < self.previous.head.writer_binding.expires_at_unix_seconds * 1000
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            self.directory.clone(),
            STORE_OWNER.into(),
        )?;
        let actual = store.load(STORE_OWNER)?;
        if actual == self.previous.head {
            return HostCognitiveCheckpoint::adopt_current_after_root_restart(
                self.directory.clone(),
                &self.previous,
                &self.predecessor,
                registration,
                successor,
                self.clock.clone(),
            );
        }
        if actual != next {
            return Err(AuthorityTrustError::Conflict);
        }
        let reconciled = HostCognitiveCheckpoint::open(
            self.directory.clone(),
            registration,
            self.clock.clone(),
        )?;
        if reconciled.current_for_handoff()? != next {
            return Err(AuthorityTrustError::Unavailable);
        }
        self.predecessor.require_retired()?;
        successor.require_alive()?;
        Ok(reconciled)
    }
}
