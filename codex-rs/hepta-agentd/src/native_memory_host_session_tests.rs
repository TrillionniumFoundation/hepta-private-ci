use std::assert_eq;
use std::future::pending;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::Session;
use super::SessionSlot;
use crate::native_memory_current_test_support::fixture;

#[tokio::test]
async fn busy_claim_returns_the_same_prepared_identity_after_release() {
    let fixture = fixture().await;
    let cancellation = CancellationToken::new();
    let slot = SessionSlot::new(cancellation.clone());
    let prepared = fixture.prepare("lease-normal");
    let binding = prepared.binding().clone();
    let mut lease = slot.claim().unwrap();
    lease.prepared = Some(("enrollment".into(), prepared));
    assert_eq!(
        slot.claim().err().as_deref(),
        Some("current session is busy")
    );
    drop(lease);
    let returned = slot.claim().unwrap();
    assert_eq!(
        (
            returned.attempted,
            returned
                .prepared
                .as_ref()
                .map(|(id, p)| (id.as_str(), p.binding())),
            returned.result.is_some(),
            cancellation.is_cancelled()
        ),
        (false, Some(("enrollment", &binding)), false, false),
    );
}

#[tokio::test]
async fn actual_authority_error_returns_consumed_session() {
    let fixture = fixture().await;
    let cancellation = CancellationToken::new();
    let slot = SessionSlot::new(cancellation.clone());
    slot.claim().unwrap().prepared = Some(("enrollment".into(), fixture.prepare("lease-error")));
    let result = {
        let mut lease = slot.claim().unwrap();
        lease.attempted = true;
        let (_, prepared) = lease.prepared.take().unwrap();
        let grant = fixture.sign(prepared.binding().clone(), "lease-error-grant");
        // Real owner revocation remains available while the session is owned.
        fixture.feed(/*revision*/ 3, &["lease-error-grant"]);
        prepared.authorize(&grant)
    };
    assert!(
        result
            .err()
            .unwrap()
            .to_string()
            .contains("prepared NDU binding no longer current")
    );
    let returned = slot.claim().unwrap();
    assert_eq!(
        (
            returned.attempted,
            returned.prepared.is_none(),
            returned.result.is_none(),
            cancellation.is_cancelled()
        ),
        (true, true, true, false),
    );
}

#[tokio::test]
async fn cancelling_pending_work_returns_consumed_session() {
    let fixture = fixture().await;
    let cancellation = CancellationToken::new();
    let slot = Arc::new(SessionSlot::new(cancellation.clone()));
    slot.claim().unwrap().prepared = Some(("enrollment".into(), fixture.prepare("lease-cancel")));
    let (entered_tx, entered_rx) = oneshot::channel();
    let owned = Arc::clone(&slot);
    let task = tokio::spawn(async move {
        let mut lease = owned.claim().unwrap();
        lease.attempted = true;
        let _prepared = lease.prepared.take().unwrap();
        entered_tx.send(()).unwrap();
        pending::<()>().await;
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), entered_rx)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        slot.claim().err().as_deref(),
        Some("current session is busy")
    );
    fixture.feed(/*revision*/ 3, &[]);
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    let returned = slot.claim().unwrap();
    assert_eq!(
        (
            returned.attempted,
            returned.prepared.is_none(),
            returned.result.is_none(),
            cancellation.is_cancelled()
        ),
        (true, true, true, false),
    );
}

fn poison(slot: &SessionSlot) {
    assert!(
        std::panic::catch_unwind(AssertUnwindSafe(|| {
            let _guard = slot.slot.lock().unwrap();
            panic!("injected slot poisoning");
        }))
        .is_err()
    );
}

#[test]
fn poisoned_claim_closes_runtime_without_clearing_poison() {
    let cancellation = CancellationToken::new();
    let slot = SessionSlot::new(cancellation.clone());
    poison(&slot);
    assert_eq!(
        slot.claim().err().as_deref(),
        Some("current session is poisoned")
    );
    assert_eq!(
        (cancellation.is_cancelled(), slot.slot.is_poisoned()),
        (true, true)
    );
}

#[test]
fn poisoned_return_preserves_spent_state_and_closes_runtime() {
    let cancellation = CancellationToken::new();
    let slot = SessionSlot::new(cancellation.clone());
    let mut lease = slot.claim().unwrap();
    lease.attempted = true;
    poison(&slot);
    drop(lease);
    let retained = slot.slot.lock().err().unwrap().into_inner();
    assert_eq!(
        (
            retained.as_ref().map(|state| state.attempted),
            cancellation.is_cancelled(),
            slot.slot.is_poisoned()
        ),
        (Some(true), true, true),
    );
    drop(retained);
    assert!(slot.claim().is_err());
}

#[tokio::test]
async fn occupied_return_preserves_incumbent_and_closes_runtime() {
    let fixture = fixture().await;
    let cancellation = CancellationToken::new();
    let slot = SessionSlot::new(cancellation.clone());
    let mut lease = slot.claim().unwrap();
    lease.attempted = true;
    *slot.slot.lock().unwrap() = Some(Session {
        prepared: Some(("incumbent".into(), fixture.prepare("lease-incumbent"))),
        ..Session::default()
    });
    drop(lease);
    let retained = slot.slot.lock().unwrap();
    let retained = retained.as_ref().unwrap();
    assert_eq!(
        (
            retained.attempted,
            retained.prepared.as_ref().map(|(id, _)| id.as_str()),
            cancellation.is_cancelled()
        ),
        (false, Some("incumbent"), true),
    );
    assert!(slot.claim().is_err());
}
