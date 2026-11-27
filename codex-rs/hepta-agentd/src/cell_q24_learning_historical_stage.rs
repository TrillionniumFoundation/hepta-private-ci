//! The original aggregate's bounded lane encloses one complete historical
//! stage. The borrowed source and Trainer never leave this blocking thread.

use super::historical_operation::OriginalQ24StageOperationV1;
use super::*;
use crate::learning_iteration::historical_context::OriginalHistoricalStageAdmissionV1;
use crate::learning_iteration::historical_context::OriginalHistoricalStageContextV1;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) async fn run_original_historical_stage(
        &self,
        context: Arc<OriginalHistoricalStageContextV1>,
        work: OriginalHistoricalWorkV1,
    ) -> Result<OriginalHistoricalResultV1, Error> {
        context.require_original_aggregate(self)?;
        if self.inner.cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        let permit = Arc::clone(&self.inner.lane)
            .try_acquire_owned()
            .map_err(|_| Error::CommitUncertain)?;
        let mut fence = FenceAggregateOnDrop {
            cancelled: Arc::clone(&self.inner.cancelled),
            armed: true,
        };
        let inner = Arc::clone(&self.inner);
        let runtime = Handle::current();
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if inner.cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            let mut locked = inner
                .owners
                .try_lock()
                .map_err(|_| Error::CommitUncertain)?;
            let owners: &mut Q24StageOwners = &mut locked;
            CellQ24PreparedLearningV1::with_original_prepared_operation(&inner.prepared, |read| {
                context.require_in_operation(read, OriginalHistoricalStageAdmissionV1::ReadOnly)?;
                runtime
                    .block_on(crate::AgentdRootQ24ModelFactoryV1::require_current(
                        &mut owners.factory,
                    ))
                    .map_err(unavailable)?;
                if inner.cancelled.load(Ordering::Acquire) {
                    return Err(Error::CommitUncertain);
                }
                let result = OriginalCellQ24TrainingStageV1::with_original_training_operation(
                    &inner.training,
                    &inner.dataset_cut,
                    read,
                    |training| {
                        let mut operation = OriginalQ24StageOperationV1::from_original(
                            &inner,
                            owners,
                            &runtime,
                            training,
                            read,
                            context.as_ref(),
                        )?;
                        OriginalQ24StageOperationV1::run(&mut operation, work)
                    },
                );
                // A failed owner call still receives the actual source, state,
                // factory and cancellation postchecks before the lane leaves.
                context.require_in_operation(read, OriginalHistoricalStageAdmissionV1::ReadOnly)?;
                runtime
                    .block_on(crate::AgentdRootQ24ModelFactoryV1::require_current(
                        &mut owners.factory,
                    ))
                    .map_err(unavailable)?;
                if inner.cancelled.load(Ordering::Acquire) {
                    return Err(Error::CommitUncertain);
                }
                result
            })
            .map_err(unavailable)?
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        if result.is_ok() {
            fence.armed = false;
        }
        result
    }
}
