use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::shutdown::Shutdown;
use super::task::SupervisedTask;

fn finish<T: Send + 'static>(task: &mut SupervisedTask<T>) -> Result<T, &'static str> {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(result) = task.poll() {
            return result;
        }
        assert!(Instant::now() < deadline, "test worker failed to finish");
        std::thread::yield_now();
    }
}

#[test]
fn shutdown_cancels_waiting_mutation_but_retains_admitted_owner_until_join() {
    let owner = Arc::new(Mutex::new(0));
    let admitted_owner = Arc::clone(&owner);
    let (entered, entry) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    let mut admitted = SupervisedTask::spawn(
        "lifecycle-admitted-owner",
        || {},
        move |admission| {
            let mut state = admission
                .wait_lock(&admitted_owner, Duration::from_secs(5))
                .unwrap();
            admission.begin().unwrap();
            entered.send(()).unwrap();
            wait.recv().unwrap();
            *state += 1;
            *state
        },
    )
    .unwrap();
    entry.recv_timeout(Duration::from_secs(5)).unwrap();

    let waiting_owner = Arc::clone(&owner);
    let (waiting, pending) = mpsc::channel();
    let mut cancelled = SupervisedTask::spawn(
        "lifecycle-waiting-owner",
        || {},
        move |admission| {
            waiting.send(()).unwrap();
            let mut state = admission.wait_lock(&waiting_owner, Duration::from_secs(5))?;
            admission.begin()?;
            *state += 1;
            Ok::<_, &'static str>(*state)
        },
    )
    .unwrap();
    pending.recv_timeout(Duration::from_secs(5)).unwrap();

    let mut shutdown = Shutdown::default();
    shutdown.update_requested = true;
    assert!(!shutdown.requested());
    assert!(!shutdown.close_started);
    shutdown.request(Instant::now());
    assert!(shutdown.requested());
    assert!(cancelled.cancel_before_admission());
    assert!(!admitted.cancel_before_admission());
    assert_eq!(
        finish(&mut cancelled),
        Ok(Err("native task cancelled before runtime admission"))
    );
    assert!(admitted.poll().is_none());
    assert!(!shutdown.activation_allowed());

    release.send(()).unwrap();
    assert_eq!(finish(&mut admitted), Ok(1));
    assert!(admitted.poll().is_none());
    assert_eq!(*owner.lock().unwrap(), 1);
    // Joining the admitted operation is not the runtime owner's close receipt.
    assert!(!shutdown.activation_allowed());
    shutdown.close_started = true;
    shutdown.runtime_closed = true;
    assert!(shutdown.close_started);
    assert!(shutdown.activation_allowed());
}
