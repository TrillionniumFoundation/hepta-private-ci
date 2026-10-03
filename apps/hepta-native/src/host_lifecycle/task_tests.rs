use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::SupervisedTask;

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
fn cancelled_waiting_task_never_enters_the_runtime() {
    let (release, wait) = mpsc::channel();
    let mut task = SupervisedTask::spawn(
        "cancel-before-admission",
        || {},
        move |admission| {
            wait.recv().unwrap();
            admission.begin()
        },
    )
    .unwrap();
    assert!(task.poll().is_none());
    assert!(task.cancel_before_admission());
    release.send(()).unwrap();
    assert_eq!(
        finish(&mut task),
        Ok(Err("native task cancelled before runtime admission"))
    );
    assert!(task.poll().is_none());
}

#[test]
fn cancelled_runtime_lock_waiter_exits_without_owner_entry() {
    let owner = Arc::new(Mutex::new(()));
    let owner_guard = owner.lock().unwrap();
    let worker_owner = Arc::clone(&owner);
    let (waiting_tx, waiting_rx) = mpsc::channel();
    let mut task = SupervisedTask::spawn(
        "cancel-lock-wait",
        || {},
        move |admission| {
            waiting_tx.send(()).unwrap();
            admission
                .wait_lock(&worker_owner, Duration::from_secs(5))
                .map(|_| ())
        },
    )
    .unwrap();
    waiting_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(task.cancel_before_admission());
    assert_eq!(
        finish(&mut task),
        Ok(Err("native task cancelled before runtime admission"))
    );
    drop(owner_guard);
}

#[test]
fn runtime_lock_wait_has_a_bounded_pre_admission_deadline() {
    let owner = Arc::new(Mutex::new(()));
    let owner_guard = owner.lock().unwrap();
    let worker_owner = Arc::clone(&owner);
    let mut task = SupervisedTask::spawn(
        "bounded-lock-wait",
        || {},
        move |admission| {
            admission
                .wait_lock(&worker_owner, Duration::from_millis(30))
                .map(|_| ())
        },
    )
    .unwrap();
    assert_eq!(
        finish(&mut task),
        Ok(Err(
            "native runtime lock deadline exceeded before admission"
        ))
    );
    drop(owner_guard);
}

#[test]
fn acquiring_the_runtime_lock_does_not_consume_admission() {
    let owner = Arc::new(Mutex::new(()));
    let worker_owner = Arc::clone(&owner);
    let mut task = SupervisedTask::spawn(
        "lock-then-admit",
        || {},
        move |admission| {
            let owner_guard = admission
                .wait_lock(&worker_owner, Duration::from_secs(1))
                .unwrap();
            let admitted = admission.begin();
            drop(owner_guard);
            admitted
        },
    )
    .unwrap();
    assert_eq!(finish(&mut task), Ok(Ok(())));
}

#[test]
fn admitted_task_is_not_interrupted_or_detached_by_cancellation() {
    let (entered, entry) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    let mut task = SupervisedTask::spawn(
        "drain-admitted",
        || {},
        move |admission| {
            admission.begin().unwrap();
            entered.send(()).unwrap();
            wait.recv().unwrap();
            "durable-terminal"
        },
    )
    .unwrap();
    entry.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(!task.cancel_before_admission());
    assert!(task.poll().is_none());
    release.send(()).unwrap();
    assert_eq!(finish(&mut task), Ok("durable-terminal"));
    assert!(task.poll().is_none());
}

#[test]
fn panic_is_joined_and_wakes_the_ui_without_manufacturing_success() {
    let wakes = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&wakes);
    let mut task = SupervisedTask::<()>::spawn(
        "panic-is-not-success",
        move || {
            observed.fetch_add(1, Ordering::SeqCst);
        },
        |admission| {
            admission.begin().unwrap();
            panic!("injected worker failure");
        },
    )
    .unwrap();
    assert_eq!(
        finish(&mut task),
        Err("native worker panicked; completion is not established")
    );
    assert_eq!(wakes.load(Ordering::SeqCst), 1);
    assert!(task.poll().is_none());
}

#[test]
fn cancellation_and_admission_have_one_winner_under_race() {
    for _ in 0..64 {
        let barrier = Arc::new(Barrier::new(2));
        let worker_barrier = Arc::clone(&barrier);
        let effects = Arc::new(AtomicUsize::new(0));
        let worker_effects = Arc::clone(&effects);
        let mut task = SupervisedTask::spawn(
            "admission-race",
            || {},
            move |admission| {
                worker_barrier.wait();
                let accepted = admission.begin();
                if accepted.is_ok() {
                    worker_effects.fetch_add(1, Ordering::SeqCst);
                }
                accepted
            },
        )
        .unwrap();
        barrier.wait();
        let cancelled = task.cancel_before_admission();
        let result = finish(&mut task).unwrap();
        assert_eq!(effects.load(Ordering::SeqCst), usize::from(result.is_ok()));
        assert_ne!(cancelled, result.is_ok());
    }
}

#[test]
fn a_task_cannot_enter_its_runtime_owner_twice() {
    let mut task = SupervisedTask::spawn(
        "double-admission",
        || {},
        |admission| {
            let first = admission.begin();
            let second = admission.begin();
            (first, second)
        },
    )
    .unwrap();
    assert_eq!(
        finish(&mut task),
        Ok((
            Ok(()),
            Err("native task admission may only be consumed once")
        ))
    );
}
