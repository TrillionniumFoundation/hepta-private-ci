use super::*;
use std::sync::atomic::AtomicUsize;

#[test]
fn robrix_close_drains_the_original_owner_before_exit() {
    let root = tempfile::TempDir::new().unwrap();
    let app = crate::ui::input_event_tests::app_fixture(root.path());
    let activation = Arc::clone(&app.activate_update_on_exit);
    let mut host = RobrixHost { app };
    let loading = host.poll();
    host.request_close();
    host.request_close();
    assert!(!host.app.shutdown.runtime_closed);
    let closing = host.poll();
    assert_eq!(closing.phase, NativeHostPhase::Closing);
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if host.poll().phase == NativeHostPhase::Closed {
            break;
        }
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    }
    assert!(host.app.shutdown.runtime_closed && host.app.all_tasks_idle());
    let closed = host.poll();
    let status_text = [loading.status, closing.status, closed.status].join("\n");
    insta::with_settings!({prepend_module_to_snapshot => false}, {
        insta::assert_snapshot!("robrix_owner_status_transitions", status_text);
    });
    host.on_exit();
    assert!(!activation.load(Ordering::Acquire));
}

#[test]
fn renderer_wake_keeps_the_original_history_worker_and_join() {
    let root = tempfile::TempDir::new().unwrap();
    let app = crate::ui::input_event_tests::app_fixture(root.path());
    let mut host = RobrixHost { app };
    let wakes = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&wakes);
    host.set_waker(Arc::new(move || {
        observed.fetch_add(1, Ordering::SeqCst);
    }));
    host.app.load_history_page(0);
    let deadline = Instant::now() + Duration::from_secs(5);
    while host.app.any_task_active() {
        host.poll();
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    }
    assert_eq!(wakes.load(Ordering::SeqCst), 1);
    assert!(host.app.all_tasks_idle());
    assert_eq!(host.poll().phase, NativeHostPhase::Loading);
    assert!(host.app.ready_view.is_none());
}

#[test]
fn renderer_failure_and_unconfirmed_exit_cannot_activate_update() {
    let root = tempfile::TempDir::new().unwrap();
    let app = crate::ui::input_event_tests::app_fixture(root.path());
    let activation = Arc::clone(&app.activate_update_on_exit);
    let mut host = RobrixHost { app };
    host.app.shutdown.update_requested = true;
    host.rendering_failed("missing embedded resource");
    assert!(host.app.shutdown.requested());
    assert!(!host.app.shutdown.update_requested);
    assert_eq!(
        host.app.shutdown.failure.as_deref(),
        Some("missing embedded resource")
    );
    host.on_exit();
    assert!(!activation.load(Ordering::Acquire));
}

#[test]
fn renderer_invalidation_discards_the_original_first_draw_witness() {
    let root = tempfile::TempDir::new().unwrap();
    let app = crate::ui::input_event_tests::app_fixture(root.path());
    let mut host = RobrixHost { app };
    let view = RuntimeView {
        session_id: "session.one".into(),
        session_generation: 1,
        generation: 1,
        revision: 1,
        digest: "1".repeat(64),
        modules: vec!["ui.native".into()],
    };
    assert!(
        host.app
            .readiness_frames
            .observe(1, &view)
            .unwrap()
            .is_none()
    );
    host.invalidate_rendered();
    assert!(
        host.app
            .readiness_frames
            .observe(2, &view)
            .unwrap()
            .is_none()
    );
    assert!(
        host.app
            .readiness_frames
            .observe(3, &view)
            .unwrap()
            .is_some()
    );
    assert!(host.app.all_tasks_idle());
}

#[test]
fn renderer_failure_cancels_queued_readiness_before_owner_admission() {
    let root = tempfile::TempDir::new().unwrap();
    let app = crate::ui::input_event_tests::app_fixture(root.path());
    let mut host = RobrixHost { app };
    let runtime = Arc::clone(&host.app.runtime);
    let guard = runtime.lock().unwrap();
    let queued_runtime = Arc::clone(&runtime);
    let admitted = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&admitted);
    let (waiting, reached) = std::sync::mpsc::channel();
    host.app.start_task(UiTaskKind::Ready, move |admission| {
        waiting.send(()).unwrap();
        let _owner = lock_runtime_for_task(&admission, &queued_runtime)?;
        admission
            .begin()
            .map_err(|detail| ShellError::State(detail.into()))?;
        observed.store(true, Ordering::Release);
        Ok(UiTaskOutput::Ready { pending: None })
    });
    reached.recv_timeout(Duration::from_secs(5)).unwrap();
    host.rendering_failed("font disappeared while readiness was queued");
    host.request_close();
    drop(guard);
    let deadline = Instant::now() + Duration::from_secs(5);
    while host.poll().phase != NativeHostPhase::Closed {
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    }
    assert!(!admitted.load(Ordering::Acquire));
    assert!(host.app.all_tasks_idle());
    assert!(!host.app.activate_update_on_exit.load(Ordering::Acquire));
}
