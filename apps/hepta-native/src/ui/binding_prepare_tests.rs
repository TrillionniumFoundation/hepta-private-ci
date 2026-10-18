use std::sync::atomic::AtomicUsize;
use std::sync::mpsc;

use super::*;
use crate::backend::AuthenticatedRuntimeStatus;
use crate::backend::BackendAdapter;
use crate::journal::OperationRecord;
use crate::model::OperationKey;
use crate::model::PlatformObservation;
use crate::model::SessionIncarnation;
use crate::platform::PermissionDecision;
use crate::platform::PlatformAdapter;

#[path = "binding_prepare_snapshot_tests.rs"]
mod snapshots;

struct Backend(Arc<AtomicUsize>);

impl BackendAdapter for Backend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        Ok(SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: "test.session".to_owned(),
            generation: 1,
        })
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        Ok(AuthenticatedRuntimeStatus {
            value: serde_json::json!({"state": {"runtime_snapshot_generation": 1}}),
            body_digest: "2".repeat(64),
        })
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

struct BlockingConfirmation {
    entered: mpsc::Sender<PlatformPayload>,
    release: Mutex<mpsc::Receiver<()>>,
    calls: Arc<AtomicUsize>,
}

impl PlatformAdapter for BlockingConfirmation {
    fn confirmation_resource(
        &self,
        payload: &PlatformPayload,
    ) -> Result<Option<String>, ShellError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.entered.send(payload.clone()).unwrap();
        self.release
            .lock()
            .unwrap()
            .recv_timeout(Duration::from_secs(5))
            .map_err(|error| ShellError::Platform(error.to_string()))?;
        Ok(Some("3".repeat(64)))
    }

    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        panic!("binding preparation must not enter effect permission")
    }

    fn invoke(
        &mut self,
        _key: &OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        panic!("binding preparation must not dispatch an effect")
    }

    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        panic!("empty fixture journal has no effects to reconcile")
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    app: HeptaNativeApp,
    entered: mpsc::Receiver<PlatformPayload>,
    release: mpsc::Sender<()>,
    calls: Arc<AtomicUsize>,
    closes: Arc<AtomicUsize>,
}

fn fixture() -> Fixture {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = super::super::input_event_tests::app_fixture(root.path());
    let (entered, observed) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    let calls = Arc::new(AtomicUsize::new(0));
    let closes = Arc::new(AtomicUsize::new(0));
    let mut runtime = NativeShellRuntime::new(
        Box::new(Backend(Arc::clone(&closes))),
        Box::new(BlockingConfirmation {
            entered,
            release: Mutex::new(wait),
            calls: Arc::clone(&calls),
        }),
        None,
        crate::journal::OperationJournal::open(root.path().join("state/binding-journal.json"))
            .unwrap(),
    );
    runtime.connect_runtime(&app.manifest).unwrap();
    runtime.refresh_runtime_view().unwrap();
    app.ready_view = runtime.view().cloned();
    app.view_revision = app.ready_view.as_ref().map(|view| view.revision);
    app.connected = true;
    app.operation_subject_id = "test.subject".to_owned();
    app.operation_id = "test.operation".to_owned();
    app.operation_action = PlatformAction::OpenPath;
    app.operation_path = root
        .path()
        .join("selected-resource")
        .to_str()
        .unwrap()
        .to_owned();
    app.runtime = Arc::new(Mutex::new(runtime));
    Fixture {
        _root: root,
        app,
        entered: observed,
        release,
        calls,
        closes,
    }
}

fn finish_runtime_task(app: &mut HeptaNativeApp) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while app.pending_runtime.is_some() {
        app.poll_tasks();
        assert!(
            Instant::now() < deadline,
            "owned binding worker did not finish"
        );
        std::thread::yield_now();
    }
}

#[test]
fn prepare_returns_while_os_confirmation_is_blocked_and_discards_edited_input() {
    let mut fixture = fixture();
    let selected = PathBuf::from(&fixture.app.operation_path);
    fixture.app.prepare_operation_binding();
    assert_eq!(
        fixture.app.pending_runtime.as_ref().unwrap().kind,
        UiTaskKind::PrepareBinding
    );
    assert_eq!(
        fixture
            .entered
            .recv_timeout(Duration::from_secs(5))
            .unwrap(),
        PlatformPayload::OpenPath { path: selected }
    );
    assert!(fixture.app.operation_binding.is_none());
    fixture.app.operation_path = fixture
        ._root
        .path()
        .join("different-resource")
        .to_str()
        .unwrap()
        .to_owned();
    fixture.release.send(()).unwrap();
    finish_runtime_task(&mut fixture.app);
    assert!(fixture.app.operation_binding.is_none());
    assert!(
        fixture
            .app
            .operation_message
            .as_deref()
            .unwrap()
            .contains("discarded")
    );
}

#[test]
fn cancelled_binding_lock_waiter_never_calls_the_confirmation_owner() {
    let mut fixture = fixture();
    let owner = Arc::clone(&fixture.app.runtime);
    let guard = owner.lock().unwrap();
    fixture.app.prepare_operation_binding();
    assert!(
        fixture
            .app
            .pending_runtime
            .as_ref()
            .unwrap()
            .worker
            .cancel_before_admission()
    );
    finish_runtime_task(&mut fixture.app);
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 0);
    assert!(
        fixture
            .app
            .last_error
            .as_deref()
            .unwrap()
            .contains("cancelled before runtime admission")
    );
    drop(guard);
}

#[test]
fn changed_runtime_view_is_rejected_before_os_confirmation() {
    let mut fixture = fixture();
    let owner = Arc::clone(&fixture.app.runtime);
    let mut guard = owner.lock().unwrap();
    fixture.app.prepare_operation_binding();
    guard.refresh_runtime_view().unwrap();
    drop(guard);
    finish_runtime_task(&mut fixture.app);
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 0);
    assert!(
        fixture
            .app
            .last_error
            .as_deref()
            .unwrap()
            .contains("does not match the current runtime view")
    );
}

#[test]
fn admitted_binding_is_drained_before_shutdown_closes_the_runtime() {
    let mut fixture = fixture();
    let context = egui::Context::default();
    fixture.app.prepare_operation_binding();
    fixture
        .entered
        .recv_timeout(Duration::from_secs(5))
        .unwrap();
    fixture.app.shutdown.update_requested = true;
    fixture.app.request_shutdown(&context);
    assert!(fixture.app.pending_runtime.is_some());
    assert!(!fixture.app.shutdown.runtime_closed);
    assert_eq!(fixture.closes.load(Ordering::SeqCst), 0);
    fixture.release.send(()).unwrap();
    finish_runtime_task(&mut fixture.app);
    assert!(fixture.app.operation_binding.is_none());
    context
        .run_ui(egui::RawInput::default(), |ui| {
            assert!(fixture.app.shutdown_view(ui));
        })
        .drop_without_applying_deltas();
    finish_runtime_task(&mut fixture.app);
    assert!(fixture.app.shutdown.runtime_closed);
    assert_eq!(fixture.closes.load(Ordering::SeqCst), 1);
}

#[test]
fn completed_binding_is_invalidated_by_later_widget_input_changes() {
    let mut fixture = fixture();
    fixture.app.prepare_operation_binding();
    fixture
        .entered
        .recv_timeout(Duration::from_secs(5))
        .unwrap();
    fixture.release.send(()).unwrap();
    finish_runtime_task(&mut fixture.app);
    let binding: codex_hepta_contracts::FinalUseBinding =
        serde_json::from_str(&fixture.app.operation_binding.as_ref().unwrap().text).unwrap();
    assert_eq!(binding.subject_id, "test.subject");
    fixture.app.operation_id = "different.operation".to_owned();
    egui::Context::default()
        .run_ui(egui::RawInput::default(), |ui| {
            fixture.app.operations_view(ui);
        })
        .drop_without_applying_deltas();
    assert!(fixture.app.operation_binding.is_none());
}

#[test]
fn completed_binding_never_attaches_to_a_different_screen_or_view_identity() {
    for axis in 0..8 {
        let mut fixture = fixture();
        let binding = PreparedBinding {
            text: "exact original input".to_owned(),
            input: BindingInput::capture(&fixture.app).unwrap(),
        };
        match axis {
            0 => fixture.app.screen = Screen::Updates,
            1 => fixture.app.operation_subject_id = "different.subject".to_owned(),
            2 => fixture.app.operation_action = PlatformAction::CopyText,
            3 => {
                fixture.app.ready_view.as_mut().unwrap().session_id = "different.session".to_owned()
            }
            4 => fixture.app.ready_view.as_mut().unwrap().session_generation += 1,
            5 => fixture.app.ready_view.as_mut().unwrap().generation += 1,
            6 => fixture.app.ready_view.as_mut().unwrap().digest = "4".repeat(64),
            7 => fixture.app.view_revision = Some(2),
            _ => unreachable!(),
        }
        fixture.app.install_prepared_binding(binding);
        assert!(fixture.app.operation_binding.is_none(), "axis {axis}");
    }
}
