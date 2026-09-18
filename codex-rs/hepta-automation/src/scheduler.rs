use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use tokio::time::timeout;

use crate::AutomationAdmission;
use crate::AutomationError;
use crate::AutomationQueueReceipt;
use crate::AutomationStore;
use crate::AutomationTick;
use crate::admission_receipt_digest;

pub type AutomationFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, AutomationError>> + Send + 'a>>;

/// The only Codex admission seam available to the timer scheduler.
///
/// Product implementations must use the owning Agent's durable App Server
/// thread queue. `thread/queue/reconcile` is preferred because it atomically
/// binds a stable client id and canonical payload to an existing queued or
/// persisted Core record. The scheduler cannot call a model, tool, or another
/// Agent directly. Failures after possible admission must be reported as
/// `DispatchUnknown`; only proven pre-admission failures may be retried.
pub trait AutomationTurnQueue: Send + Sync {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt>;
}

pub struct AutomationScheduler<Q> {
    store: AutomationStore,
    queue: Arc<Q>,
    generation: u64,
    lease_duration_ms: u64,
    dispatch_timeout: Duration,
}

impl<Q> AutomationScheduler<Q>
where
    Q: AutomationTurnQueue,
{
    pub fn new(
        store: AutomationStore,
        queue: Arc<Q>,
        generation: u64,
        lease_duration: Duration,
        dispatch_timeout: Duration,
    ) -> Result<Self, AutomationError> {
        let lease_duration_ms =
            u64::try_from(lease_duration.as_millis()).map_err(|_| AutomationError::Invalid)?;
        if generation == 0
            || lease_duration_ms == 0
            || dispatch_timeout.is_zero()
            || dispatch_timeout >= lease_duration
        {
            return Err(AutomationError::Invalid);
        }
        Ok(Self {
            store,
            queue,
            generation,
            lease_duration_ms,
            dispatch_timeout,
        })
    }

    pub fn store(&self) -> &AutomationStore {
        &self.store
    }

    /// Claims and admits at most one occurrence. Queue admission is deliberately
    /// non-terminal: the owning runtime must later bind the persisted turn and
    /// terminal observation through the durable occurrence lifecycle.
    pub async fn tick(&self, now_ms: u64) -> Result<AutomationTick, AutomationError> {
        let Some(lease) = self
            .store
            .claim_due(now_ms, self.generation, self.lease_duration_ms)
            .await?
        else {
            return Ok(AutomationTick::Idle);
        };

        // Freeze schedule revision + canonical scheduled instant into a stable
        // occurrence identity before any external admission boundary.
        let occurrence = self.store.materialize_occurrence(&lease, now_ms).await?;
        // Bind the same occurrence to the existing durable TaskFlow run and
        // append its step intent/claim before provider contact.
        let taskflow = self
            .store
            .prepare_occurrence_taskflow(&occurrence, &lease, now_ms, self.lease_duration_ms)
            .await
            .map_err(|_| AutomationError::Unavailable)?;

        // Persist the dispatch intent before crossing the App Server seam. If
        // this process dies after possible admission, recovery retains the same
        // client id and must reconcile instead of blindly creating a duplicate.
        self.store.record_dispatch_uncertain(&lease, now_ms).await?;
        let admission = lease.admission();
        let result = timeout(self.dispatch_timeout, self.queue.enqueue(admission)).await;
        let receipt = match result {
            Ok(Ok(receipt)) => receipt,
            Ok(Err(AutomationError::AccessDenied)) => {
                self.store.abort_dispatch_before_admission(&lease).await?;
                return Err(AutomationError::AccessDenied);
            }
            Ok(Err(AutomationError::DispatchUnknown)) | Err(_) => {
                self.store.record_dispatch_uncertain(&lease, now_ms).await?;
                return Ok(AutomationTick::DispatchUncertain {
                    task_id: lease.task.task_id,
                    occurrence: lease.occurrence,
                });
            }
            Ok(Err(_)) => {
                self.store.abort_dispatch_before_admission(&lease).await?;
                return Ok(AutomationTick::RetryScheduled {
                    task_id: lease.task.task_id,
                    occurrence: lease.occurrence,
                });
            }
        };
        if receipt.client_user_message_id != lease.client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            self.store.record_dispatch_uncertain(&lease, now_ms).await?;
            return Ok(AutomationTick::DispatchUncertain {
                task_id: lease.task.task_id,
                occurrence: lease.occurrence,
            });
        }

        // Critical semantic boundary: durable Core admission is not automation
        // completion. The lifecycle row remains admitted/running until a trusted
        // terminal observation (or reconciliation) settles it.
        let admitted = self
            .store
            .record_occurrence_admitted(&lease, &receipt, now_ms)
            .await?;
        let admission_digest = admission_receipt_digest(&admitted);
        self.store
            .mark_occurrence_taskflow_admitted(&admitted, &taskflow, &admission_digest, now_ms)
            .await
            .map_err(|_| AutomationError::Unavailable)?;

        // Preserve the public v1 tick variant for compatibility. `Submitted`
        // now means only durable Core queue admission; it is explicitly not an
        // automation-occurrence terminal state.
        Ok(AutomationTick::Submitted {
            task_id: lease.task.task_id,
            occurrence: lease.occurrence,
            queued_submission_id: receipt.queued_submission_id,
        })
    }
}
