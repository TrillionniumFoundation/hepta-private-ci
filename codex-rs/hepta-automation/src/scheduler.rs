use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use tokio::time::timeout;

use crate::AutomationAdmission;
use crate::AutomationError;
use crate::AutomationLease;
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
        self.tick_with_clock(|| Ok(now_ms)).await
    }

    /// Sample the host-selected clock after each preparation boundary and
    /// before queue admission. The compatibility `tick` keeps its supplied
    /// time; normal hosts must use this live-clock entry point.
    pub async fn tick_with_clock(
        &self,
        mut clock: impl FnMut() -> Result<u64, AutomationError>,
    ) -> Result<AutomationTick, AutomationError> {
        let now_ms = clock()?;
        let Some(lease) = self
            .store
            .claim_due(now_ms, self.generation, self.lease_duration_ms)
            .await?
        else {
            return Ok(AutomationTick::Idle);
        };
        let mut last_sample = now_ms;
        let mut clock = || {
            let sampled = clock()?;
            if sampled < last_sample {
                return Err(AutomationError::Unavailable);
            }
            last_sample = sampled;
            Ok(sampled)
        };

        // Freeze schedule revision + canonical scheduled instant into a stable
        // occurrence identity before any external admission boundary.
        let preparation_started = Instant::now();
        let prepared = timeout(self.dispatch_timeout, async {
            let occurrence = self.store.materialize_occurrence(&lease, clock()?).await?;
            let prepared_at = clock()?;
            if prepared_at < now_ms || prepared_at >= lease.lease_expires_at_ms {
                return Ok(None);
            }
            // Local preparation can finish with an unknown commit result when
            // cancelled. Keep its original lease and every committed row; no
            // queue request has entered this future. The existing stale-owner
            // recovery handles missing, queued and claimed original runs.
            self.store
                .prepare_occurrence_taskflow(
                    &occurrence,
                    &lease,
                    prepared_at,
                    self.lease_duration_ms,
                )
                .await
                .map(Some)
                .map_err(|_| AutomationError::Unavailable)
        })
        .await;
        let taskflow = match prepared {
            Ok(Ok(Some(prepared))) => prepared,
            Ok(Ok(None)) | Ok(Err(_)) | Err(_) => {
                return Ok(AutomationTick::DispatchUncertain {
                    task_id: lease.task.task_id,
                    occurrence: lease.occurrence,
                });
            }
        };
        let Ok(prepared_at) = clock() else {
            return Ok(AutomationTick::DispatchUncertain {
                task_id: lease.task.task_id,
                occurrence: lease.occurrence,
            });
        };

        // Persist the dispatch intent before crossing the App Server seam. If
        // this process dies after possible admission, recovery retains the same
        // client id and must reconcile instead of blindly creating a duplicate.
        if !matches!(
            timeout(
                self.dispatch_timeout,
                self.store.record_dispatch_uncertain(&lease, prepared_at),
            )
            .await,
            Ok(Ok(()))
        ) || preparation_started.elapsed() >= self.dispatch_timeout
        {
            return Ok(retained_preparation(&lease));
        }
        let gate = timeout(
            self.dispatch_timeout,
            self.store
                .verify_prepared_admission(&lease, &taskflow, now_ms, &mut clock),
        )
        .await;
        if preparation_started.elapsed() >= self.dispatch_timeout || !matches!(gate, Ok(Ok(true))) {
            return Ok(AutomationTick::DispatchUncertain {
                task_id: lease.task.task_id,
                occurrence: lease.occurrence,
            });
        }
        let Ok(dispatch_at) = clock() else {
            return Ok(retained_preparation(&lease));
        };
        let dispatch_window_ms = u64::try_from(self.dispatch_timeout.as_millis())
            .map_err(|_| AutomationError::Invalid)?;
        if dispatch_at < prepared_at
            || dispatch_at
                .checked_add(dispatch_window_ms)
                .is_none_or(|until| until >= lease.lease_expires_at_ms)
        {
            return Ok(AutomationTick::DispatchUncertain {
                task_id: lease.task.task_id,
                occurrence: lease.occurrence,
            });
        }
        let admission = lease.admission();
        let result = timeout(self.dispatch_timeout, self.queue.enqueue(admission)).await;
        // A missing clock or local acknowledgement is an original-ID recovery
        // obligation after possible dispatch, never grounds for redispatch.
        let Ok(now_ms) = clock() else {
            return Ok(retained_preparation(&lease));
        };
        if now_ms < dispatch_at {
            return Ok(AutomationTick::DispatchUncertain {
                task_id: lease.task.task_id,
                occurrence: lease.occurrence,
            });
        }
        let receipt = match result {
            Ok(Ok(receipt)) => receipt,
            Ok(Err(AutomationError::AccessDenied)) => {
                self.store
                    .abort_dispatch_before_admission(&lease, now_ms)
                    .await?;
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
                self.store
                    .abort_dispatch_before_admission(&lease, now_ms)
                    .await?;
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

fn retained_preparation(lease: &AutomationLease) -> AutomationTick {
    AutomationTick::DispatchUncertain {
        task_id: lease.task.task_id,
        occurrence: lease.occurrence,
    }
}

#[cfg(test)]
#[path = "scheduler_preparation_tests.rs"]
mod tests;
