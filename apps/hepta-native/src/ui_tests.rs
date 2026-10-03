use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::Locale;
use super::UiTaskKind;
use super::UiTaskOutput;
use super::render_runtime_status;
use super::spawn_ui_task;
use crate::error::ShellError;

#[test]
fn readiness_failure_cancels_waiting_task_and_retains_admitted_task() {
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;

    for (admitted_before_failure, already_requested) in
        [(false, false), (true, false), (false, true), (true, true)]
    {
        let root = tempfile::TempDir::new().unwrap();
        let mut app = super::input_event_tests::app_fixture(root.path());
        let called = Arc::new(AtomicBool::new(false));
        let observed = Arc::clone(&called);
        let (entered, arrived) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        app.start_task(UiTaskKind::Ready, move |admission| {
            if admitted_before_failure {
                admission
                    .begin()
                    .map_err(|detail| ShellError::State(detail.into()))?;
            }
            entered.send(()).unwrap();
            wait.recv().unwrap();
            if !admitted_before_failure {
                admission
                    .begin()
                    .map_err(|detail| ShellError::State(detail.into()))?;
            }
            observed.store(true, Ordering::Release);
            Ok(UiTaskOutput::Ready { pending: None })
        });
        arrived.recv_timeout(Duration::from_secs(5)).unwrap();
        if already_requested {
            app.shutdown.request(Instant::now());
        }
        app.fail_readiness("render witness failed".into());
        app.advance_shutdown_owner();
        assert!(app.any_task_active());
        assert!(!app.shutdown.close_started);
        release.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while app.any_task_active() {
            app.poll_tasks();
            assert!(Instant::now() < deadline);
            std::thread::yield_now();
        }
        assert_eq!(called.load(Ordering::Acquire), admitted_before_failure);
        assert!(app.shutdown.requested());
        assert!(!app.shutdown.activation_allowed());
        assert!(!app.activate_update_on_exit.load(Ordering::Acquire));
    }

    // Repeated failures must not cancel the final cleanup worker itself.
    let root = tempfile::TempDir::new().unwrap();
    let mut app = super::input_event_tests::app_fixture(root.path());
    let runtime = Arc::clone(&app.runtime);
    let guard = runtime.lock().unwrap();
    app.request_shutdown_owner(|| {});
    app.advance_shutdown_owner();
    assert!(app.shutdown.close_started);
    app.fail_readiness("failure while cleanup is waiting for its owner".into());
    drop(guard);
    let deadline = Instant::now() + Duration::from_secs(5);
    while app.any_task_active() {
        app.poll_tasks();
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    }
    assert!(app.shutdown.runtime_closed && app.all_tasks_idle());
    app.finish_renderer_exit();
    assert!(!app.activate_update_on_exit.load(Ordering::Acquire));
}

#[test]
fn worker_slot_returns_before_the_bounded_task_completes() {
    let (release, wait) = mpsc::channel();
    let mut pending = spawn_ui_task(
        UiTaskKind::Refresh,
        Arc::new(Mutex::new(super::NativeWake::default())),
        move |admission| {
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            wait.recv()
                .map_err(|error| ShellError::State(error.to_string()))?;
            Err::<UiTaskOutput, ShellError>(ShellError::State("worker-finished".to_owned()))
        },
    )
    .unwrap();
    assert!(pending.worker.poll().is_none());
    release.send(()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let outcome = loop {
        if let Some(outcome) = pending.worker.poll() {
            break outcome.unwrap();
        }
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    };
    assert_eq!(
        outcome.unwrap_err(),
        "native-shell state violation: worker-finished"
    );
}

#[test]
fn locale_selection_covers_chinese_and_safe_english_fallback() {
    for value in ["zh", "zh_CN.UTF-8", "ZH-tw", " zh_Hans "] {
        assert_eq!(Locale::from_name(value), Locale::Chinese);
    }
    for value in ["", "C", "C.UTF-8", "en_US.UTF-8", "ja_JP.UTF-8"] {
        assert_eq!(Locale::from_name(value), Locale::English);
    }
    assert_eq!(Locale::Chinese.text("English", "中文"), "中文");
    assert_eq!(Locale::English.text("English", "中文"), "English");
}

#[test]
fn runtime_status_rendering_is_stable_pretty_json() {
    let value = serde_json::json!({
        "generation": 7,
        "state": {"connected": true, "pending": 0}
    });
    let rendered = render_runtime_status(&value).unwrap();
    assert_eq!(rendered, serde_json::to_string_pretty(&value).unwrap());
    assert!(rendered.contains('\n'));
}
