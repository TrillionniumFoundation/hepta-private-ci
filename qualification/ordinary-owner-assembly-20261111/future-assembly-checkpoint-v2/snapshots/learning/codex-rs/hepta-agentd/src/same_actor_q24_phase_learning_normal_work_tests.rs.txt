//! Components of the actual Work registry, blocking JoinHandles and Unix FDs.
//! No C capability, Training receipt, durable business ACK or Root completion
//! is manufactured here.

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_join_keeps_the_actual_delivered_owner_and_closes_new_admission() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (owned, mut peer) = pair()?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || Ok::<_, ()>(owned));
        admission.retain_original_handle(handle)
    };
    let original = jobs.receive_registered_job(job).await?
        .map_err(|_| anyhow::anyhow!("original result"))?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    tokio::time::timeout(WAIT, jobs.join_original_normal()).await?
        .map_err(anyhow::Error::msg)?;
    jobs.gate.require_open()?;
    assert_eq!(peer.try_read(&mut [0]).unwrap_err().kind(), io::ErrorKind::WouldBlock);
    assert!(jobs.reserve().is_err());
    assert!(jobs.gate.require_open().is_err());
    drop(original);
    require_eof(&mut peer).await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_join_refuses_and_drops_an_actual_undelivered_owner() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (owned, mut peer) = pair()?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || Ok::<_, ()>(owned));
        admission.retain_original_handle(handle)
    };
    assert!(tokio::time::timeout(WAIT, jobs.join_original_normal()).await?.is_err());
    assert!(jobs.gate.require_open().is_err());
    require_eof(&mut peer).await?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    drop(job);
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    assert!(tokio::time::timeout(WAIT, jobs.close_and_join()).await?.is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelling_normal_join_retains_the_same_real_blocking_handle_for_cleanup() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (owned, mut peer) = pair()?;
    let (started, started_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::sync_channel(1);
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            let _ = started.send(());
            release_rx.recv().map_err(|_| ())?;
            Ok::<_, ()>(owned)
        });
        admission.retain_original_handle(handle)
    };
    drop(job);
    tokio::time::timeout(WAIT, started_rx).await??;
    let mut normal = Box::pin(jobs.join_original_normal());
    tokio::select! {
        biased;
        result = &mut normal => panic!("normal join returned while actual work was blocked: {result:?}"),
        _ = tokio::task::yield_now() => {},
    }
    drop(normal);
    assert!(jobs.gate.require_open().is_err());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    assert_eq!(peer.try_read(&mut [0]).unwrap_err().kind(), io::ErrorKind::WouldBlock);
    let mut cleanup = Box::pin(jobs.close_and_join());
    tokio::select! {
        biased;
        result = &mut cleanup => panic!("cleanup returned before the real handle completed: {result:?}"),
        _ = tokio::task::yield_now() => {},
    }
    release.send(())?;
    tokio::time::timeout(WAIT, cleanup).await?
        .map_err(|_| anyhow::anyhow!("actual cleanup failed"))?;
    require_eof(&mut peer).await?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_join_waits_for_the_actual_last_job_holder_after_registry_release() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(|| Ok::<_, ()>(()));
        admission.retain_original_handle(handle)
    };
    jobs.receive_registered_job(Arc::clone(&job)).await?
        .map_err(|_| anyhow::anyhow!("actual job result"))?;
    assert!(jobs.retained.lock().unwrap().is_empty());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    let mut normal = Box::pin(jobs.join_original_normal());
    tokio::select! {
        biased;
        result = &mut normal => panic!("normal join ignored an actual outstanding holder: {result:?}"),
        _ = tokio::task::yield_now() => {},
    }
    jobs.gate.require_open()?;
    drop(job);
    tokio::time::timeout(WAIT, normal).await?.map_err(anyhow::Error::msg)?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    jobs.gate.require_open()?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn admission_racing_normal_join_cannot_start_another_original_handle() -> anyhow::Result<()> {
    let jobs = jobs()?;
    let (started, started_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::sync_channel(1);
    let job = {
        let admission = jobs.reserve()?;
        let handle = tokio::task::spawn_blocking(move || {
            let _ = started.send(());
            release_rx.recv().map_err(|_| ())?;
            Ok::<_, ()>(())
        });
        admission.retain_original_handle(handle)
    };
    drop(job);
    tokio::time::timeout(WAIT, started_rx).await??;
    let mut normal = Box::pin(jobs.join_original_normal());
    tokio::select! {
        biased;
        result = &mut normal => panic!("normal join skipped actual in-flight work: {result:?}"),
        _ = tokio::task::yield_now() => {},
    }
    assert!(jobs.reserve().is_err());
    assert!(tokio::time::timeout(WAIT, normal).await?.is_err());
    assert_eq!(jobs.pending.load(Ordering::Acquire), 1);
    release.send(())?;
    tokio::time::timeout(WAIT, jobs.close_and_join()).await?
        .map_err(|_| anyhow::anyhow!("actual cleanup failed"))?;
    assert_eq!(jobs.pending.load(Ordering::Acquire), 0);
    Ok(())
}
