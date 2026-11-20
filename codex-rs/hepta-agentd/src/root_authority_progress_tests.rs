//! Controlled same-UID peer and the real activation/refresh serial barrier.
//! This is not an original Root/HostStore or Native qualification.
use super::*;
use crate::root_observation_diagnostic::RefreshPhase;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn a_blocked_serial_barrier_reports_the_unstarted_request_and_keeps_the_fence() {
    let (session, _, peer, _) = tests::connected().await;
    session.diagnose_attach(AttachStage::OpeningFrontiers);
    // Block the actual feed's existing serial barrier. Blocking the application
    // executor alone must no longer starve the independent observation reactor.
    let live = Arc::clone(&session.live);
    let (held, holding) = tokio::sync::oneshot::channel();
    let (release, releasing) = std::sync::mpsc::channel::<()>();
    let barrier = std::thread::spawn(move || {
        let _serial = live.serial.blocking_lock();
        let _ = held.send(());
        // Dropping the sender also releases this guard if the test panics.
        let _ = releasing.recv();
    });
    holding.await.unwrap();
    let before = tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if let Some(progress) = session.live.cache.diagnostics.progress()
                && progress.refresh_phase == RefreshPhase::WaitingSerial
            {
                break progress;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(before.refresh_phase, RefreshPhase::WaitingSerial);
    assert!(before.request_sequence >= 1);
    // The dedicated reactor has woken, but cannot begin its next observation
    // while the original barrier is held. The original age limit still applies.
    std::thread::sleep(Duration::from_millis(650));
    assert!(session.clock().now_unix_ms().is_err());
    let first = session.live.cache.diagnostics.first().unwrap();
    assert_eq!(first.stage, "cache_current_age_or_rollback");
    assert_eq!(first.progress, Some(before));
    assert!(first.now_ns.unwrap() - first.previous_started_ns.unwrap() > MAX_AGE_NS);
    assert!(before.reply_ended_ns.unwrap() >= before.request_started_ns.unwrap());
    drop(release);
    barrier.join().unwrap();
    // Observe a real late reply, rather than assuming a fixed sleep let the feed
    // run. Receiving it must not revive the already fenced authority or replace
    // the diagnostic captured at the original refusal.
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if let Some(progress) = session.live.cache.diagnostics.progress()
                && progress.request_sequence > before.request_sequence
                && progress.reply_ended_ns.is_some()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(session.clock().now_unix_ms().is_err());
    assert_eq!(session.live.cache.diagnostics.first(), Some(first));
    drop(session);
    tokio::task::yield_now().await;
    peer.join().unwrap();
}
