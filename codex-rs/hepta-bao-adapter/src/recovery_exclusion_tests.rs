use std::future::Future;
use std::future::pending;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Barrier;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use pretty_assertions::assert_eq;

use super::*;

fn registry() -> (tempfile::TempDir, Mutex<DurableLeaseRegistryV1>) {
    let directory = tempfile::tempdir().expect("private test directory");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private permissions");
    let owner = DurableLeaseRegistryV1::open(directory.path().join("owner.json"))
        .expect("durable owner");
    (directory, Mutex::new(owner))
}

#[test]
fn live_request_excludes_a_second_host_and_recovery_until_guard_drop() {
    let (_directory, registry) = registry();
    let running = BaoExecutionGuard::try_enter(&registry).expect("first owner entry");
    assert!(matches!(
        BaoExecutionGuard::try_enter(&registry),
        Err(LeaseRegistryErrorV1::WriterBusy)
    ));
    drop(running);
    drop(BaoExecutionGuard::try_enter(&registry).expect("recovery after request completion"));
}

#[test]
fn independent_owners_do_not_share_a_global_execution_lock() {
    let (_first_directory, first) = registry();
    let (_second_directory, second) = registry();
    let _first = BaoExecutionGuard::try_enter(&first).expect("first registry");
    let _second = BaoExecutionGuard::try_enter(&second).expect("independent registry");
}

#[test]
fn cancellation_releases_the_local_execution_fence_without_running_a_callback() {
    let (_directory, registry) = registry();
    let mut future = Box::pin(async {
        let _guard = BaoExecutionGuard::try_enter(&registry).expect("request entry");
        pending::<()>().await;
        panic!("cancelled request must not enter a consumer");
    });
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(future.as_mut().poll(&mut context), Poll::Pending);
    assert!(matches!(
        BaoExecutionGuard::try_enter(&registry),
        Err(LeaseRegistryErrorV1::WriterBusy)
    ));
    drop(future);
    drop(BaoExecutionGuard::try_enter(&registry).expect("observation-only recovery"));
}

#[test]
fn cross_thread_recovery_cannot_enter_a_live_owner() {
    let (_directory, registry) = registry();
    let registry = Arc::new(registry);
    let entered = Arc::new(Barrier::new(2));
    let finish = Arc::new(Barrier::new(2));
    let task = {
        let registry = Arc::clone(&registry);
        let entered = Arc::clone(&entered);
        let finish = Arc::clone(&finish);
        std::thread::spawn(move || {
            let _guard = BaoExecutionGuard::try_enter(&registry).expect("live request");
            entered.wait();
            finish.wait();
        })
    };
    entered.wait();
    assert!(matches!(
        BaoExecutionGuard::try_enter(&registry),
        Err(LeaseRegistryErrorV1::WriterBusy)
    ));
    finish.wait();
    task.join().expect("request thread");
    drop(BaoExecutionGuard::try_enter(&registry).expect("recovery after request thread"));
}
