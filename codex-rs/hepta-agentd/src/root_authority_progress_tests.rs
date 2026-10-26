//! Controlled same-UID peer; deliberate single-worker starvation is a host
//! scheduling fixture, not an original Root/HostStore or Native qualification.
use super::*;
use crate::root_observation_diagnostic::RefreshPhase;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn a_blocked_single_worker_reports_the_unstarted_next_poll_and_keeps_the_fence() {
    let (session, _, peer, _) = tests::connected().await;
    session.diagnose_attach(AttachStage::OpeningFrontiers);
    let before = tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let progress = session.live.cache.diagnostics.progress().unwrap();
            if progress.refresh_phase == RefreshPhase::Sleeping {
                break progress;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(before.refresh_phase, RefreshPhase::Sleeping);
    assert!(before.request_sequence >= 1);
    // No await: the same sole async executor cannot poll its ready feed.
    std::thread::sleep(Duration::from_millis(650));
    assert!(session.clock().now_unix_ms().is_err());
    let first = session.live.cache.diagnostics.first().unwrap();
    assert_eq!(first.stage, "cache_current_age_or_rollback");
    assert_eq!(first.progress, Some(before));
    assert!(first.now_ns.unwrap() - first.previous_started_ns.unwrap() > MAX_AGE_NS);
    assert!(before.reply_ended_ns.unwrap() >= before.request_started_ns.unwrap());
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert!(session.clock().now_unix_ms().is_err());
    assert_eq!(session.live.cache.diagnostics.first(), Some(first));
    drop(session);
    tokio::task::yield_now().await;
    peer.join().unwrap();
}
