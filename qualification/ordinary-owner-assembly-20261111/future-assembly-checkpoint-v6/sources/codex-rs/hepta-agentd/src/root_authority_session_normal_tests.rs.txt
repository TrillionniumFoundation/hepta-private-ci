//! Actual original Session pause components. Same-UID synthetic proof is
//! explicit: these test the worker/frame/FD custody cut, not C or Root success.

use super::*;
use crate::root_authority_session::OriginalRootSessionPaused;
use pretty_assertions::assert_eq;

fn bind_original_writer(
    session: &AgentdRootAuthoritySession,
) -> Result<(tempfile::TempDir, AgentdConfig, std::fs::File), Box<dyn Error>> {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let (trust, _) = fixture();
    let config = original_config(&directory.path().canonicalize()?, &trust)?;
    config.retain_root_session(session)?;
    let contender = OpenOptions::new().read(true).write(true)
        .open(config.identity().layout.writer_lock())?;
    Ok((directory, config, contender))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_pause_joins_the_actual_feed_but_retains_its_stream_and_original_file()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    let writer = Arc::downgrade(&session.writer_file);
    drop(config);
    let worker = session.worker.abort_handle();
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let paused = tokio::time::timeout(Duration::from_secs(5), waiter.join_original_paused()).await??;
    assert!(worker.is_finished());
    assert!(!session.live.active.load(Ordering::Acquire));
    assert!(session.live.cache.current().is_err());
    gate.require_open()?;
    OriginalRootSessionPaused::require_original_origin(&paused, &identity, &gate)?;
    let joined = paused.consumer_join_observation();
    assert_eq!((joined.registered, joined.joined), (1, 1));
    assert_eq!(joined.first_observed_failure, None);
    assert!(!joined.admission_poisoned);
    assert!(!peer.is_finished());
    assert!(writer.upgrade().is_some());
    assert!(!takes_lock(&contender)?);

    // No Root intent has been issued. Dropping Session remains fault closure,
    // and actual returned pause custody continues holding its original FD/File.
    drop(session);
    assert!(gate.require_open().is_err());
    let observed = tokio::time::timeout(
        Duration::from_secs(5), slot.stop_and_join_retired_session_tasks(),
    ).await??;
    let OriginalRootSessionJoinObservation::Joined {
        worker, recorded_worker_failure, consumers, ..
    } = observed else {
        panic!("original paused Session was not retained");
    };
    assert_eq!(worker, OriginalRootWorkerTermination::Returned);
    assert_eq!(recorded_worker_failure, None);
    assert_eq!(consumers, joined);
    assert!(!takes_lock(&contender)?);
    drop(paused);
    drop(slot);
    assert!(writer.upgrade().is_none());
    assert!(takes_lock(&contender)?);
    join_peer(peer).await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pause_request_waits_for_the_complete_original_refresh_and_real_consumer_cas()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, head, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let BlockingConsumer {
        owner: consumer, directory: _consumer_directory, entered, release, mut probe,
    } = blocking_consumer(&session, key, BlockedOutcome::Committed);
    let actual_consumer = consumer.clone();
    session.activate_original_phase_final_use_owners(vec![consumer]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    head.store(2, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(5), entered).await??;
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let mut paused = Box::pin(waiter.join_original_paused());
    std::future::poll_fn(|context| {
        assert!(std::future::Future::poll(paused.as_mut(), context).is_pending());
        Poll::Ready(())
    }).await;
    gate.require_open()?;
    assert!(session.live.active.load(Ordering::Acquire));
    assert!(matches!(probe.read(&mut [0]), Err(error)
        if error.kind() == std::io::ErrorKind::WouldBlock));
    assert!(!takes_lock(&contender)?);
    release.send(())?;
    let paused = tokio::time::timeout(Duration::from_secs(5), paused).await??;
    assert_eq!(probe.read(&mut [0])?, 0);
    assert_eq!(actual_consumer.revocation_head()?.revision, 2);
    assert!(!session.live.refresh_failed.load(Ordering::Acquire));
    let joined = paused.consumer_join_observation();
    assert_eq!((joined.registered, joined.joined), (2, 2));
    assert_eq!(joined.first_observed_failure, None);
    gate.require_open()?;
    OriginalRootSessionPaused::require_original_origin(&paused, &identity, &gate)?;
    drop(actual_consumer);
    drop(paused);
    drop(session);
    let observed = slot.stop_and_join_retired_session_tasks().await?;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined {
        worker: OriginalRootWorkerTermination::Returned, recorded_worker_failure: None, ..
    }));
    drop(slot);
    assert!(takes_lock(&contender)?);
    join_peer(peer).await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelling_normal_pause_preserves_the_actual_in_flight_consumer_for_fault_join()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, head, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let BlockingConsumer {
        owner: consumer, directory: _consumer_directory, entered, release, mut probe,
    } = blocking_consumer(&session, key, BlockedOutcome::Refused);
    session.activate_original_phase_final_use_owners(vec![consumer]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    head.store(2, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(5), entered).await??;
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let mut paused = Box::pin(waiter.join_original_paused());
    std::future::poll_fn(|context| {
        assert!(std::future::Future::poll(paused.as_mut(), context).is_pending());
        Poll::Ready(())
    }).await;
    drop(paused);
    assert!(gate.require_open().is_err());
    drop(session);
    let mut cleanup = Box::pin(slot.stop_and_join_retired_session_tasks());
    std::future::poll_fn(|context| {
        assert!(std::future::Future::poll(cleanup.as_mut(), context).is_pending());
        Poll::Ready(())
    }).await;
    assert!(matches!(probe.read(&mut [0]), Err(error)
        if error.kind() == std::io::ErrorKind::WouldBlock));
    assert!(!takes_lock(&contender)?);
    release.send(())?;
    let observed = tokio::time::timeout(Duration::from_secs(5), cleanup).await??;
    let OriginalRootSessionJoinObservation::Joined { consumers, .. } = observed else {
        panic!("cancelled normal pause lost actual worker custody");
    };
    assert_eq!((consumers.registered, consumers.joined), (2, 2));
    assert_eq!(consumers.first_observed_failure, Some(OriginalConsumerFailure::Owner(
        AgentdRootAuthorityError::Unavailable,
    )));
    assert_eq!(probe.read(&mut [0])?, 0);
    drop(slot);
    assert!(takes_lock(&contender)?);
    join_peer(peer).await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropping_an_unpolled_pause_waiter_never_means_normal_session_completion()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let never_polled = waiter.join_original_paused();
    drop(never_polled);
    assert!(gate.require_open().is_err());
    assert!(!takes_lock(&contender)?);
    drop(session);
    let observed = tokio::time::timeout(
        Duration::from_secs(5), slot.stop_and_join_retired_session_tasks(),
    ).await??;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined { .. }));
    drop(slot);
    assert!(takes_lock(&contender)?);
    join_peer(peer).await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_pause_request_is_one_time_and_duplicate_refusal_stays_closed()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    assert!(slot.component_request_original_normal_pause(&identity).is_err());
    assert!(gate.require_open().is_err());
    assert!(waiter.join_original_paused().await.is_err());
    drop(session);
    let observed = tokio::time::timeout(
        Duration::from_secs(5), slot.stop_and_join_retired_session_tasks(),
    ).await??;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined { .. }));
    drop(slot);
    assert!(takes_lock(&contender)?);
    join_peer(peer).await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn releasing_the_joined_observation_fd_preserves_failure_guards_and_original_file()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let paused = tokio::time::timeout(Duration::from_secs(5), waiter.join_original_paused()).await??;
    // Component-only entry exercises the very same actual stream/alias take.
    // No Root intent or C capability is manufactured by this FD custody test.
    let retired = paused.component_release_original_observation_purpose()?;
    tokio::time::timeout(Duration::from_secs(5), join_peer(peer)).await?;
    gate.require_open()?;
    crate::root_authority_session::OriginalRootSessionObservationRetired::require_original_origin(
        &retired, &identity, &gate,
    )?;
    assert!(!takes_lock(&contender)?);
    // Armed failure closure was retained after purpose EOF, not discarded.
    drop(retired);
    assert!(gate.require_open().is_err());
    drop(session);
    let observed = slot.stop_and_join_retired_session_tasks().await?;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined {
        worker: OriginalRootWorkerTermination::Returned, recorded_worker_failure: None, ..
    }));
    drop(slot);
    assert!(takes_lock(&contender)?);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_session_field_retirement_releases_the_actual_file_while_slot_is_still_owned()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let paused = tokio::time::timeout(Duration::from_secs(5), waiter.join_original_paused()).await??;
    assert_eq!((paused.consumer_join_observation().registered,
        paused.consumer_join_observation().joined), (1, 1));
    let retired = paused.component_release_original_observation_purpose()?;
    tokio::time::timeout(Duration::from_secs(5), join_peer(peer)).await?;
    gate.require_open()?;
    assert!(!takes_lock(&contender)?);

    // These components exercise only real fields/File cleanup. They do not
    // fabricate the production Root-exit capability or a business completion.
    drop(session);
    assert!(gate.require_open().is_err());
    let finished = slot.component_finish_original_retired_session(retired)?;
    assert!(takes_lock(&contender)?);
    // Keep both the finished observation and original outer slot alive: the
    // original File was consumed by the actual transition, not by their Drop.
    assert!(matches!(slot.stop_and_join_retired_session_tasks().await?,
        OriginalRootSessionJoinObservation::NotRegistered { slot_poisoned: false }));
    drop(finished);
    drop(slot);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_session_field_retirement_refuses_a_still_owned_actual_session()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let paused = tokio::time::timeout(Duration::from_secs(5), waiter.join_original_paused()).await??;
    let retired = paused.component_release_original_observation_purpose()?;
    tokio::time::timeout(Duration::from_secs(5), join_peer(peer)).await?;
    assert!(slot.component_finish_original_retired_session(retired).is_err());
    assert!(gate.require_open().is_err());
    assert!(!takes_lock(&contender)?);

    // Refusal retained the actual outer custody. Fault cleanup still observes
    // the same already returned handles after the real Session finally drops.
    drop(session);
    let observed = slot.stop_and_join_retired_session_tasks().await?;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined {
        worker: OriginalRootWorkerTermination::Returned, recorded_worker_failure: None, ..
    }));
    assert!(!takes_lock(&contender)?);
    drop(slot);
    assert!(takes_lock(&contender)?);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_session_field_retirement_refuses_an_extra_original_file_owner()
-> Result<(), Box<dyn Error>> {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, key, gate, .. } = phase_connection(&slot).await;
    let session = session?;
    let (device, _, _device_directory) = owner(&session, key);
    session.activate_original_phase_final_use_owners(vec![device]).await?;
    let (_directory, config, contender) = bind_original_writer(&session)?;
    let identity = config.identity().clone();
    let extra_file_owner = Arc::clone(session.writer_file.get()
        .ok_or("actual original writer File was not retained")?);
    drop(config);
    let waiter = slot.component_request_original_normal_pause(&identity)?;
    let paused = tokio::time::timeout(Duration::from_secs(5), waiter.join_original_paused()).await??;
    let retired = paused.component_release_original_observation_purpose()?;
    tokio::time::timeout(Duration::from_secs(5), join_peer(peer)).await?;
    drop(session);

    // The actual Session's last field and all joins have completed, but this
    // separate real File owner still exists. That cannot become FullyRetired.
    assert!(slot.component_finish_original_retired_session(retired).is_err());
    assert!(gate.require_open().is_err());
    assert!(!takes_lock(&contender)?);
    drop(extra_file_owner);
    assert!(!takes_lock(&contender)?);
    let observed = slot.stop_and_join_retired_session_tasks().await?;
    assert!(matches!(observed, OriginalRootSessionJoinObservation::Joined {
        worker: OriginalRootWorkerTermination::Returned, recorded_worker_failure: None, ..
    }));
    drop(slot);
    assert!(takes_lock(&contender)?);
    Ok(())
}
