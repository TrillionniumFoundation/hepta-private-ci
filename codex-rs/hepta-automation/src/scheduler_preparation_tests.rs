use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::AutomationOccurrenceState;
use crate::AutomationSchedule;
use crate::AutomationTaskDraft;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

struct ObservedQueue(AtomicUsize);
impl AutomationTurnQueue for ObservedQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(AutomationQueueReceipt {
                queued_submission_id: "queue.original".to_owned(),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

async fn store()
-> Result<(tempfile::TempDir, AutomationStore), Box<dyn std::error::Error + Send + Sync>> {
    let root = tempfile::tempdir()?;
    let store = AutomationStore::open_root(
        root.path().join("owner"),
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
    )
    .await?;
    store
        .create_task(&AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "preserve exact original preparation",
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await?;
    Ok((root, store))
}

#[tokio::test]
async fn live_clock_fences_preparation_and_records_actual_queue_ack() -> TestResult {
    let (_root, store) = store().await?;
    let queue = Arc::new(ObservedQueue(AtomicUsize::new(0)));
    let scheduler = AutomationScheduler::new(
        store.clone(),
        queue.clone(),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )?;
    let mut sampled = 100;
    let result = scheduler
        .tick_with_clock(|| {
            sampled += 1;
            Ok(sampled)
        })
        .await?;
    assert!(matches!(result, AutomationTick::Submitted { .. }));
    assert_eq!(queue.0.load(Ordering::SeqCst), 1);
    assert!(sampled > 105);
    let status = store.timer_status().await?;
    assert_eq!(
        (status.leased_occurrences, status.uncertain_dispatches),
        (0, 0)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn expiry_after_preparation_or_fence_retains_original_run_without_queue_entry() -> TestResult
{
    for expires_at_sample in [4, 7] {
        let (root, store) = store().await?;
        let queue = Arc::new(ObservedQueue(AtomicUsize::new(0)));
        let scheduler = AutomationScheduler::new(
            store.clone(),
            queue.clone(),
            1,
            Duration::from_secs(30),
            Duration::from_secs(2),
        )?;
        let mut count = 0;
        let result = scheduler
            .tick_with_clock(|| {
                count += 1;
                Ok(if count >= expires_at_sample {
                    31_000
                } else {
                    100
                })
            })
            .await?;
        let (task_id, occurrence_number) = match result {
            AutomationTick::DispatchUncertain {
                task_id,
                occurrence,
            } => (task_id, occurrence),
            other => {
                return Err(format!("expected retained original preparation: {other:?}").into());
            }
        };
        assert_eq!(queue.0.load(Ordering::SeqCst), 0);
        let occurrence = store
            .automation_occurrence(task_id, occurrence_number)
            .await?
            .ok_or("original occurrence missing")?;
        assert_eq!(occurrence.state, AutomationOccurrenceState::Claimed);
        let original = store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await?
            .ok_or("original prepared run missing")?;
        store.recover_stale_generation(2, 32_000).await?;
        assert_eq!(
            store.taskflow_run(&original.run_id).await?,
            Some(original.clone())
        );
        store.close().await;
        let reopened =
            AutomationStore::open_root(root.path().join("owner"), store.owner_agent_id().clone())
                .await?;
        assert_eq!(
            reopened.taskflow_run(&original.run_id).await?,
            Some(original)
        );
        let status = reopened.timer_status().await?;
        assert_eq!(
            (status.leased_occurrences, status.uncertain_dispatches),
            (1, 1)
        );
        reopened.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn missing_or_rolling_back_clock_never_enters_queue_or_discards_preparation() -> TestResult {
    for failure_sample in [4, 7] {
        let (_root, store) = store().await?;
        let queue = Arc::new(ObservedQueue(AtomicUsize::new(0)));
        let scheduler = AutomationScheduler::new(
            store.clone(),
            queue.clone(),
            1,
            Duration::from_secs(30),
            Duration::from_secs(2),
        )?;
        let mut count = 0;
        let result = scheduler
            .tick_with_clock(|| {
                count += 1;
                if count == failure_sample {
                    if failure_sample == 7 {
                        Err(AutomationError::Unavailable)
                    } else {
                        Ok(99)
                    }
                } else {
                    Ok(100)
                }
            })
            .await?;
        let (task_id, occurrence_number) = match result {
            AutomationTick::DispatchUncertain {
                task_id,
                occurrence,
            } => (task_id, occurrence),
            other => {
                return Err(format!("expected retained original preparation: {other:?}").into());
            }
        };
        assert_eq!(queue.0.load(Ordering::SeqCst), 0);
        let occurrence = store
            .automation_occurrence(task_id, occurrence_number)
            .await?
            .ok_or("original occurrence missing")?;
        assert!(
            store
                .taskflow_run(&occurrence.taskflow_run_id)
                .await?
                .is_some()
        );
        assert_eq!(store.timer_status().await?.leased_occurrences, 1);
        store.close().await;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn writer_stall_cancels_only_local_preparation_and_preserves_original_claim() -> TestResult {
    let (_root, store) = store().await?;
    let mut writer = store.taskflow_pool().acquire().await?;
    let (requested, request) = tokio::sync::oneshot::channel();
    let (ready, observed) = std::sync::mpsc::sync_channel(1);
    let (release, released) = tokio::sync::oneshot::channel();
    let held_writer = tokio::spawn(async move {
        request.await?;
        sqlx::query("BEGIN IMMEDIATE").execute(&mut *writer).await?;
        ready.send(())?;
        let _ = released.await;
        sqlx::query("ROLLBACK").execute(&mut *writer).await?;
        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
    });
    let queue = Arc::new(ObservedQueue(AtomicUsize::new(0)));
    let scheduler = AutomationScheduler::new(
        store.clone(),
        queue.clone(),
        1,
        Duration::from_secs(30),
        Duration::from_millis(100),
    )?;
    let mut count = 0;
    let mut requested = Some(requested);
    let result = scheduler
        .tick_with_clock(|| {
            count += 1;
            if count == 3 {
                requested
                    .take()
                    .ok_or(AutomationError::Unavailable)?
                    .send(())
                    .map_err(|_| AutomationError::Unavailable)?;
                observed
                    .recv_timeout(Duration::from_secs(1))
                    .map_err(|_| AutomationError::Unavailable)?;
            }
            Ok(100)
        })
        .await;
    let _ = release.send(());
    held_writer.await??;
    let (task_id, occurrence_number) = match result? {
        AutomationTick::DispatchUncertain {
            task_id,
            occurrence,
        } => (task_id, occurrence),
        other => return Err(format!("expected retained original claim: {other:?}").into()),
    };
    assert_eq!(queue.0.load(Ordering::SeqCst), 0);
    let original = store
        .automation_occurrence(task_id, occurrence_number)
        .await?
        .ok_or("original materialized occurrence missing")?;
    assert_eq!(original.state, AutomationOccurrenceState::Claimed);
    assert_eq!(store.timer_status().await?.leased_occurrences, 1);
    store.recover_stale_generation(2, 32_000).await?;
    let retained = store
        .automation_occurrence(task_id, occurrence_number)
        .await?
        .ok_or("recovery erased original occurrence")?;
    assert_eq!(
        (
            retained.occurrence_id,
            retained.client_user_message_id,
            retained.taskflow_run_id
        ),
        (
            original.occurrence_id,
            original.client_user_message_id,
            original.taskflow_run_id
        )
    );
    assert_eq!(queue.0.load(Ordering::SeqCst), 0);
    store.close().await;
    Ok(())
}
