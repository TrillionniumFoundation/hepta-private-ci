use super::CognitiveStore;
use super::CognitiveStoreError;
use super::capture_recovery_anchor;
use super::unavailable;
use super::verify_store;
use crate::cognitive_checkpoint::CognitiveCheckpointTransport;
use crate::cognitive_checkpoint::ProtectedCognitiveCheckpoint;
use crate::cognitive_checkpoint_wire::CognitiveCheckpointReceipt;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::sync::Arc;
use std::time::Duration;

impl CognitiveStore {
    /// Bind one independently recovered owner to its fixed protected host before
    /// constructing the ProductionDurableWriter. The expected receipt must be
    /// independently authenticated Current and must be the exact recovery input;
    /// a local hash is never a replacement for it.
    ///
    /// Consumes the sole store handle, closes the old pool, and retains its
    /// original exclusive recovery guard. The returned checkpoint and store
    /// share one whole-pool gate. Clones of the returned store are supported;
    /// binding legacy/shared stores or creating a second coordinator is refused.
    pub async fn bind_protected_checkpoint<T: CognitiveCheckpointTransport + 'static>(
        mut self,
        transport: Arc<T>,
        expected_current: CognitiveCheckpointReceipt,
        deadline: Duration,
    ) -> Result<(Self, Arc<ProtectedCognitiveCheckpoint<T>>), CognitiveStoreError> {
        let exclusive = self
            ._open_guard
            .as_ref()
            .is_some_and(|guard| guard.exclusive && Arc::strong_count(guard) == 1);
        if !exclusive || self.commit_gate.is_managed() {
            return Err(CognitiveStoreError::Invalid(
                "protected checkpoint requires the sole exclusively recovered owner before writer creation"
                    .to_string(),
            ));
        }
        self.commit_gate.require_open()?;
        if expected_current.head.owner_agent_id != self.owner_agent_id {
            return Err(CognitiveStoreError::Invalid(
                "protected checkpoint owner differs from the recovered store".to_string(),
            ));
        }
        let expected_cut = expected_current.head.last_current.clone();
        let coordinator = Arc::new(
            ProtectedCognitiveCheckpoint::new(
                transport,
                expected_current,
                self.commit_gate.clone(),
                deadline,
            )
            .map_err(unavailable)?,
        );
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        self.commit_gate.manage_commits();
        let attempt = self.commit_gate.checkpoint_attempt();
        if capture_recovery_anchor(&mut transaction, &self.owner_agent_id).await? != expected_cut {
            return Err(CognitiveStoreError::Invalid(
                "protected Current does not match the exact recovered owner cut".to_string(),
            ));
        }
        coordinator.verify_initial().await.map_err(unavailable)?;
        transaction.rollback().await.map_err(unavailable)?;
        self.pool.close().await;
        let root = self.path.parent().ok_or_else(|| {
            CognitiveStoreError::Invalid("recovered database has no parent".to_string())
        })?;
        let sqlite_home = AbsolutePathBuf::try_from(root.to_path_buf()).map_err(unavailable)?;
        let connection_gate = self.commit_gate.clone();
        let checkout_coordinator = Arc::clone(&coordinator);
        let config = SqliteConfig::from_sqlite_home(sqlite_home);
        self.pool = config
            .open_coordinated_durable_evidence_pool(
                &self.path,
                move || connection_gate.commit_allowed(),
                move || {
                    let coordinator = Arc::clone(&checkout_coordinator);
                    async move { coordinator.before_checkout().await }
                },
            )
            .await
            .map_err(unavailable)?;
        self.commit_gate.require_open()?;
        verify_store(&self.pool, &self.owner_agent_id).await?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let reopened = capture_recovery_anchor(&mut transaction, &self.owner_agent_id).await?;
        transaction.rollback().await.map_err(unavailable)?;
        if reopened != expected_cut {
            return Err(CognitiveStoreError::Invalid(
                "recovered owner changed while its guarded pool was bound".to_string(),
            ));
        }
        self.observation_pool = Some(
            config
                .open_durable_observation_pool(&self.path)
                .await
                .map_err(unavailable)?,
        );
        if self.recovery_anchor().await? != expected_cut {
            return Err(CognitiveStoreError::Invalid(
                "read-only observer differs from the recovered owner cut".to_string(),
            ));
        }
        self.bound_publication = Some(coordinator.clone());
        attempt.acknowledge();
        Ok((self, coordinator))
    }
}
