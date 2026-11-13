//! Actual cold Version local-capability mechanisms.
//! These use the original T/B/S/C fixture and real original responses. They
//! are not a Fresh Root or cross-UID ordinary-task qualification.

use super::*;
use crate::OriginalCircuitPublishedLocalReadV1;
use crate::OriginalCircuitLearningReadbackV1;

type ReadTask = tokio::task::JoinHandle<
    Result<Option<OriginalCircuitLearningReadbackV1>, ReadError>,
>;

fn require_equal<T: PartialEq + std::fmt::Debug>(actual: T, expected: T) -> anyhow::Result<()> {
    anyhow::ensure!(actual == expected,
        "actual original value {actual:?} differs from expected {expected:?}");
    Ok(())
}

async fn original_local_c(
    case: &NextUseCase,
    lifetime: Duration,
) -> anyhow::Result<(
    OriginalCircuitPublishedLocalReadV1,
    OriginalCircuitLearningReadClientV1,
    OriginalCircuitCompletionReadinessClientV1,
)> {
    let local = Version::open_original_evaluated_next_use_local_read(
        case.host()?, case.selection()?, Duration::from_millis(500), lifetime,
    ).await?;
    let live = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_next_use(
        local.clone(), case.selection()?,
    )?;
    OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(
        &live, case.shared.as_ref().context("same Version original T/E")?,
    )?;
    let readiness = OriginalCircuitCompletionReadinessClientV1::bind_original_evaluated_local_read(
        &live,
        &case.fixture()?.host.original.command_config,
        case.dataset_receipt.as_ref().context("actual original D receipt")?,
        &case.selection()?,
    )?;
    Ok((local, live, readiness))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_readiness_and_current_reuse_one_actual_request_sequence() -> anyhow::Result<()> {
    let case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let (local, live, readiness) = original_local_c(&case, Duration::from_secs(300)).await?;
        let alias = local.clone();
        anyhow::ensure!(local.fixture_shares_budget(&alias), "clone retains the actual same Arc");
        require_equal(local.fixture_next_request_id()?, Some(1))?;
        let before = case.original_bytes()?;
        require_equal(readiness.read_current().await?, None)?;
        require_equal(alias.fixture_next_request_id()?, Some(2))?;
        require_equal(case.original_bytes()?, before)?;
        let publication = execute(case.task()?, 1).await?;
        let actual = read_receipt(case.task()?, &case.fixture()?.definition, &publication)?;
        anyhow::ensure!(actual.bundle_digest == case.fixture()?.bundle.digest()?,
            "actual C used the original retained baseline");
        let completed_bytes = case.original_bytes()?;
        let read = live.read_current().await?;
        require_equal(local.fixture_next_request_id()?, Some(3))?;
        require_equal(readiness.read_current().await?, Some(read))?;
        require_equal(alias.fixture_next_request_id()?, Some(4))?;
        require_equal(case.original_bytes()?, completed_bytes)?;
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_readiness_borrows_the_fourth_lane_without_a_fifth_permit() -> anyhow::Result<()> {
    let case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        // The original S fixture already holds one actual Version channel.
        // Three concrete local exports occupy the remaining original permits.
        let selection = Version::open_original_evaluated_selection_local_read(
            case.host()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        let (next_use, live, readiness) = original_local_c(&case, Duration::from_secs(300)).await?;
        let extra_selection = Version::open_original_evaluated_selection_local_read(
            case.host()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        let alias = next_use.clone();
        anyhow::ensure!(alias.fixture_shares_budget(&next_use), "same local lane");
        let refused = Version::open_original_evaluated_selection_local_read(
            case.host()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await;
        anyhow::ensure!(matches!(refused, Err(VersionError::Busy)),
            "the original four-permit limit is still enforced");
        require_equal(readiness.read_current().await?, None)?;
        require_equal(next_use.fixture_next_request_id()?, Some(2))?;
        drop((selection, extra_selection, live, readiness, alias, next_use));
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_read_capabilities_reject_cross_purpose_conversions() -> anyhow::Result<()> {
    let case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let selection = Version::open_original_evaluated_selection_local_read(
            case.host()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        let next_use = Version::open_original_evaluated_next_use_local_read(
            case.host()?, case.selection()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        anyhow::ensure!(OriginalCircuitLearningReadClientV1::from_original_evaluated_local_selection(
            next_use.clone(), case.fixture()?.readback_context()?,
        ).is_err(), "a five-cut capability cannot become a four-cut capability");
        anyhow::ensure!(OriginalCircuitLearningReadClientV1::from_original_evaluated_local_next_use(
            selection.clone(), case.selection()?,
        ).is_err(), "a four-cut capability cannot become readiness or NextUse");
        require_equal(selection.fixture_next_request_id()?, Some(1))?;
        require_equal(next_use.fixture_next_request_id()?, Some(1))?;
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_readiness_rechecks_actual_b_and_fences_all_aliases() -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        let (local, live, readiness) = original_local_c(&case, Duration::from_secs(300)).await?;
        require_equal(readiness.read_current().await?, None)?;
        case.fixture.as_deref_mut().context("same original B")?.host.retention_b.withdraw_target()?;
        let before = case.original_bytes()?;
        let revision = case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision;
        anyhow::ensure!(readiness.read_current().await.is_err(),
            "later actual B withdrawal invalidates an already admitted local capability");
        anyhow::ensure!(matches!(live.read_current().await, Err(ReadError::Unavailable)),
            "the readback alias cannot repair the shared terminal slot");
        require_equal(local.fixture_next_request_id()?, None)?;
        require_equal(case.original_bytes()?, before)?;
        require_equal(case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision, revision)?;
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[derive(Clone, Copy)]
enum PausedLocalReadCase {
    CompetingAlias,
    CancelAwaiter,
    CrossFixedEnd,
}

async fn paused_local_read_case(mode: PausedLocalReadCase) -> anyhow::Result<()> {
    let case = Box::pin(NextUseCase::ready()).await?;
    let setup = original_local_c(&case, match mode {
        PausedLocalReadCase::CrossFixedEnd => Duration::from_millis(500),
        PausedLocalReadCase::CompetingAlias | PausedLocalReadCase::CancelAwaiter =>
            Duration::from_secs(300),
    }).await;
    let (local, live, readiness) = match setup {
        Ok(value) => value,
        Err(error) => return finish_case(Err(error), case).await,
    };
    let probe = match local.fixture_pause_after_original_response() {
        Ok(value) => value,
        Err(error) => {
            drop((local, live, readiness));
            return finish_case(Err(error.into()), case).await;
        }
    };
    let inputs: anyhow::Result<_> = (|| {
        Ok((
            case.original_bytes()?,
            OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(
                &live, &case.selection()?,
            )?,
        ))
    })();
    let (before, fixed_end) = match inputs {
        Ok(value) => value,
        Err(error) => {
            drop((probe, local, live, readiness));
            return finish_case(Err(error), case).await;
        }
    };
    let mut task: Option<ReadTask> = Some(tokio::spawn(async move {
        readiness.read_current().await
    }));
    let mut consumed_join = false;
    let result: anyhow::Result<()> = async {
        let current = task.as_mut().context("one actual local read awaiter")?;
        tokio::select! {
            completed = current => {
                consumed_join = true;
                anyhow::bail!("actual read ended before the original-response gate: {completed:?}");
            }
            _ = probe.wait_after_original_response() => {}
        }
        anyhow::ensure!(probe.original_started(), "the original worker actually started");
        anyhow::ensure!(probe.original_response_observed(),
            "the pause occurs after the concrete original owner produced its response");
        require_equal(local.fixture_next_request_id()?, None)?;
        anyhow::ensure!(matches!(live.read_current().await, Err(ReadError::Unavailable)),
            "a competing alias sees the same occupied slot without issuing owner I/O");
        match mode {
            PausedLocalReadCase::CompetingAlias => {
                probe.release();
                let original = task.take().context("original awaited read")?.await??;
                require_equal(original, None)?;
                probe.wait_original_terminal().await;
                require_equal(local.fixture_next_request_id()?, Some(2))?;
            }
            PausedLocalReadCase::CancelAwaiter => {
                task.as_ref().context("same original awaiter")?.abort();
                let stopped = task.take().context("same cancelled awaiter")?.await;
                anyhow::ensure!(matches!(stopped, Err(ref error) if error.is_cancelled()),
                    "the awaiting future actually terminated by cancellation");
                probe.release();
                probe.wait_original_terminal().await;
                require_equal(local.fixture_next_request_id()?, None)?;
                anyhow::ensure!(matches!(live.read_current().await, Err(ReadError::Unavailable)),
                    "late actual work cannot restore the cancelled shared slot");
            }
            PausedLocalReadCase::CrossFixedEnd => {
                // No extra sleep or larger budget: retain the actual response
                // until this capability's already-fixed deadline ends the wait.
                let stopped = task.take().context("same deadline-bound awaiter")?.await?;
                anyhow::ensure!(stopped.is_err(), "no success may cross the fixed local end");
                anyhow::ensure!(std::time::Instant::now() >= fixed_end,
                    "the original fixed local deadline actually elapsed");
                probe.release();
                probe.wait_original_terminal().await;
                require_equal(local.fixture_next_request_id()?, None)?;
                anyhow::ensure!(matches!(live.read_current().await, Err(ReadError::Unavailable)),
                    "the expired operation cannot replenish the shared slot");
            }
        }
        require_equal(case.original_bytes()?, before)?;
        require_equal(case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision, 0)?;
        Ok(())
    }.await;
    // Also close and observe the original operation if any assertion failed.
    // No serving lane is detached merely to turn cleanup into a pass.
    probe.release();
    let mut cleanup_error = None;
    if let Some(task) = task.take() {
        if !consumed_join {
            task.abort();
            match task.await {
                Ok(_) => {}
                Err(error) if error.is_cancelled() => {}
                Err(error) => cleanup_error = Some(anyhow::anyhow!("local read join: {error}")),
            }
        }
    }
    if probe.original_submitted() {
        probe.wait_original_terminal().await;
    }
    drop((probe, local, live));
    let result = match (result, cleanup_error) {
        (Ok(()), None) => Ok(()),
        (Err(error), None) => Err(error),
        (Ok(()), Some(error)) => Err(error),
        (Err(error), Some(cleanup)) => Err(error.context(format!("actual local cleanup: {cleanup:#}"))),
    };
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_alias_contention_preserves_the_original_pending_response() -> anyhow::Result<()> {
    Box::pin(paused_local_read_case(PausedLocalReadCase::CompetingAlias)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_cancelled_read_never_restores_any_alias() -> anyhow::Result<()> {
    Box::pin(paused_local_read_case(PausedLocalReadCase::CancelAwaiter)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_original_response_crossing_fixed_end_is_not_delivered() -> anyhow::Result<()> {
    Box::pin(paused_local_read_case(PausedLocalReadCase::CrossFixedEnd)).await
}
