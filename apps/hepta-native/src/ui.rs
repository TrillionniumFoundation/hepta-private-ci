mod binding_prepare;
// This canonical API also contains geometry and labels used by the web host.
mod chat_app;
mod chat_bridge;
pub use chat_app::show_chat_setup_shell;
#[allow(dead_code)]
#[path = "../../hepta-ui-shared/chat.rs"]
mod chat_model;
mod chat_view;
mod history_page;
mod native_picker;
mod operations_view;
mod path_input;
mod readiness;
mod runtime_status;
mod shell_view;
mod shutdown;
mod startup_recovery;
mod task_supervisor;
mod theme;
mod update_views;

pub use self::startup_recovery::{
    StartupDecision, StartupFailure, StartupRetry, StartupStage, show_startup_recovery,
};

use self::binding_prepare::PreparedBinding;
use self::history_page::HISTORY_PAGE_SIZE;
use self::readiness::ReadinessFrames;
use self::runtime_status::render_runtime_status;
use self::shutdown::Shutdown;
use self::task_supervisor::FileInputTarget;
use self::task_supervisor::FileInputTicket;
use self::task_supervisor::SupervisedTask;
use self::task_supervisor::TaskAdmission;
use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::PlatformAction;
use crate::model::PlatformPayload;
use crate::model::PlatformReceipt;
use crate::model::PlatformRequest;
use crate::model::RuntimeView;
use crate::runtime::NativeShellRuntime;
use crate::runtime::OperationHistoryPage;
use crate::security::now_unix_ms;
use crate::session_store::SessionReferenceStore;
use crate::updater::PendingUpdateStatus;
use crate::updater::PendingUpdateV1;
use crate::updater::SignedUpdateManifestV1;
use crate::updater::UpdateManager;
use codex_hepta_contracts::SignedFinalUseGrant;
use eframe::egui;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

/// Run only the bounded, unprivileged native picker helper protocol.
/// The dialog result remains untrusted input and never grants effect authority.
#[cfg(any(target_os = "macos", target_os = "windows"))]
pub fn run_picker_helper() -> Result<(), ShellError> {
    native_picker::run_helper()
}

const RUNTIME_LOCK_WAIT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Screen {
    Runtime,
    Operations,
    Updates,
    Accessibility,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Locale {
    English,
    Chinese,
}

impl Locale {
    fn detect() -> Self {
        let locale = std::env::var("LC_ALL")
            .or_else(|_| std::env::var("LC_MESSAGES"))
            .or_else(|_| std::env::var("LANG"))
            .unwrap_or_default();
        Self::from_name(&locale)
    }

    fn from_name(locale: &str) -> Self {
        if locale.trim().to_ascii_lowercase().starts_with("zh") {
            Self::Chinese
        } else {
            Self::English
        }
    }

    fn text(self, english: &'static str, chinese: &'static str) -> &'static str {
        match self {
            Self::English => english,
            Self::Chinese => chinese,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum UiTaskKind {
    Refresh,
    Reconcile,
    Execute,
    PrepareBinding,
    StageUpdate,
    Ready,
    History,
    PickFile,
    Shutdown,
}

impl UiTaskKind {
    fn thread_name(self) -> &'static str {
        match self {
            Self::Refresh => "hepta-native-refresh",
            Self::Reconcile => "hepta-native-reconcile",
            Self::Execute => "hepta-native-effect",
            Self::PrepareBinding => "hepta-native-binding-prepare",
            Self::StageUpdate => "hepta-native-update-stage",
            Self::Ready => "hepta-native-readiness",
            Self::History => "hepta-native-history-read",
            Self::PickFile => "hepta-native-file-picker",
            Self::Shutdown => "hepta-native-shutdown",
        }
    }

    fn label(self, locale: Locale) -> &'static str {
        match self {
            Self::Refresh => locale.text("Refreshing runtime", "正在刷新运行时"),
            Self::Reconcile => locale.text("Reconciling operations", "正在对账操作"),
            Self::Execute => locale.text("Executing bounded operation", "正在执行受限操作"),
            Self::PrepareBinding => locale.text("Preparing exact binding", "正在生成精确 binding"),
            Self::StageUpdate => locale.text("Verifying and staging update", "正在验证并暂存更新"),
            Self::Ready => locale.text("Recording verified GUI readiness", "正在记录界面就绪状态"),
            Self::History => locale.text("Reading one history page", "正在读取一页历史"),
            Self::PickFile => locale.text("Selecting one input file", "正在选择一个输入文件"),
            Self::Shutdown => locale.text("Closing runtime", "正在关闭运行时"),
        }
    }
}

#[derive(Debug)]
enum UiTaskOutput {
    Shutdown,
    PrepareBinding(PreparedBinding),
    Refresh {
        status_rendered: String,
        view_revision: u64,
        ready_view: RuntimeView,
        history: OperationHistoryPage,
    },
    Reconcile {
        history: OperationHistoryPage,
    },
    Execute {
        message: String,
        history: OperationHistoryPage,
    },
    History {
        history: OperationHistoryPage,
    },
    StageUpdate {
        message: String,
        pending: Box<PendingUpdateV1>,
    },
    Ready {
        pending: Option<Box<PendingUpdateV1>>,
    },
    PickedFile {
        ticket: FileInputTicket,
        path: Option<PathBuf>,
    },
}

struct PendingUiTask {
    kind: UiTaskKind,
    worker: SupervisedTask<Result<UiTaskOutput, String>>,
}

type JoinedUiTask = Result<Result<UiTaskOutput, String>, &'static str>;

fn lock_runtime_for_task<'a>(
    admission: &TaskAdmission,
    runtime: &'a Arc<Mutex<NativeShellRuntime>>,
) -> Result<std::sync::MutexGuard<'a, NativeShellRuntime>, ShellError> {
    admission
        .wait_lock(runtime.as_ref(), RUNTIME_LOCK_WAIT)
        .map_err(|message| ShellError::State(message.to_owned()))
}

fn spawn_ui_task<F>(
    kind: UiTaskKind,
    repaint: Arc<Mutex<Option<egui::Context>>>,
    task: F,
) -> std::io::Result<PendingUiTask>
where
    F: FnOnce(TaskAdmission) -> Result<UiTaskOutput, ShellError> + Send + 'static,
{
    let worker = SupervisedTask::spawn(
        kind.thread_name(),
        move || {
            if let Ok(context) = repaint.lock()
                && let Some(context) = context.as_ref()
            {
                context.request_repaint();
            }
        },
        move |admission| task(admission).map_err(|error| error.to_string()),
    )?;
    Ok(PendingUiTask { kind, worker })
}

fn poll_task_slot(slot: &mut Option<PendingUiTask>) -> Option<(UiTaskKind, JoinedUiTask)> {
    let task = slot.as_mut()?;
    let kind = task.kind;
    let outcome = task.worker.poll()?;
    *slot = None;
    Some((kind, outcome))
}

pub struct HeptaNativeApp {
    runtime: Arc<Mutex<NativeShellRuntime>>,
    manifest: EndpointManifest,
    screen: Screen,
    chat_shell: chat_app::ChatShell,
    locale: Locale,
    connected: bool,
    status_rendered: Option<String>,
    view_revision: Option<u64>,
    ready_view: Option<RuntimeView>,
    gui_frame: u64,
    readiness_frames: ReadinessFrames,
    /// One newest-first page only. Durable history remains in OperationJournal.
    operations: Vec<PlatformReceipt>,
    history_page: usize,
    history_total: usize,
    file_input_focus: Option<FileInputTarget>,
    /// Single mutation owner lane. It includes runtime/update/readiness/shutdown
    /// mutations and never runs concurrently with the history-read lane.
    pending_runtime: Option<PendingUiTask>,
    /// Bounded read-only lane for persistent history pages.
    pending_read: Option<PendingUiTask>,
    /// Platform dialogs are isolated from the runtime owner and may remain open
    /// without blocking refresh, reconciliation, or final-use mutation.
    pending_picker: Option<PendingUiTask>,
    shutdown: Shutdown,
    repaint: Arc<Mutex<Option<egui::Context>>>,
    last_error: Option<String>,
    operation_subject_id: String,
    operation_id: String,
    operation_action: PlatformAction,
    operation_path: String,
    operation_text: String,
    notification_title: String,
    notification_body: String,
    operation_grant_path: String,
    operation_binding: Option<PreparedBinding>,
    operation_message: Option<String>,
    startup_recorder: Option<crate::startup::StartupRecorder>,
    update_handoff: Option<crate::update_handoff::UpdateHandoff>,
    pending_update_path: PathBuf,
    pending_update: Option<PendingUpdateV1>,
    updater: UpdateManager,
    activate_update_on_exit: Arc<AtomicBool>,
    update_manifest_path: String,
    update_package_path: String,
    update_message: Option<String>,
}

impl HeptaNativeApp {
    pub fn configure_chat(
        &mut self,
        config: crate::chat_runtime::ChatConfig,
    ) -> Result<(), String> {
        self.chat_shell.configure_chat(config)
    }

    pub fn set_chat_configuration_error(&mut self, error: String) {
        self.chat_shell.chat.availability = chat_model::ChatAvailability::Failed;
        self.chat_shell.chat_bridge.error = Some(error);
    }

    pub fn new(
        mut runtime: NativeShellRuntime,
        manifest: EndpointManifest,
        updater: UpdateManager,
        activate_update_on_exit: Arc<AtomicBool>,
    ) -> Result<Self, ShellError> {
        activate_update_on_exit.store(false, Ordering::Release);
        let session = runtime.connect_runtime(&manifest)?;
        SessionReferenceStore::default().save(&session, &manifest.manifest_digest)?;
        let history = runtime.operation_history_page(0, HISTORY_PAGE_SIZE)?;
        let pending_update = updater.load_pending()?;
        let mut app = Self {
            runtime: Arc::new(Mutex::new(runtime)),
            manifest,
            screen: Screen::Runtime,
            chat_shell: chat_app::ChatShell::default(),
            locale: Locale::detect(),
            connected: false,
            status_rendered: None,
            view_revision: None,
            ready_view: None,
            gui_frame: 0,
            readiness_frames: ReadinessFrames::default(),
            operations: history.receipts,
            history_page: history.page,
            history_total: history.total,
            file_input_focus: None,
            pending_runtime: None,
            pending_read: None,
            pending_picker: None,
            shutdown: Shutdown::default(),
            repaint: Arc::new(Mutex::new(None)),
            last_error: None,
            operation_subject_id: "operator.local".to_owned(),
            operation_id: format!("native.ui.{}.{}", std::process::id(), now_unix_ms()?.max(1)),
            operation_action: PlatformAction::CopyText,
            operation_path: String::new(),
            operation_text: String::new(),
            notification_title: String::new(),
            notification_body: String::new(),
            operation_grant_path: String::new(),
            operation_binding: None,
            operation_message: None,
            startup_recorder: None,
            update_handoff: None,
            pending_update_path: updater.pending_path(),
            pending_update,
            updater,
            activate_update_on_exit,
            update_manifest_path: String::new(),
            update_package_path: String::new(),
            update_message: None,
        };
        app.refresh();
        Ok(app)
    }

    pub fn set_startup_recorder(&mut self, recorder: crate::startup::StartupRecorder) {
        self.startup_recorder = Some(recorder);
    }

    pub fn set_update_handoff(&mut self, handoff: crate::update_handoff::UpdateHandoff) {
        self.update_handoff = Some(handoff);
    }

    fn apply_history(&mut self, history: OperationHistoryPage) {
        self.history_page = history.page;
        self.history_total = history.total;
        self.operations = history.receipts;
    }

    fn fail_readiness(&mut self, message: String) {
        self.shutdown.failure = Some(message.clone());
        self.shutdown.update_requested = false;
        self.shutdown.request(Instant::now());
        self.activate_update_on_exit.store(false, Ordering::Release);
        self.connected = false;
        self.ready_view = None;
        self.view_revision = None;
        self.operation_binding = None;
        self.readiness_frames.reset();
        self.last_error = Some(message);
    }

    fn confirm_rendered_update(&mut self, ui: &egui::Ui) {
        if self.runtime_busy()
            || self.status_rendered.is_none()
            || self.last_error.is_some()
            || (self.startup_recorder.is_none() && self.update_handoff.is_none())
        {
            return;
        }
        let Some(view) = self.ready_view.as_ref() else {
            return;
        };
        let witness = match self.readiness_frames.observe(self.gui_frame, view) {
            Ok(Some(witness)) => witness,
            Ok(None) => {
                ui.ctx().request_repaint();
                return;
            }
            Err(error) => {
                self.fail_readiness(error.to_string());
                return;
            }
        };
        let recorder = self.startup_recorder.take();
        let handoff = self.update_handoff.take();
        let runtime = Arc::clone(&self.runtime);
        let updater = self.updater.clone();
        self.start_task(UiTaskKind::Ready, move |admission| {
            let runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            witness.verify_current(&runtime)?;
            if let Some(recorder) = recorder {
                runtime.record_startup(recorder)?;
            }
            if let Some(handoff) = handoff {
                runtime.confirm_update_ready(&updater, &handoff)?;
            }
            Ok(UiTaskOutput::Ready {
                pending: updater.load_pending()?.map(Box::new),
            })
        });
        if self.pending_runtime.is_none() {
            self.fail_readiness(
                self.last_error
                    .clone()
                    .unwrap_or_else(|| "cannot start readiness worker".into()),
            );
        }
    }

    /// Start a mutation-owner task. A history read must finish first; this keeps
    /// pages stable without creating a second journal authority.
    fn start_task<F>(&mut self, kind: UiTaskKind, task: F)
    where
        F: FnOnce(TaskAdmission) -> Result<UiTaskOutput, ShellError> + Send + 'static,
    {
        if self.runtime_busy() {
            self.last_error = Some(
                self.locale
                    .text(
                        "Another native runtime operation is still running.",
                        "另一个原生运行时操作仍在运行。",
                    )
                    .to_owned(),
            );
            return;
        }
        match spawn_ui_task(kind, Arc::clone(&self.repaint), task) {
            Ok(pending) => {
                self.pending_runtime = Some(pending);
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(format!("start native worker: {error}")),
        }
    }

    fn start_read_task<F>(&mut self, kind: UiTaskKind, task: F)
    where
        F: FnOnce(TaskAdmission) -> Result<UiTaskOutput, ShellError> + Send + 'static,
    {
        if self.runtime_busy() {
            self.last_error = Some(
                self.locale
                    .text(
                        "The runtime owner is busy; the history page was not changed.",
                        "运行时 owner 正忙；历史页面未改变。",
                    )
                    .to_owned(),
            );
            return;
        }
        match spawn_ui_task(kind, Arc::clone(&self.repaint), task) {
            Ok(pending) => {
                self.pending_read = Some(pending);
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(format!("start history reader: {error}")),
        }
    }

    fn start_picker_task<F>(&mut self, task: F)
    where
        F: FnOnce(TaskAdmission) -> Result<UiTaskOutput, ShellError> + Send + 'static,
    {
        if self.picker_busy() {
            self.last_error = Some(
                self.locale
                    .text(
                        "Another platform file dialog is still open.",
                        "另一个平台文件对话框仍处于打开状态。",
                    )
                    .to_owned(),
            );
            return;
        }
        match spawn_ui_task(UiTaskKind::PickFile, Arc::clone(&self.repaint), task) {
            Ok(pending) => {
                self.pending_picker = Some(pending);
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(format!("start native picker: {error}")),
        }
    }

    fn poll_tasks(&mut self) {
        let completed = [
            poll_task_slot(&mut self.pending_runtime),
            poll_task_slot(&mut self.pending_read),
            poll_task_slot(&mut self.pending_picker),
        ];
        for (kind, joined) in completed.into_iter().flatten() {
            self.handle_task_outcome(kind, joined);
        }
    }

    fn handle_task_outcome(&mut self, kind: UiTaskKind, joined: JoinedUiTask) {
        let outcome = match joined {
            Ok(outcome) => outcome,
            Err(error) => {
                self.shutdown.failure = Some(error.to_owned());
                self.shutdown.update_requested = false;
                Err(error.to_owned())
            }
        };
        match outcome {
            Ok(UiTaskOutput::PrepareBinding(binding)) => {
                self.install_prepared_binding(binding);
            }
            Ok(UiTaskOutput::Shutdown) => {
                self.shutdown.check_deadline(Instant::now());
                self.shutdown.runtime_closed = true;
                self.connected = false;
            }
            Ok(UiTaskOutput::Refresh {
                status_rendered,
                view_revision,
                ready_view,
                history,
            }) => {
                self.status_rendered = Some(status_rendered);
                self.view_revision = Some(view_revision);
                self.ready_view = Some(ready_view);
                self.readiness_frames.reset();
                self.connected = true;
                self.apply_history(history);
                self.operation_binding = None;
                self.last_error = None;
            }
            Ok(UiTaskOutput::Reconcile { history }) => {
                self.apply_history(history);
                self.last_error = None;
            }
            Ok(UiTaskOutput::Execute { message, history }) => {
                self.operation_message = Some(message);
                self.apply_history(history);
                self.last_error = None;
            }
            Ok(UiTaskOutput::History { history }) => {
                self.apply_history(history);
                self.last_error = None;
            }
            Ok(UiTaskOutput::StageUpdate { message, pending }) => {
                self.update_message = Some(message);
                self.pending_update = Some(*pending);
                self.last_error = None;
            }
            Ok(UiTaskOutput::Ready { pending }) => {
                self.pending_update = pending.map(|value| *value);
                self.last_error = None;
            }
            Ok(UiTaskOutput::PickedFile { ticket, path }) => {
                let context = self.repaint.lock().ok().and_then(|context| context.clone());
                if let Some(context) = context {
                    self.finish_picker_result(&context, ticket, path);
                } else {
                    self.last_error = Some("picker callback has no live UI context".into());
                }
            }
            Err(error) => {
                if kind == UiTaskKind::Ready {
                    self.fail_readiness(error);
                    return;
                }
                if kind == UiTaskKind::Shutdown {
                    self.shutdown.failure = Some(error.clone());
                    self.shutdown.update_requested = false;
                }
                if kind == UiTaskKind::Refresh {
                    self.connected = false;
                    self.status_rendered = None;
                    self.view_revision = None;
                    self.ready_view = None;
                    self.readiness_frames.reset();
                    self.operation_binding = None;
                }
                if kind == UiTaskKind::PrepareBinding {
                    self.operation_binding = None;
                    self.operation_message = None;
                } else if kind == UiTaskKind::Execute {
                    self.operation_message = None;
                } else if kind == UiTaskKind::StageUpdate {
                    self.update_message = None;
                } else if kind == UiTaskKind::PickFile
                    && let Some(context) = self.repaint.lock().ok().and_then(|value| value.clone())
                {
                    task_supervisor::cancel_file_input(&context);
                }
                self.last_error = Some(error);
            }
        }
    }

    fn runtime_busy(&self) -> bool {
        self.pending_runtime.is_some() || self.pending_read.is_some() || self.shutdown.requested()
    }

    fn is_busy(&self) -> bool {
        self.runtime_busy()
    }

    fn picker_busy(&self) -> bool {
        self.pending_picker.is_some() || self.shutdown.requested()
    }

    fn history_read_busy(&self) -> bool {
        self.pending_read.is_some()
    }

    fn any_task_active(&self) -> bool {
        self.pending_runtime.is_some()
            || self.pending_read.is_some()
            || self.pending_picker.is_some()
    }

    fn all_tasks_idle(&self) -> bool {
        !self.any_task_active()
    }

    pub(super) fn load_history_page(&mut self, requested_page: usize) {
        let runtime = Arc::clone(&self.runtime);
        self.start_read_task(UiTaskKind::History, move |admission| {
            let runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            Ok(UiTaskOutput::History {
                history: runtime.operation_history_page(requested_page, HISTORY_PAGE_SIZE)?,
            })
        });
    }

    fn refresh(&mut self) {
        if self.runtime_busy() {
            return;
        }
        self.connected = false;
        self.status_rendered = None;
        self.view_revision = None;
        self.ready_view = None;
        self.readiness_frames.reset();
        self.operation_binding = None;
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::Refresh, move |admission| {
            let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            let (presentation, status) = runtime.refresh_runtime_view()?;
            // Pretty JSON may expand well beyond the bounded wire payload.
            // Serialize once on the worker, never during the GUI callback.
            let status_rendered = render_runtime_status(&status)?;
            let ready_view = runtime.view().cloned().ok_or_else(|| {
                ShellError::State("authenticated refresh did not retain its view".into())
            })?;
            let history = runtime.operation_history_page(0, HISTORY_PAGE_SIZE)?;
            Ok(UiTaskOutput::Refresh {
                status_rendered,
                view_revision: presentation.revision,
                ready_view,
                history,
            })
        });
    }

    fn reconcile(&mut self) {
        let requested_page = self.history_page;
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::Reconcile, move |admission| {
            let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            let _ = runtime.reconcile_pending()?;
            Ok(UiTaskOutput::Reconcile {
                history: runtime.operation_history_page(requested_page, HISTORY_PAGE_SIZE)?,
            })
        });
    }
}

impl eframe::App for HeptaNativeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        theme::ensure_initialized(ui.ctx());
        if let Ok(mut repaint) = self.repaint.lock()
            && repaint.is_none()
        {
            *repaint = Some(ui.ctx().clone());
        }
        match self.gui_frame.checked_add(1) {
            Some(frame) => self.gui_frame = frame,
            None => self.fail_readiness("GUI frame identity exhausted".into()),
        }
        self.poll_tasks();
        if self.shutdown_view(ui) {
            return;
        }
        // Input cancellation belongs to the app callback, regardless of the
        // screen selected while a worker is waiting for runtime admission.
        self.file_input_focus = self.handle_file_input_intent(ui);
        if self.any_task_active() || self.shutdown.requested() {
            ui.ctx().request_repaint_after(Duration::from_millis(250));
        }
        self.shell_view(ui);
        self.confirm_rendered_update(ui);
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        let closed = self.shutdown.runtime_closed && self.all_tasks_idle();
        self.activate_update_on_exit.store(
            closed && self.shutdown.activation_allowed(),
            Ordering::Release,
        );
        if !closed {
            eprintln!(
                "hepta-native interrupted exit: runtime close is unconfirmed; update activation denied; recover unknown operations without replay"
            );
        }
    }
}

#[cfg(test)]
#[path = "ui_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "ui/input_event_tests.rs"]
mod input_event_tests;
