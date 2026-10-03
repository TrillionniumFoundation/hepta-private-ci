//! Real SQLite serialization and controlled clock sampling races. These do not
//! claim physical process exit, authority signing, or power-loss qualification.
use std::future::Future;
use std::future::poll_fn;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::task::Poll;
use std::time::Duration;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use pretty_assertions::assert_eq;

use super::*;
use crate::HostObservation;
use crate::ResourceVectorV1;

struct Clock(AtomicU64);
impl Clock {
    fn set(&self, now_ms: u64) {
        self.0.store(now_ms, Ordering::SeqCst);
    }
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

async fn poll_waiting<F: Future>(mut future: Pin<&mut F>) {
    poll_fn(|cx| {
        assert!(
            future.as_mut().poll(cx).is_pending(),
            "writer must wait for the held serialization boundary"
        );
        Poll::Ready(())
    })
    .await;
}

#[tokio::test]
async fn waiting_writer_samples_after_lock_and_preserves_real_rollback_rejection()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let clock = Arc::new(Clock(AtomicU64::new(1_000)));
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await?;
    let mut held = store.pool.begin_with("BEGIN IMMEDIATE").await?;
    let workspace = directory.path().join("workspace");
    let mut waiting = Box::pin(store.reserve_workspace("agent-one", &workspace));
    poll_waiting(waiting.as_mut()).await;
    clock.set(/*now_ms*/ 2_000);
    DurableFleetStore::advance_clock_tx(&mut held, /*now_ms*/ 2_000).await?;
    held.commit().await?;
    let reserved = waiting.await?;
    assert_eq!(
        (reserved.created_at_ms, reserved.updated_at_ms),
        (2_000, 2_000)
    );
    let before: Vec<(String, i64)> = sqlx::query_as(
        "SELECT agent_id, updated_at_ms FROM workspace_reservations ORDER BY agent_id",
    )
    .fetch_all(&store.pool)
    .await?;
    clock.set(/*now_ms*/ 1_999);
    assert_eq!(
        store
            .reserve_workspace("agent-two", &directory.path().join("other"))
            .await,
        Err(DurableFleetError::ClockRollback)
    );
    let after: Vec<(String, i64)> = sqlx::query_as(
        "SELECT agent_id, updated_at_ms FROM workspace_reservations ORDER BY agent_id",
    )
    .fetch_all(&store.pool)
    .await?;
    assert_eq!(after, before);
    Ok(())
}

#[tokio::test]
async fn observation_ttl_is_revalidated_after_waiting_for_writer_lock()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let clock = Arc::new(Clock(AtomicU64::new(1_000)));
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await?;
    let observation = HostObservation {
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        generation: 1,
        observed_at_ms: 1_000,
        valid_until_ms: 1_500,
        capacity: ResourceVectorV1 {
            cpu_millis: 1_000,
            memory_bytes: 1 << 20,
            concurrent_turns: 1,
            tool_processes: 1,
            turn_queue_slots: 1,
            ..ResourceVectorV1::default()
        },
    };
    let mut held = store.pool.begin_with("BEGIN IMMEDIATE").await?;
    let mut waiting = Box::pin(store.observe_host(&observation, "actual-test-observer"));
    poll_waiting(waiting.as_mut()).await;
    clock.set(/*now_ms*/ 2_000);
    DurableFleetStore::advance_clock_tx(&mut held, /*now_ms*/ 2_000).await?;
    held.commit().await?;
    assert_eq!(waiting.await, Err(DurableFleetError::Stale));
    let hosts: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM fleet_hosts")
        .fetch_one(&store.pool)
        .await?;
    assert_eq!(hosts, 0);
    Ok(())
}

#[tokio::test]
async fn opening_existing_store_samples_inside_schema_writer_transaction()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let database = directory.path().join("fleet.sqlite3");
    let clock = Arc::new(Clock(AtomicU64::new(1_000)));
    let store = DurableFleetStore::open_with_clock(&database, clock.clone()).await?;
    let mut held = store.pool.begin_with("BEGIN IMMEDIATE").await?;
    let mut waiting = Box::pin(DurableFleetStore::open_with_clock(&database, clock.clone()));
    poll_waiting(waiting.as_mut()).await;
    clock.set(/*now_ms*/ 2_000);
    DurableFleetStore::advance_clock_tx(&mut held, /*now_ms*/ 2_000).await?;
    held.commit().await?;
    let reopened = waiting.await?;
    assert_eq!(reopened.owner_now_ms(), Ok(2_000));
    reopened.close().await;
    clock.set(/*now_ms*/ 1_999);
    assert!(matches!(
        DurableFleetStore::open_with_clock(&database, clock).await,
        Err(DurableFleetError::ClockRollback)
    ));
    let frontier: i64 =
        sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
            .fetch_one(&store.pool)
            .await?;
    assert_eq!(frontier, 2_000);
    Ok(())
}

struct PausedClock {
    now: AtomicU64,
    pause: AtomicBool,
    entered: mpsc::SyncSender<()>,
    release: Mutex<mpsc::Receiver<()>>,
}
impl AuthorityClock for PausedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let sampled = self.now.load(Ordering::SeqCst);
        if self.pause.swap(/*val*/ false, Ordering::SeqCst) {
            self.entered
                .send(())
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            self.release
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .recv()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        Ok(sampled)
    }
}

#[tokio::test]
async fn concurrent_memory_frontier_advance_resamples_clock_after_cas_race()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let (entered_tx, entered_rx) = mpsc::sync_channel(/*bound*/ 0);
    let (release_tx, release_rx) = mpsc::sync_channel(/*bound*/ 0);
    let clock = Arc::new(PausedClock {
        now: AtomicU64::new(1_000),
        pause: AtomicBool::new(/*v*/ false),
        entered: entered_tx,
        release: Mutex::new(release_rx),
    });
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await?;
    clock.pause.store(/*val*/ true, Ordering::SeqCst);
    let peer = store.clone();
    let paused = std::thread::spawn(move || peer.owner_now_ms());
    entered_rx.recv_timeout(Duration::from_secs(5))?;
    clock.now.store(/*val*/ 2_000, Ordering::SeqCst);
    assert_eq!(store.owner_now_ms(), Ok(2_000));
    release_tx.send(())?;
    assert_eq!(
        paused.join().map_err(|_| "clock sampler panicked")?,
        Ok(2_000)
    );
    clock.now.store(/*val*/ 1_999, Ordering::SeqCst);
    assert_eq!(store.owner_now_ms(), Err(DurableFleetError::ClockRollback));
    Ok(())
}
