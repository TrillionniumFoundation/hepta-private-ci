use std::future::Future;
use std::sync::mpsc;
use std::task::Poll;
use std::time::Duration;

use anyhow::Result;
use pretty_assertions::assert_eq;
use tokio::time::timeout;

use super::super::owner::SingleInstanceLock;
use super::super::shutdown_tests::Fixture;
use super::*;

#[tokio::test(flavor = "current_thread")]
async fn cancelled_waiter_retains_writer_and_capacity_until_blocking_work_finishes() -> Result<()> {
    let Fixture {
        temp,
        state,
        cancellation: _,
    } = Fixture::new()?;
    let lock_path = state.registry.layout().supervisor_lock().to_path_buf();
    let capacity = Arc::clone(&state.execution.slots);
    let permit = Arc::clone(&capacity).try_acquire_owned()?;
    let (started_tx, started_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let job = spawn_owned(Arc::clone(&state), permit, move |state| {
        let _writer = state.supervisor.blocking_lock();
        let _ = started_tx.send(());
        release_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("release blocked owner");
    });
    timeout(Duration::from_secs(2), started_rx).await??;
    // Actual daemon dispatch on a single-thread runtime while its writer is held.
    let health = timeout(
        Duration::from_millis(250),
        handle(Arc::clone(&state), SupervisordMethod::Health),
    )
    .await?;
    assert!(matches!(health, SupervisordPayload::Health(_)));
    let agent_id = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let busy = handle(
        Arc::clone(&state),
        SupervisordMethod::ProductionMutationStatus { agent_id },
    )
    .await;
    assert!(
        matches!(busy, SupervisordPayload::Error { ref code, .. } if code == "not_admitted_busy")
    );
    assert_eq!(state.execution.rejected.load(Ordering::Relaxed), 1);
    // Dropping a JoinHandle is not completion of the underlying synchronous I/O.
    drop(job);
    drop(state);
    assert_eq!(capacity.available_permits(), 0);
    assert!(SingleInstanceLock::acquire(&lock_path).is_err());
    release_tx.send(())?;
    timeout(Duration::from_secs(2), async {
        while capacity.available_permits() == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    SingleInstanceLock::acquire(&lock_path)?;
    drop(temp);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn owner_panic_poison_cancels_daemon_and_prevents_successor_work() -> Result<()> {
    let fixture = Fixture::new()?;
    let state = &fixture.state;
    let permit = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let failed = spawn_owned(Arc::clone(state), permit, |_| -> () {
        panic!("injected owner panic")
    })
    .await;
    assert!(failed.expect_err("injected panic").is_panic());
    assert!(state.execution.poisoned.load(Ordering::Acquire));
    assert!(fixture.cancellation.is_cancelled());
    assert!(matches!(
        handle(Arc::clone(state), SupervisordMethod::Health).await,
        SupervisordPayload::Error { .. }
    ));
    let invoked = Arc::new(AtomicBool::new(false));
    let called = Arc::clone(&invoked);
    let permit = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let result = spawn_owned(Arc::clone(state), permit, move |_| {
        called.store(true, Ordering::Release);
    })
    .await?;
    assert_eq!(result, None);
    assert!(!invoked.load(Ordering::Acquire));
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn cancellation_releases_ticker_wait_without_starting_more_work() -> Result<()> {
    let fixture = Fixture::new()?;
    let state = &fixture.state;
    let _busy = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let ticker = tokio::spawn(tick(Arc::clone(state), Instant::now()));
    tokio::task::yield_now().await;
    fixture.cancellation.cancel();
    timeout(Duration::from_secs(1), ticker).await??;
    assert_eq!(state.execution.completed.load(Ordering::Relaxed), 0);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn queued_request_gets_owner_capacity_before_a_later_tick() -> Result<()> {
    let fixture = Fixture::new()?;
    let state = &fixture.state;
    let busy = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let agent_id = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let mut request = Box::pin(handle(
        Arc::clone(state),
        SupervisordMethod::ProductionMutationStatus { agent_id },
    ));
    // Poll once to deterministically register the FIFO acquisition before tick.
    std::future::poll_fn(|cx| {
        assert!(request.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    let mut ticker = Box::pin(tick(Arc::clone(state), Instant::now()));
    std::future::poll_fn(|cx| {
        assert!(ticker.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    drop(busy);
    // A live-state query can reject an unknown Agent, but must actually execute
    // instead of being starved by a continuously runnable periodic ticker.
    let _ = timeout(Duration::from_secs(1), request).await?;
    assert_eq!(state.execution.rejected.load(Ordering::Relaxed), 0);
    assert_eq!(state.execution.completed.load(Ordering::Relaxed), 1);
    fixture.cancellation.cancel();
    timeout(Duration::from_secs(1), ticker).await?;
    Ok(())
}

#[test]
fn tick_projection_refresh_is_coalesced_at_the_fixed_interval() {
    let execution = Execution::new(CancellationToken::new());
    let started = execution.started;
    execution
        .last_view_refresh_us
        .store(20_000, Ordering::Relaxed);
    assert!(!execution.view_refresh_due(started + Duration::from_millis(119)));
    assert!(execution.view_refresh_due(started + Duration::from_millis(120)));
    execution.note_view_refresh(started + Duration::from_millis(120));
    assert!(!execution.view_refresh_due(started + Duration::from_millis(219)));
    assert!(execution.view_refresh_due(started + Duration::from_millis(220)));
}

#[tokio::test(flavor = "current_thread")]
async fn live_allow_read_lane_is_bounded_and_never_retains_the_writer_lock()
-> Result<(), Box<dyn std::error::Error>> {
    let Fixture {
        temp,
        state,
        cancellation,
    } = Fixture::new()?;
    let lock_path = state.registry.layout().supervisor_lock().to_path_buf();
    let reader = state.execution.release_reads.get_or_init(|| {
        super::super::release_reads::ReleaseReads::new(state.registry.clone(), cancellation.clone())
            .map_err(|error| error.to_string())
    });
    let reader = reader.as_ref().map_err(|_| "reader startup")?;
    // A deterministic scheduling barrier holds only the actual native reader.
    // File/custody/content behavior is qualified separately on real root files.
    let resume = reader.pause().await?;
    let fence = crate::SupervisordControlFence {
        agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        supervisor_epoch: state.supervisor_epoch.clone(),
        lifecycle: codex_hepta_fleet::AgentLifecycle::Stopped,
        lifecycle_generation: 1,
        spawn_generation: None,
        runtime_generation: None,
        current_release: None,
        previous_release: None,
        release_change_pending: false,
        state_digest: crate::ControlStateDigest::parse("0".repeat(64))?,
    };
    let method = SupervisordMethod::AllowInstalledRelease {
        fence,
        release_id: "cold-release".parse()?,
    };
    for _ in 0..2 {
        let reply = timeout(
            Duration::from_secs(1),
            handle(Arc::clone(&state), method.clone()),
        )
        .await?;
        assert!(
            matches!(reply, SupervisordPayload::Error { ref code, .. } if code == "not_admitted_busy")
        );
        assert_eq!(state.execution.slots.available_permits(), 1);
        assert_eq!(state.execution.completed.load(Ordering::Relaxed), 0);
    }
    assert!(matches!(
        timeout(
            Duration::from_millis(250),
            handle(Arc::clone(&state), SupervisordMethod::Health)
        )
        .await?,
        SupervisordPayload::Health(_)
    ));
    timeout(
        Duration::from_secs(1),
        tick(Arc::clone(&state), Instant::now()),
    )
    .await?;
    assert_eq!(state.execution.completed.load(Ordering::Relaxed), 1);
    cancellation.cancel();
    drop(state);
    // The still-paused read thread owns no DaemonState/single-instance guard.
    SingleInstanceLock::acquire(&lock_path)?;
    resume.send(())?;
    drop(temp);
    Ok(())
}
