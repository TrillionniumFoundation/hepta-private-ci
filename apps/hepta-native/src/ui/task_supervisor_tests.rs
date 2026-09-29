use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::FileInputError;
use super::FileInputIntent;
use super::FileInputTarget;
use super::SupervisedTask;
use super::accept_file_input_result;
use super::active_file_input;
use super::arm_file_input;
use super::cancel_file_input;

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

fn absolute_path(name: &str) -> PathBuf {
    #[cfg(windows)]
    {
        PathBuf::from(format!(r"C:\hepta-native\{name}"))
    }
    #[cfg(not(windows))]
    {
        PathBuf::from(format!("/tmp/hepta-native/{name}"))
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

#[test]
fn file_input_success_is_single_use_and_requires_an_absolute_path() {
    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::UpdateManifest).unwrap();
    let selected = absolute_path("manifest.json");
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(selected.clone())]
        ),
        Ok(selected)
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("manifest-2.json"))]
        ),
        Err(FileInputError::NoActiveIntent)
    );
}

#[test]
fn cancelled_or_replaced_file_input_rejects_stale_results() {
    let mut intent = FileInputIntent::default();
    let cancelled = intent.arm(FileInputTarget::OperationGrant).unwrap();
    assert_eq!(intent.cancel(), Some(cancelled));
    let current = intent.arm(FileInputTarget::UpdatePackage).unwrap();

    assert_eq!(
        intent.accept(
            cancelled,
            FileInputTarget::OperationGrant,
            &[Some(absolute_path("grant.json"))]
        ),
        Err(FileInputError::StaleIntent)
    );
    assert_eq!(intent.active(), Some(current));
    assert_eq!(
        intent.accept(
            current,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("package.zip"))]
        ),
        Ok(absolute_path("package.zip"))
    );
}

#[test]
fn callback_results_are_bound_to_the_exact_context_ticket() {
    let context = eframe::egui::Context::default();
    let cancelled = arm_file_input(&context, FileInputTarget::OperationGrant).unwrap();
    assert_eq!(cancel_file_input(&context), Some(cancelled));
    let current = arm_file_input(&context, FileInputTarget::UpdateManifest).unwrap();

    assert_eq!(
        accept_file_input_result(
            &context,
            cancelled,
            FileInputTarget::OperationGrant,
            &[Some(absolute_path("stale-grant.json"))]
        ),
        Err(FileInputError::StaleIntent)
    );
    assert_eq!(active_file_input(&context), Some(current));
    assert_eq!(
        accept_file_input_result(
            &context,
            current,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("wrong-package.zip"))]
        ),
        Err(FileInputError::WrongTarget {
            expected: FileInputTarget::UpdateManifest,
            actual: FileInputTarget::UpdatePackage,
        })
    );
    assert_eq!(active_file_input(&context), Some(current));
    assert_eq!(
        accept_file_input_result(
            &context,
            current,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("manifest.json"))]
        ),
        Ok(absolute_path("manifest.json"))
    );
    assert_eq!(active_file_input(&context), None);
}

#[test]
fn wrong_target_and_invalid_drop_do_not_consume_the_active_intent() {
    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::UpdateManifest).unwrap();

    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("package.zip"))]
        ),
        Err(FileInputError::WrongTarget {
            expected: FileInputTarget::UpdateManifest,
            actual: FileInputTarget::UpdatePackage,
        })
    );
    assert_eq!(intent.active(), Some(ticket));

    assert_eq!(
        intent.accept(ticket, FileInputTarget::UpdateManifest, &[]),
        Err(FileInputError::InvalidSelectionCount { actual: 0 })
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("one")), Some(absolute_path("two"))]
        ),
        Err(FileInputError::InvalidSelectionCount { actual: 2 })
    );
    assert_eq!(
        intent.accept(ticket, FileInputTarget::UpdateManifest, &[None]),
        Err(FileInputError::MissingFilesystemPath)
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(PathBuf::from("relative.json"))]
        ),
        Err(FileInputError::RelativePath)
    );
    assert_eq!(intent.active(), Some(ticket));
}
