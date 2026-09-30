use std::collections::BTreeMap;

use codex_hepta_types::StableId;

use super::FederationClientError;
use super::FederationWireClientV1;
use super::snapshot::ClientAttemptIdentity;
use super::snapshot::ClientAttemptMetadata;
use super::snapshot::encode_client_snapshot;
use super::snapshot::retain_live_attempts;
use crate::protocol::AuthenticatedFrontierV1;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryStoreV1;
use crate::replay::ReplayCacheV1;

impl<S> FederationWireClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    /// Persist one bounded expiry-maintenance quantum independently of any
    /// request. Failed admission cleanup is intentionally rolled back; this
    /// owner entrypoint makes progress without replaying a query. Derived client
    /// metadata is reconciled by the existing atomic state replacement.
    pub fn maintain_expired(&mut self, now_unix_ms: u64) -> Result<usize, FederationClientError> {
        let maximum = crate::recovery::FEDERATION_RECOVERY_CLEANUP_BATCH;
        let before = self.recovery.replay_len() + self.recovery.attempt_len();
        let next = self.recovery.stage_maintenance_at(now_unix_ms, maximum)?;
        let removed = before - next.replay_len() - next.attempt_len();
        let mut replay = self.replay.clone();
        let live_removed =
            replay.purge_expired_bounded(now_unix_ms, maximum.saturating_sub(removed))?;
        self.replace_state_and_replay(next, self.attempts.clone(), self.frontiers.clone(), replay)?;
        Ok(removed + live_removed)
    }

    pub fn recovery_snapshot(&self) -> Result<Vec<u8>, FederationClientError> {
        encode_client_snapshot(
            &self.local_peer_id,
            self.limits,
            self.recovery.snapshot_bytes()?,
            &self.attempts,
            &self.frontiers,
        )
    }

    pub fn last_frontier(&self, peer_id: &StableId) -> Option<&AuthenticatedFrontierV1> {
        self.frontiers.get(peer_id.as_str())
    }

    pub(super) fn clone_recovery(
        &self,
        now_unix_ms: u64,
    ) -> Result<DurableFederationStateV1, FederationClientError> {
        Ok(self.recovery.stage_at(now_unix_ms)?)
    }

    pub(super) fn replace_state(
        &mut self,
        next: DurableFederationStateV1,
        attempts: BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
        frontiers: BTreeMap<String, AuthenticatedFrontierV1>,
    ) -> Result<(), FederationClientError> {
        self.replace_state_and_replay(next, attempts, frontiers, self.replay.clone())
    }

    pub(super) fn replace_state_and_replay(
        &mut self,
        next: DurableFederationStateV1,
        mut attempts: BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
        frontiers: BTreeMap<String, AuthenticatedFrontierV1>,
        replay: ReplayCacheV1,
    ) -> Result<(), FederationClientError> {
        retain_live_attempts(&next, &mut attempts);
        let snapshot = encode_client_snapshot(
            &self.local_peer_id,
            self.limits,
            next.snapshot_bytes()?,
            &attempts,
            &frontiers,
        )?;
        self.recovery_store.store(&snapshot)?;
        self.recovery = next;
        self.attempts = attempts;
        self.frontiers = frontiers;
        self.replay = replay;
        Ok(())
    }

    pub(super) fn persist_current(&mut self) -> Result<(), FederationClientError> {
        let snapshot = self.recovery_snapshot()?;
        self.recovery_store.store(&snapshot)?;
        Ok(())
    }
}
