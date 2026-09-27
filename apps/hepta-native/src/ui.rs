mod operations_view;
mod shutdown;
mod task_supervisor;
mod update_views;

use self::shutdown::Shutdown;
use self::task_supervisor::SupervisedTask;
use self::task_supervisor::TaskAdmission;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::SignedFinalUseGrant;
use eframe::egui;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::PlatformAction;
use crate::model::PlatformPayload;
use crate::model::PlatformReceipt;
use crate::model::PlatformRequest;
use crate::runtime::NativeShellRuntime;
use crate::security::now_unix_ms;
use crate::session_store::SessionReferenceStore;
use crate::updater::PendingUpdateStatus;
use crate::updater::PendingUpdateV1;
use crate::updater::SignedUpdateManifestV1;
use crate::updater::UpdateManager;

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
    StageUpdate,
    Shutdown,
}

impl UiTaskKind {
    fn thread_name(self) -> &'static str {
        match self {
            Self::Refresh => "hepta-native-refresh",
            Self::Reconcile => "hepta-native-reconcile",
            Self::Execute => "hepta-native-effect",
            Self::StageUpdate => "hepta-native-update-stage",
            Self::Shutdown => "hepta-native-shutdown",
        }
    }

    fn label(self, locale: Locale) -> &'static str {
        match self {
            Self::Refresh => locale.text("Refreshing runtime", "正在刷新运行时"),
            Self::Reconcile => locale.text("Reconciling operations", "正在对账操作"),
            Self::Execute => locale.text("Executing bounded operation", "正在执行受限操作"),
            Self::StageUpdate => locale.text("Verifying and staging update", "正在验证并暂存更新"),
            Self::Shutdown => locale.text("Closing runtime", "正在关闭运行时"),
        }
    }
}

#[derive(Debug)]
enum UiTaskOutput {
    Shutdown,
    Refresh {
        status: serde_json::Value,
        view_revision: u64,
        operations: Vec<PlatformReceipt>,
    },
    Reconcile {
        operations: Vec<PlatformReceipt>,
    },
    Execute {
        message: String,
        operations: Vec<PlatformReceipt>,
    },
    StageUpdate {
        message: String,
        pending: Box<PendingUpdateV1>,
    },
}

struct PendingUiTask {
    kind: UiTaskKind,
    worker: SupervisedTask<Result<UiTaskOutput, String>>,
}

fn lock_runtime(
    runtime: &Arc<Mutex<NativeShellRuntime>>,
) -> Result<std::sync::MutexGuard<'_, NativeShellRuntime>, ShellError> {
    runtime
        .lock()
        .map_err(|_| ShellError::State("native runtime worker lock is poisoned".to_owned()))
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

pub struct HeptaNativeApp {
    runtime: Arc<Mutex<NativeShellRuntime>>,
    manifest: EndpointManifest,
    screen: Screen,
    locale: Locale,
    connected: bool,
    status: Option<serde_json::Value>,
    view_revision: Option<u64>,
    operations: Vec<PlatformReceipt>,
    pending_task: Option<PendingUiTask>,
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
    operation_binding: Option<String>,
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
    pub fn new(
        mut runtime: NativeShellRuntime,
        manifest: EndpointManifest,
        updater: UpdateManager,
        activate_update_on_exit: Arc<AtomicBool>,
    ) -> Result<Self, ShellError> {
        activate_update_on_exit.store(false, Ordering::Release);
        let session = runtime.connect_runtime(&manifest)?;
        SessionReferenceStore::default().save(&session, &manifest.manifest_digest)?;
        let operations = runtime.operation_history();
        let pending_update = updater.load_pending()?;
        let mut app = Self {
            runtime: Arc::new(Mutex::new(runtime)),
            manifest,
            screen: Screen::Runtime,
            locale: Locale::detect(),
            connected: true,
            status: None,
            view_revision: None,
            operations,
            pending_task: None,
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

    fn confirm_rendered_update(&mut self, ui: &egui::Ui) {
        if self.is_busy() || self.status.is_none() || self.view_revision.is_none() || self.last_error.is_some() {
            return;
        }
        if let Some(recorder) = self.startup_recorder.take()
            && let Err(error) =
                lock_runtime(&self.runtime).and_then(|runtime| runtime.record_startup(recorder))
        {
            eprintln!("hepta-native startup failed: {error}");
            self.last_error = Some(error.to_string());
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
            return;
        }
        if let Some(handoff) = self.update_handoff.take() {
            let outcome = lock_runtime(&self.runtime)
                .and_then(|runtime| runtime.confirm_update_ready(&self.updater, &handoff));
            match outcome {
                Ok(()) => self.pending_update = self.updater.load_pending().ok().flatten(),
                Err(error) => {
                    self.last_error = Some(error.to_string());
                    ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
        }
    }

    fn start_task<F>(&mut self, kind: UiTaskKind, task: F)
    where
        F: FnOnce(TaskAdmission) -> Result<UiTaskOutput, ShellError> + Send + 'static,
    {
        if self.is_busy() {
            self.last_error = Some(
                self.locale
                    .text(
                        "Another native operation is still running.",
                        "另一个原生操作仍在运行。",
                    )
                    .to_owned(),
            );
            return;
        }
        match spawn_ui_task(kind, Arc::clone(&self.repaint), task) {
            Ok(pending) => {
                self.pending_task = Some(pending);
                self.last_error = None;
            }
            Err(error) => {
                self.last_error = Some(format!("start native worker: {error}"));
            }
        }
    }

    fn poll_task(&mut self) {
        let outcome = self.pending_task.as_mut().and_then(|task| {
            task.worker.poll().map(|outcome| (task.kind, outcome))
        });
        let Some((kind, joined)) = outcome else {
            return;
        };
        self.pending_task = None;
        let outcome = match joined {
            Ok(outcome) => outcome,
            Err(error) => {
                self.shutdown.failure = Some(error.to_owned());
                self.shutdown.update_requested = false;
                Err(error.to_owned())
            }
        };
        match outcome {
            Ok(UiTaskOutput::Shutdown) => {
                self.shutdown.check_deadline(std::time::Instant::now());
                self.shutdown.runtime_closed = true;
                self.connected = false;
            }
            Ok(UiTaskOutput::Refresh {
                status,
                view_revision,
                operations,
            }) => {
                self.status = Some(status);
                self.view_revision = Some(view_revision);
                self.operations = operations;
                self.operation_binding = None;
                self.last_error = None;
            }
            Ok(UiTaskOutput::Reconcile { operations }) => {
                self.operations = operations;
                self.last_error = None;
            }
            Ok(UiTaskOutput::Execute {
                message,
                operations,
            }) => {
                self.operation_message = Some(message);
                self.operations = operations;
                self.last_error = None;
            }
            Ok(UiTaskOutput::StageUpdate { message, pending }) => {
                self.update_message = Some(message);
                self.pending_update = Some(*pending);
                self.last_error = None;
            }
            Err(error) => {
                if kind == UiTaskKind::Shutdown {
                    self.shutdown.failure = Some(error.clone());
                    self.shutdown.update_requested = false;
                }
                if kind == UiTaskKind::Refresh {
                    self.view_revision = None;
                    self.operation_binding = None;
                }
                if kind == UiTaskKind::Execute {
                    self.operation_message = None;
                } else if kind == UiTaskKind::StageUpdate {
                    self.update_message = None;
                }
                self.last_error = Some(error);
            }
        }
    }

    fn is_busy(&self) -> bool {
        self.pending_task.is_some() || self.shutdown.requested()
    }

    fn refresh(&mut self) {
        if self.is_busy() {
            return;
        }
        self.view_revision = None;
        self.operation_binding = None;
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::Refresh, move |admission| {
            let mut runtime = lock_runtime(&runtime)?;
            admission.begin().map_err(|message| ShellError::State(message.to_owned()))?;
            let (presentation, status) = runtime.refresh_runtime_view()?;
            let operations = runtime.operation_history();
            Ok(UiTaskOutput::Refresh {
                status,
                view_revision: presentation.revision,
                operations,
            })
        });
    }

    fn reconcile(&mut self) {
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::Reconcile, move |admission| {
            let mut runtime = lock_runtime(&runtime)?;
            admission.begin().map_err(|message| ShellError::State(message.to_owned()))?;
            let _ = runtime.reconcile_pending()?;
            Ok(UiTaskOutput::Reconcile {
                operations: runtime.operation_history(),
            })
        });
    }

    fn top_bar(&mut self, ui: &mut egui::Ui) {
        let busy = self.is_busy();
        ui.horizontal(|ui| {
            ui.heading("Hepta Native");
            ui.separator();
            if self.connected {
                ui.label(self.locale.text("Connected", "已连接"));
            } else {
                ui.label(self.locale.text("Disconnected", "未连接"));
            }
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(self.locale.text("Refresh", "刷新")),
                )
                .clicked()
            {
                self.refresh();
            }
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(self.locale.text("Reconcile", "对账")),
                )
                .clicked()
            {
                self.reconcile();
            }
            if let Some(task) = &self.pending_task {
                ui.spinner();
                ui.label(task.kind.label(self.locale));
            }
        });
        if let Some(error) = &self.last_error {
            ui.separator();
            ui.label(egui::RichText::new(error).strong());
        }
    }

    fn navigation(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Navigation", "导航"));
        for (screen, en, zh) in [
            (Screen::Runtime, "Runtime", "运行时"),
            (Screen::Operations, "Operations", "操作"),
            (Screen::Updates, "Updates", "更新"),
            (Screen::Accessibility, "Accessibility", "无障碍"),
        ] {
            if ui
                .selectable_label(self.screen == screen, self.locale.text(en, zh))
                .clicked()
            {
                self.screen = screen;
            }
        }
        ui.separator();
        ui.label(format!(
            "{}: {}",
            self.locale.text("Endpoint", "端点"),
            self.manifest.address
        ));
        ui.label(format!(
            "{}: {}/{}",
            self.locale.text("Platform", "平台"),
            std::env::consts::OS,
            std::env::consts::ARCH
        ));
    }

    fn runtime_view(&self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Runtime status", "运行时状态"));
        match &self.status {
            Some(value) => {
                let mut pretty = serde_json::to_string_pretty(value)
                    .unwrap_or_else(|error| format!("status serialization failed: {error}"));
                ui.add(
                    egui::TextEdit::multiline(&mut pretty)
                        .font(egui::TextStyle::Monospace)
                        .desired_rows(24)
                        .interactive(false),
                );
            }
            None => {
                ui.label(self.locale.text("No runtime snapshot.", "暂无运行时快照。"));
            }
        }
    }


}

impl eframe::App for HeptaNativeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if let Ok(mut repaint) = self.repaint.lock()
            && repaint.is_none()
        {
            *repaint = Some(ui.ctx().clone());
        }
        self.poll_task();
        if self.shutdown_view(ui) {
            return;
        }
        if self.is_busy() {
            ui.ctx().request_repaint_after(Duration::from_millis(250));
        }
        egui::Panel::top("hepta-native-top").show(ui, |ui| {
            self.top_bar(ui);
        });
        egui::Panel::left("hepta-native-navigation")
            .resizable(false)
            .default_size(210.0)
            .show(ui, |ui| self.navigation(ui));
        egui::CentralPanel::default().show(ui, |ui| match self.screen {
            Screen::Runtime => self.runtime_view(ui),
            Screen::Operations => self.operations_view(ui),
            Screen::Updates => self.updates_view(ui),
            Screen::Accessibility => self.accessibility_view(ui),
        });
        self.confirm_rendered_update(ui);
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        let closed = self.shutdown.runtime_closed && self.pending_task.is_none();
        self.activate_update_on_exit.store(
            closed && self.shutdown.activation_allowed(),
            Ordering::Release,
        );
        if !closed {
            eprintln!("hepta-native interrupted exit: runtime close is unconfirmed; update activation denied; recover unknown operations without replay");
        }
    }
}

#[cfg(test)]
#[path = "ui_tests.rs"]
mod tests;
