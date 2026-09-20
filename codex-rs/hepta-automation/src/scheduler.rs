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

pub type AutomationFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, AutomationError>> + Send + 'a>>;

/// The only execution seam available to automation.
///
/// Product implementations must enqueue this admission through the owning
/// Agent's App Server `thread/queue/add` API. The scheduler cannot call a
/// model, a tool, Core, or another Agent directly. `Dispatch`, `Unavailable`,
/// and `Corrupt` are retryable only when the implementation knows the
/// request did not cross that admission seam; otherwise it must return
/// `DispatchUnknown` so the durable intent remains quarantined.
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

    /// Claims and submits at most one occurrence. Bounded single-item ticks
    /// prevent one Agent backlog from creating a fleet-wide drain loop.
    pub async fn tick(&self, now_ms: u64) -> Result<AutomationTick, AutomationError> {
        let Some(lease) = self
            .store
            .claim_due(now_ms, self.generation, self.lease_duration_ms)
            .await?
        else {
            return Ok(AutomationTick::Idle);
        };
        // Persist the dispatch intent before crossing the App Server seam.
        // If this process dies after admission (or while the request is still
        // in flight) the successor must observe a durable unknown outcome and
        // refuse a blind duplicate.  Known pre-admission failures explicitly
        // clear this marker below, preserving the bounded retry path.
        self.store.record_dispatch_uncertain(&lease, now_ms).await?;
        let admission = lease.admission();
        let result = timeout(self.dispatch_timeout, self.queue.enqueue(admission)).await;
        let receipt = match result {
            Ok(Ok(receipt)) => receipt,
            // Owner/generation fencing is not a transient dispatch failure.
            // Agentd performs this check before the queue seam, so remove the
            // pre-admission intent before returning the fence to the caller.
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
                // Agentd maps only failures observed before the App Server
                // admission seam to these retryable errors. If the process
                // dies before this cleanup, the durable intent remains
                // uncertain and recovery stays fail-closed.
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
        self.store.mark_submitted(&lease, &receipt, now_ms).await?;
        Ok(AutomationTick::Submitted {
            task_id: lease.task.task_id,
            occurrence: lease.occurrence,
            queued_submission_id: receipt.queued_submission_id,
        })
    }
}
