//! Component checks of actual blocking-work and Unix-FD custody.
//! These tests supply no Root, Dataset, Training receipt or ordinary task.

use std::io;
use std::sync::mpsc;
use std::time::Duration;

use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::sync::Semaphore;
use tokio::sync::oneshot;

use super::*;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;

const WAIT: Duration = Duration::from_secs(60);

fn jobs() -> io::Result<Arc<OriginalLearningJobs>> {
    Ok(Arc::new(OriginalLearningJobs {
        gate: SameActorPhaseGate::from_original_deadline(
            SameActorPhaseDeadline::at_original_service_start(WAIT)?,
        )?,
        retained: Mutex::new(Vec::new()),
        pending: Arc::new(AtomicUsize::new(0)),
        join_failed: Arc::new(AtomicBool::new(false)),
        changed: Arc::new(Notify::new()),
    }))
}

fn pair() -> io::Result<(std::os::unix::net::UnixStream, tokio::net::UnixStream)> {
    let (owned, peer) = std::os::unix::net::UnixStream::pair()?;
    peer.set_nonblocking(true)?;
    Ok((owned, tokio::net::UnixStream::from_std(peer)?))
}

async fn require_eof(peer: &mut tokio::net::UnixStream) -> anyhow::Result<()> {
    let mut byte = [0];
    assert_eq!(tokio::time::timeout(WAIT, peer.read(&mut byte)).await??, 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_job_checks_gate_after_actual_owner_lock_wait() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let owner = Arc::new(Mutex::new(0_u32));
    let (locked, locked_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::sync_channel(1);
    let lock_owner = Arc::clone(&owner);
    let holder = std::thread::spawn(move || {
        let guard = lock_owner.lock().unwrap();
        let _ = locked.send(());
        let _ = release_rx.recv();
        drop(guard);
    });
    tokio::time::timeout(WAIT, locked_rx).await??;
    let (arrived, arrived_rx) = oneshot::channel();
    let for_job = Arc::clone(&owner);
    let gate = Arc::clone(&jobs.gate);
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            let _closing = CloseSameActorPhaseOnDrop::new(&gate);
            let _ = arrived.send(());
            let mut original = for_job.lock().map_err(|_| ())?;
            gate.require_open().map_err(|_| ())?;
            *original += 1;
            Ok::<_, ()>(())
        });
        admission.retain_original_handle(handle)
    };
    tokio::time::timeout(WAIT, arrived_rx).await??;
    drop(job);
    let cleanup_jobs = Arc::clone(&jobs);
    let cleanup = tokio::spawn(async move { cleanup_jobs.close_and_join().await });
    tokio::time::timeout(WAIT, jobs.gate.cancelled()).await?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    assert!(!cleanup.is_finished());
    release.send(())?;
    tokio::time::timeout(WAIT, cleanup)
        .await??
        .map_err(|_| anyhow::anyhow!("join"))?;
    holder.join().map_err(|_| anyhow::anyhow!("holder panicked"))?;
    assert_eq!(*owner.lock().unwrap(), 0);
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_waiter_retains_actual_blocking_handle_and_original_output() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let lane = Arc::new(Semaphore::new(1));
    let permit = Arc::clone(&lane).acquire_owned().await?;
    let (owned, mut peer) = pair()?;
    let (started, started_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::sync_channel(1);
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let _ = started.send(());
            release_rx.recv().map_err(|_| ())?;
            // Represents an original operation already admitted before close:
            // its actual returned FD must be retained, then discarded on exit.
            Ok::<_, ()>(owned)
        });
        admission.retain_original_handle(handle)
    };
    tokio::time::timeout(WAIT, started_rx).await??;
    let waiting_jobs = Arc::clone(&jobs);
    let (waiting, waiting_rx) = oneshot::channel();
    let waiter = tokio::spawn(async move {
        let closing = CloseSameActorPhaseOnDrop::new(&waiting_jobs.gate);
        let _ = waiting.send(());
        let result = waiting_jobs.receive_registered_job(job).await;
        drop(closing);
        result
    });
    tokio::time::timeout(WAIT, waiting_rx).await??;
    waiter.abort(); // Only the result waiter; never the original blocking job.
    assert!(waiter.await.unwrap_err().is_cancelled());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    assert_eq!(lane.available_permits(), 0);
    assert_eq!(
        peer.try_read(&mut [0]).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    let cleanup_jobs = Arc::clone(&jobs);
    let cleanup = tokio::spawn(async move { cleanup_jobs.close_and_join().await });
    assert!(!cleanup.is_finished());
    release.send(())?;
    tokio::time::timeout(WAIT, cleanup)
        .await??
        .map_err(|_| anyhow::anyhow!("join"))?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    assert_eq!(lane.available_permits(), 1);
    require_eof(&mut peer).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_cleanup_rejoins_same_handle_without_restarting_work() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (owned, mut peer) = pair()?;
    let (started, started_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::sync_channel(1);
    let executions = Arc::new(AtomicUsize::new(0));
    let calls = Arc::clone(&executions);
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            calls.fetch_add(1, Ordering::AcqRel);
            let _ = started.send(());
            release_rx.recv().map_err(|_| ())?;
            Ok::<_, ()>(owned)
        });
        admission.retain_original_handle(handle)
    };
    drop(job);
    tokio::time::timeout(WAIT, started_rx).await??;
    let first_jobs = Arc::clone(&jobs);
    let first = tokio::spawn(async move { first_jobs.close_and_join().await });
    tokio::time::timeout(WAIT, jobs.gate.cancelled()).await?;
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    let second_jobs = Arc::clone(&jobs);
    let second = tokio::spawn(async move { second_jobs.close_and_join().await });
    release.send(())?;
    tokio::time::timeout(WAIT, second)
        .await??
        .map_err(|_| anyhow::anyhow!("join"))?;
    assert_eq!(executions.load(Ordering::Acquire), 1);
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    require_eof(&mut peer).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn empty_registry_cannot_hide_outstanding_original_job_custody() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (owned, mut peer) = pair()?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || Ok::<_, ()>(owned));
        admission.retain_original_handle(handle)
    };
    let mut cleanup = Box::pin(jobs.close_and_join());
    // Poll the real cleanup first. EOF can only be produced by that future
    // dropping the original output. An early Ready is therefore deterministic,
    // rather than depending on whether a spawned cleanup has been scheduled.
    tokio::time::timeout(WAIT, async {
        tokio::select! {
            biased;
            result = &mut cleanup => {
                panic!("cleanup completed while exact job custody remained: {result:?}");
            }
            result = require_eof(&mut peer) => result,
        }
    })
    .await??;
    assert!(jobs.retained.lock().unwrap().is_empty());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    drop(job);
    tokio::time::timeout(WAIT, cleanup)
        .await?
        .map_err(|_| anyhow::anyhow!("join"))?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_join_panic_is_sticky_after_handle_has_been_consumed() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let lane = Arc::new(Semaphore::new(1));
    let permit = Arc::clone(&lane).acquire_owned().await?;
    let job = {
        let admission = jobs.reserve()?;
        let gate = Arc::clone(&jobs.gate);
        let handle = tokio::task::spawn_blocking(move || -> Result<(), ()> {
            let _permit = permit;
            let _closing = CloseSameActorPhaseOnDrop::new(&gate);
            panic!("controlled original blocking component failure");
        });
        admission.retain_original_handle(handle)
    };
    assert!(matches!(
        jobs.receive_registered_job(job).await,
        Err(Error::CommitUncertain)
    ));
    assert_eq!(lane.available_permits(), 1);
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    assert_eq!(jobs.close_and_join().await, Err(()));
    assert_eq!(jobs.close_and_join().await, Err(()));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_owner_error_is_preserved_and_phase_closes() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(|| Err::<u64, _>("original owner refusal"));
        admission.retain_original_handle(handle)
    };
    assert!(matches!(
        jobs.receive_registered_job(job).await,
        Ok(Err("original owner refusal"))
    ));
    tokio::time::timeout(WAIT, jobs.gate.cancelled()).await?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    assert_eq!(jobs.close_and_join().await, Ok(()));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn successful_original_job_releases_real_lane_before_returning_value() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let lane = Arc::new(Semaphore::new(1));
    let permit = Arc::clone(&lane).acquire_owned().await?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            Ok::<_, ()>(41_u64)
        });
        admission.retain_original_handle(handle)
    };
    let result = jobs.receive_registered_job(job).await?;
    assert_eq!(result, Ok(41));
    assert_eq!(lane.available_permits(), 1);
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    jobs.gate.require_open()?;
    assert_eq!(jobs.close_and_join().await, Ok(()));
    Ok(())
}
