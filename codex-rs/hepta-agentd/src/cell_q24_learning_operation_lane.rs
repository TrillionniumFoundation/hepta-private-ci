//! One natural owner operation borrows one original Prepared source. Its two
//! actual Root reads surround all work and postchecks, including failed work.

use super::*;
use crate::cell_composed_q24::OriginalPreparedReadV1;

impl Q24StageState {
    pub(super) async fn in_original_prepared_lane<T>(
        self: &Arc<Self>,
        work: impl for<'read> FnOnce(
            &mut Q24StageOwners,
            &Handle,
            &OriginalPreparedReadV1<'read>,
        ) -> Result<T, Error>
        + Send
        + 'static,
    ) -> Result<T, Error>
    where
        T: Send + 'static,
    {
        if self.cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::CommitUncertain)?;
        let mut fence = FenceAggregateOnDrop {
            cancelled: Arc::clone(&self.cancelled),
            armed: true,
        };
        let inner = Arc::clone(self);
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
                OriginalPreparedReadV1::require_prepared(read, &inner.prepared)
                    .map_err(unavailable)?;
                runtime
                    .block_on(crate::AgentdRootQ24ModelFactoryV1::require_current(
                        &mut owners.factory,
                    ))
                    .map_err(unavailable)?;
                if inner.cancelled.load(Ordering::Acquire) {
                    return Err(Error::CommitUncertain);
                }
                let result = work(owners, &runtime, read);
                OriginalPreparedReadV1::require_prepared(read, &inner.prepared)
                    .map_err(unavailable)?;
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

    pub(super) fn has_original_root_evaluation(&self) -> Result<bool, Error> {
        let owners = self.owners.try_lock().map_err(|_| Error::CommitUncertain)?;
        Ok(owners.root_evaluation.is_some())
    }
}
