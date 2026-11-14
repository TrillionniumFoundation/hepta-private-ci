use std::sync::atomic::Ordering;

use std::assert_eq;

use crate::NativeMemoryContextAuthorityV1;
use crate::native_memory_current_test_support::digest;
use crate::native_memory_current_test_support::fixture;
use crate::native_memory_current_test_support::id;

#[tokio::test]
async fn current_context_uses_actual_owners_and_exact_query_without_reclaiming() {
    let f = fixture().await;
    let query = f.query("read-current");
    let prepared = f.host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f.sign(prepared.binding().clone(), "read-current");
    let mut context = prepared.authorize(&signed).unwrap();
    let frontier = f.authority.frontier().unwrap();
    let first = context.current().unwrap();
    for _ in 0..3 {
        assert_eq!(context.current().unwrap(), first);
    }
    assert_eq!(f.authority.frontier().unwrap(), frontier);
    assert_eq!(
        first.subject_id.as_str(),
        f.objective.state.identity().agent_id.as_str()
    );
    assert_eq!(
        first.objective_digest,
        f.objective.record.snapshot.objective_digest
    );
    assert_ne!(first.ndu_snapshot_digest, digest("first"));
    assert_eq!(context.binding().unwrap().run_id(), &id("run.current"));
    context.validate_query(&query).unwrap();
    let mut changed = query.clone();
    changed.request_id = id("different-request");
    assert!(context.validate_query(&changed).is_err());
    changed = query.clone();
    changed.deadline_unix_ms -= 1;
    assert!(context.validate_query(&changed).is_err());
    changed = query.clone();
    changed.key.entity = "other-project".into();
    assert!(context.validate_query(&changed).is_err());
    let replay = f.host.prepare_read("run.current", query).unwrap();
    assert!(replay.authorize(&signed).is_err());
    assert!(
        f.host
            .prepare_read("unknown-run", f.query("unknown"))
            .is_err()
    );
}

#[tokio::test]
async fn prepared_read_refuses_intervening_ndu_change_before_spending_grant() {
    let f = fixture().await;
    let prepared = f.prepare("before-selection");
    let signed = f.sign(prepared.binding().clone(), "before-selection");
    f.select("second", "switch-selected");
    let frontier = f.authority.frontier().unwrap();
    assert!(prepared.authorize(&signed).is_err());
    assert_eq!(f.authority.frontier().unwrap(), frontier);
    let prepared = f.prepare("after-selection");
    let signed = f.sign(prepared.binding().clone(), "after-selection");
    let mut context = prepared.authorize(&signed).unwrap();
    context.current().unwrap();
    f.select("first", "switch-back");
    assert!(context.current().is_err());
}

#[tokio::test]
async fn objective_lifecycle_and_trust_revoke_an_existing_current_context() {
    for revoke_trust in [false, true] {
        let f = fixture().await;
        let prepared = f.prepare("before-objective-change");
        let signed = f.sign(prepared.binding().clone(), "before-objective-change");
        let mut context = prepared.authorize(&signed).unwrap();
        context.current().unwrap();
        if revoke_trust {
            f.objective.trust(/*epoch*/ 1, /*revoked*/ true);
        } else {
            f.objective
                .state
                .response(
                    /*request_id*/ 190,
                    /*spawn_generation*/ 1,
                    crate::AgentdMethod::RunCancel {
                        run_id: "run.current".into(),
                        expected_revision: 1,
                        reason: "current-context-test".into(),
                    },
                )
                .await
                .unwrap();
        }
        assert!(context.current().is_err());
    }
}

#[tokio::test]
async fn grant_revocation_and_authenticated_clock_expiry_refuse_current_use() {
    for revoke in [false, true] {
        let f = fixture().await;
        let prepared = f.prepare("revocable-read");
        let signed = f.sign(prepared.binding().clone(), "revocable-read");
        let mut context = prepared.authorize(&signed).unwrap();
        context.current().unwrap();
        if revoke {
            f.feed(/*revision*/ 3, &["revocable-read"]);
        } else {
            f.wall.0.fetch_add(61_000, Ordering::SeqCst);
        }
        assert!(context.current().is_err());
    }
}

#[tokio::test]
async fn clock_continuity_loss_and_runtime_shutdown_fence_existing_handles() {
    for change_domain in [false, true] {
        let f = fixture().await;
        let prepared = f.prepare("clock-bound-read");
        let signed = f.sign(prepared.binding().clone(), "clock-bound-read");
        let mut context = prepared.authorize(&signed).unwrap();
        f.tick.0.lock().unwrap().monotonic_micros = 2;
        context.current().unwrap();
        if change_domain {
            f.tick.0.lock().unwrap().domain = digest("different-clock-domain");
        } else {
            f.tick.0.lock().unwrap().monotonic_micros = 1;
        }
        assert!(context.current().is_err());
        assert!(f.host.cancellation.is_cancelled());
        f.tick.0.lock().unwrap().monotonic_micros = 3;
        assert!(context.current().is_err());
        assert!(
            f.host
                .prepare_read("run.current", f.query("after-closure"))
                .is_err()
        );
    }
    let f = fixture().await;
    let prepared = f.prepare("shutdown-read");
    let signed = f.sign(prepared.binding().clone(), "shutdown-read");
    let mut context = prepared.authorize(&signed).unwrap();
    f.host.cancellation.cancel();
    assert!(context.current().is_err());
}
