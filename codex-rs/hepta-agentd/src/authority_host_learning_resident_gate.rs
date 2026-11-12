//! Non-cloneable execution custody for one fresh admitted future.
//! Each check is a point-in-time Root fence, not a lock held over network I/O.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;

use super::authority::ResidentRootAuthorityV3;
use super::authority::ResidentStoreActionV3;
use super::authority::ResidentStoreValueV3;
use super::store::FreshResidentCheckpointV3;
use super::store::ResidentCheckpointV3;
use super::store::ResidentSnapshotV3;
use crate::LearningIterationRuntimeErrorV1 as Error;

pub(super) struct ResidentRegisteredStateV3 {
    pub(super) authority: Arc<ResidentRootAuthorityV3>,
    pub(super) checkpoint: Arc<ResidentCheckpointV3>,
    lane: Arc<Semaphore>,
}

impl ResidentRegisteredStateV3 {
    pub(super) fn new(authority: ResidentRootAuthorityV3, checkpoint: ResidentCheckpointV3) -> Self {
        Self { authority: Arc::new(authority), checkpoint: Arc::new(checkpoint),
            lane: Arc::new(Semaphore::new(1)) }
    }

    pub(super) async fn read(
        self: &Arc<Self>,
        cancellation: &CancellationToken,
    ) -> Result<(ResidentSnapshotV3, u64), Error> {
        let permit = tokio::time::timeout(Duration::from_secs(2),
            Arc::clone(&self.lane).acquire_owned()).await
            .map_err(|_| Error::Unavailable)?
            .map_err(|_| Error::Unavailable)?;
        let owner = Arc::clone(self);
        let cancellation = cancellation.clone();
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let result = owner.authority.perform(
                ResidentStoreActionV3::Read(&owner.checkpoint), &cancellation,
            ).map_err(|_| Error::Unavailable)?;
            match result.value {
                ResidentStoreValueV3::Snapshot(snapshot) => Ok((snapshot, result.now_ms)),
                _ => Err(Error::Unavailable),
            }
        }).await.map_err(|_| Error::Unavailable)?
    }

    pub(super) async fn admit(
        self: &Arc<Self>,
        cancellation: &CancellationToken,
    ) -> Result<Option<ResidentContinuationV3>, Error> {
        let permit = tokio::time::timeout(Duration::from_secs(2),
            Arc::clone(&self.lane).acquire_owned()).await
            .map_err(|_| Error::Unavailable)?
            .map_err(|_| Error::Unavailable)?;
        let owner = Arc::clone(self);
        let original_cancellation = cancellation.clone();
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let result = owner.authority.perform(
                ResidentStoreActionV3::Admit(&owner.checkpoint), &original_cancellation,
            ).map_err(|_| Error::CommitUncertain)?;
            match result.value {
                ResidentStoreValueV3::Fresh(fresh) => Ok(fresh),
                _ => Err(Error::CommitUncertain),
            }
        }).await.map_err(|_| Error::CommitUncertain)??;
        if cancellation.is_cancelled() {
            return Err(Error::CommitUncertain);
        }
        Ok(result.map(|fresh| ResidentContinuationV3 {
            gate: Arc::new(RootResidentLearningEffectGateV3 {
                inner: Arc::new(ResidentExecutionV3 {
                    owner: Arc::clone(self), fresh: Mutex::new(fresh),
                    active: AtomicBool::new(true), cancellation: cancellation.child_token(),
                    dispatch_cancel: Arc::new(AtomicBool::new(false)),
                }),
            }),
        }))
    }
}

struct ResidentExecutionV3 {
    owner: Arc<ResidentRegisteredStateV3>,
    fresh: Mutex<FreshResidentCheckpointV3>,
    active: AtomicBool,
    dispatch_cancel: Arc<AtomicBool>,
    cancellation: CancellationToken,
}

/// No public constructor, Clone, Deserialize, caller callback, or boolean tag.
/// Only ResidentRegisteredStateV3::admit after its actual successful CAS creates
/// the gate, and only the same resident future retains its continuation guard.
pub(crate) struct RootResidentLearningEffectGateV3 {
    inner: Arc<ResidentExecutionV3>,
}

pub(super) struct ResidentContinuationV3 {
    pub(super) gate: Arc<RootResidentLearningEffectGateV3>,
}

impl Drop for ResidentContinuationV3 {
    fn drop(&mut self) {
        self.gate.fence();
    }
}

enum GateActionV3 {
    Current,
    Begin(LearningIterationStageV1),
    Checkpoint(LearningIterationSnapshotV1),
}

impl RootResidentLearningEffectGateV3 {
    /// The predecessor is the complete current cut for this actual effect, not
    /// merely the empty initial cut. The original root record must contain the
    /// same bytes and pending (head, next-stage) intent at this fresh read.
    pub(crate) async fn require_current(
        &self,
        predecessor: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        if scope != &self.inner.owner.authority.profile.scope {
            self.fence();
            return Err(Error::WrongScope);
        }
        self.local(GateActionV3::Current, predecessor).await.map(|_| ())
    }

    pub(super) async fn begin(
        &self,
        predecessor: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> Result<u64, Error> {
        self.local(GateActionV3::Begin(stage), predecessor).await
    }

    pub(super) async fn checkpoint(
        &self,
        predecessor: &LearningIterationSnapshotV1,
        next: LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        self.local(GateActionV3::Checkpoint(next), predecessor).await.map(|_| ())
    }

    pub(super) fn cancellation(&self) -> &CancellationToken {
        &self.inner.cancellation
    }

    /// The existing Trainer client samples this same flag at its final local
    /// send boundary. It does not cancel an already accepted remote job.
    pub(crate) fn training_cancellation(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.inner.dispatch_cancel)
    }

    fn fence(&self) {
        self.inner.dispatch_cancel.store(true, Ordering::Release);
        self.inner.active.store(false, Ordering::Release);
        self.inner.cancellation.cancel();
    }

    async fn local(
        &self,
        action: GateActionV3,
        predecessor: &LearningIterationSnapshotV1,
    ) -> Result<u64, Error> {
        let profile = &self.inner.owner.authority.profile;
        if !self.inner.active.load(Ordering::Acquire)
            || self.inner.cancellation.is_cancelled()
            || predecessor.request != profile.initial.request
            || predecessor.owners != profile.initial.owners
            || profile.scope.validate_snapshot(predecessor).is_err()
        {
            self.fence();
            return Err(Error::CommitUncertain);
        }
        let result = self.local_inner(action, predecessor.clone()).await;
        if result.is_err() || self.inner.cancellation.is_cancelled() {
            self.fence();
            return Err(Error::CommitUncertain);
        }
        result
    }

    async fn local_inner(
        &self,
        action: GateActionV3,
        predecessor: LearningIterationSnapshotV1,
    ) -> Result<u64, Error> {
        let permit = tokio::time::timeout(Duration::from_secs(2),
            Arc::clone(&self.inner.owner.lane).acquire_owned()).await
            .map_err(|_| Error::CommitUncertain)?
            .map_err(|_| Error::CommitUncertain)?;
        let inner = Arc::clone(&self.inner);
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if !inner.active.load(Ordering::Acquire) || inner.cancellation.is_cancelled() {
                return Err(Error::CommitUncertain);
            }
            let mut fresh = inner.fresh.try_lock().map_err(|_| Error::CommitUncertain)?;
            let owner = &inner.owner.checkpoint;
            let operation = match &action {
                GateActionV3::Current => ResidentStoreActionV3::RequireDispatch(
                    owner, &fresh, &predecessor,
                ),
                GateActionV3::Begin(stage) => ResidentStoreActionV3::Begin(
                    owner, &mut fresh, &predecessor, *stage,
                ),
                GateActionV3::Checkpoint(next) => ResidentStoreActionV3::Checkpoint(
                    owner, &mut fresh, &predecessor, next,
                ),
            };
            let boundary = inner.owner.authority.perform(operation, &inner.cancellation)
                .map_err(|_| Error::CommitUncertain)?;
            if !inner.active.load(Ordering::Acquire) || inner.cancellation.is_cancelled() {
                return Err(Error::CommitUncertain);
            }
            Ok(boundary.now_ms)
        }).await.map_err(|_| Error::CommitUncertain)?
    }
}
