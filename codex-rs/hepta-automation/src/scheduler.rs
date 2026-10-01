use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

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
        let started_at = Instant::now();
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
        self.store
            .record_dispatch_uncertain_from_tick(&lease, now_ms, started_at)
            .await?;
        let admission = lease.admission();
        let result = timeout(self.dispatch_timeout, self.queue.enqueue(admission)).await;
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AutomationSchedule;
    use crate::AutomationTaskDraft;
    use codex_hepta_contracts::AgentId;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    #[derive(Default)]
    struct CountingQueue(AtomicUsize);

    impl AutomationTurnQueue for CountingQueue {
        fn enqueue(
            &self,
            admission: AutomationAdmission,
        ) -> AutomationFuture<'_, AutomationQueueReceipt> {
            Box::pin(async move {
                self.0.fetch_add(1, Ordering::SeqCst);
                Ok(AutomationQueueReceipt {
                    queued_submission_id: "unexpected-expired-contact".to_string(),
                    client_user_message_id: admission.client_user_message_id,
                })
            })
        }
    }

    #[tokio::test]
    async fn prepared_first_intent_samples_time_after_its_writer_wait() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("automation");
        let store = AutomationStore::open_root(
            root.clone(),
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
        )
        .await
        .unwrap();
        let task = AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "writer wait",
            AutomationSchedule::Once,
            100,
            1,
        );
        store.create_task(&task).await.unwrap();
        let lease = store.claim_due(100, 1, 10).await.unwrap().unwrap();
        let occurrence = store.materialize_occurrence(&lease, 100).await.unwrap();
        store
            .prepare_occurrence_taskflow(&occurrence, &lease, 100, 10)
            .await
            .unwrap();
        let blocker = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root).unwrap())
            .open_durable_evidence_pool(store.path())
            .await
            .unwrap();
        let reservation = blocker.begin_with("BEGIN IMMEDIATE").await.unwrap();
        let queue = CountingQueue::default();
        let started_at = Instant::now();
        let contact = async {
            store
                .record_dispatch_uncertain_from_tick(&lease, 100, started_at)
                .await?;
            queue.enqueue(lease.admission()).await
        };
        tokio::pin!(contact);
        tokio::select! {
            biased;
            result = &mut contact => panic!("writer must block first intent: {result:?}"),
            () = tokio::time::sleep(Duration::from_millis(25)) => {}
        }
        reservation.commit().await.unwrap();
        assert_eq!(contact.await, Err(AutomationError::Conflict));
        assert_eq!(queue.0.load(Ordering::SeqCst), 0);
        assert_eq!(store.uncertain_dispatches(1).await.unwrap(), Vec::new());
        blocker.close().await;
        store.close().await;
    }
}
