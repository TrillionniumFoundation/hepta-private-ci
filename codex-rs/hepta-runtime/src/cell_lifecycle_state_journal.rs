//! V2 material checks compose with the existing lifecycle journal. There is no
//! second writer, durable log or native execution callback in this profile.

use crate::RuntimeCellLifecycleAnchorStoreV1;
use crate::RuntimeCellLifecycleError;
use crate::RuntimeCellLifecycleIntentV1;
use crate::RuntimeCellLifecycleJournalV1;
use crate::RuntimeCellLifecycleObservationV1;
use crate::RuntimeCellLifecycleObserverV1;
use crate::RuntimeCellLifecycleSnapshotV1;
use crate::cell_lifecycle_state::RuntimeCellLifecyclePlanV2;

impl RuntimeCellLifecyclePlanV2<'_> {
    /// Recover only this frozen complete-state profile. All retained observation
    /// bundles are checked before acknowledging an uncertain journal suffix;
    /// the original observer still reauthenticates its native outcome. Recovery
    /// never executes a lifecycle stage or creates another operation identity.
    pub async fn recover<A: RuntimeCellLifecycleAnchorStoreV1>(
        &self, pool: sqlx::SqlitePool, writer_epoch: u64, anchor: A, max_events: u64,
        observer: &impl RuntimeCellLifecycleObserverV1,
    ) -> Result<RuntimeCellLifecycleJournalV1<A>, RuntimeCellLifecycleError> {
        self.validate()?;
        RuntimeCellLifecycleJournalV1::recover_with_profile(
            pool, self.plan, writer_epoch, anchor, max_events, observer,
            |observation| self.validate_observed_bundle(observation),
        ).await
    }

    /// Freeze the complete candidate through the original journal and anchor.
    pub async fn create<A: RuntimeCellLifecycleAnchorStoreV1>(
        &self, journal: &mut RuntimeCellLifecycleJournalV1<A>, now_ms: u64,
    ) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
        self.validate()?;
        journal.create(self.plan, now_ms).await
    }

    /// Check the exact frozen bytes before recording any next-stage intent.
    pub async fn prepare_next<A: RuntimeCellLifecycleAnchorStoreV1>(
        &self, journal: &mut RuntimeCellLifecycleJournalV1<A>, expected_revision: u64, now_ms: u64,
    ) -> Result<RuntimeCellLifecycleIntentV1, RuntimeCellLifecycleError> {
        self.validate()?;
        journal.prepare_next(self.plan, expected_revision, now_ms).await
    }

    /// Material integrity never substitutes for independently authenticated
    /// native observation. UNKNOWN effects remain pending under the same ID.
    pub async fn record_observation<A: RuntimeCellLifecycleAnchorStoreV1>(
        &self, journal: &mut RuntimeCellLifecycleJournalV1<A>, expected_revision: u64,
        observation: RuntimeCellLifecycleObservationV1, observer: &impl RuntimeCellLifecycleObserverV1,
    ) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
        self.validate()?;
        self.validate_observed_bundle(&observation)?;
        journal.record_observation(self.plan, expected_revision, observation, observer).await
    }
}
