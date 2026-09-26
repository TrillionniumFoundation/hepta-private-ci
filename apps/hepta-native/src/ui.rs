mod update_views;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::sync::mpsc::Receiver;
use std::sync::mpsc::TryRecvError;
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
}

impl UiTaskKind {
    fn thread_name(self) -> &'static str {
        match self {
            Self::Refresh => "hepta-native-refresh",
            Self::Reconcile => "hepta-native-reconcile",
            Self::Execute => "hepta-native-effect",
            Self::StageUpdate => "hepta-native-update-stage",
        }
    }

    fn label(self, locale: Locale) -> &'static str {
        match self {
            Self::Refresh => locale.text("Refreshing runtime", "正在刷新运行时"),
            Self::Reconcile => locale.text("Reconciling operations", "正在对账操作"),
            Self::Execute => locale.text("Executing bounded operation", "正在执行受限操作"),
            Self::StageUpdate => locale.text("Verifying and staging update", "正在验证并暂存更新"),
        }
    }
}

#[derive(Debug)]
enum UiTaskOutput {
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
    receiver: Receiver<Result<UiTaskOutput, String>>,
}

fn lock_runtime(
    runtime: &Arc<Mutex<NativeShellRuntime>>,
) -> Result<std::sync::MutexGuard<'_, NativeShellRuntime>, ShellError> {
    runtime
        .lock()
        .map_err(|_| ShellError::State("native runtime worker lock is poisoned".to_owned()))
}

fn spawn_ui_task<F>(kind: UiTaskKind, task: F) -> std::io::Result<PendingUiTask>
where
    F: FnOnce() -> Result<UiTaskOutput, ShellError> + Send + 'static,
{
    let (sender, receiver) = mpsc::channel();
    let handle = std::thread::Builder::new()
        .name(kind.thread_name().to_owned())
        .spawn(move || {
            let outcome = task().map_err(|error| error.to_string());
            let _ = sender.send(outcome);
        })?;
    drop(handle);
    Ok(PendingUiTask { kind, receiver })
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
        if self.status.is_none() || self.view_revision.is_none() || self.last_error.is_some() {
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
        F: FnOnce() -> Result<UiTaskOutput, ShellError> + Send + 'static,
    {
        if self.pending_task.is_some() {
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
        match spawn_ui_task(kind, task) {
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
        let outcome = match self.pending_task.as_ref() {
            Some(task) => match task.receiver.try_recv() {
                Ok(outcome) => Some((task.kind, outcome)),
                Err(TryRecvError::Empty) => None,
                Err(TryRecvError::Disconnected) => Some((
                    task.kind,
                    Err("native worker exited without an outcome".to_owned()),
                )),
            },
            None => None,
        };
        let Some((kind, outcome)) = outcome else {
            return;
        };
        self.pending_task = None;
        match outcome {
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
        self.pending_task.is_some()
    }

    fn refresh(&mut self) {
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::Refresh, move || {
            let mut runtime = lock_runtime(&runtime)?;
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
        self.start_task(UiTaskKind::Reconcile, move || {
            let mut runtime = lock_runtime(&runtime)?;
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

    fn operations_view(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Native operations", "原生操作"));
        ui.label(self.locale.text(
            "The shell never signs its own authority. Prepare the exact binding, have the independent authority owner issue a SignedFinalUseGrant, then select that grant file for one final-use operation.",
            "壳层绝不会自行签发权限。先生成精确 binding，由独立 authority owner 签发 SignedFinalUseGrant，再选择该 grant 文件执行一次 final-use 操作。",
        ));
        ui.separator();

        ui.label(self.locale.text("Authority subject", "权限主体"));
        ui.text_edit_singleline(&mut self.operation_subject_id);
        ui.label(self.locale.text("Operation ID", "操作 ID"));
        ui.text_edit_singleline(&mut self.operation_id);
        egui::ComboBox::from_id_salt("native-operation-action")
            .selected_text(self.operation_action.to_string())
            .show_ui(ui, |ui| {
                for action in [
                    PlatformAction::OpenPath,
                    PlatformAction::RevealPath,
                    PlatformAction::CopyText,
                    PlatformAction::Notify,
                ] {
                    ui.selectable_value(&mut self.operation_action, action, action.to_string());
                }
            });

        match self.operation_action {
            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                ui.label(self.locale.text("Absolute path", "绝对路径"));
                ui.text_edit_singleline(&mut self.operation_path);
            }
            PlatformAction::CopyText => {
                ui.label(self.locale.text("Clipboard text", "剪贴板文本"));
                ui.text_edit_multiline(&mut self.operation_text);
            }
            PlatformAction::Notify => {
                ui.label(self.locale.text("Notification title", "通知标题"));
                ui.text_edit_singleline(&mut self.notification_title);
                ui.label(self.locale.text("Notification body", "通知正文"));
                ui.text_edit_multiline(&mut self.notification_body);
            }
        }

        ui.label(self.locale.text("Signed grant path", "签名 grant 路径"));
        ui.text_edit_singleline(&mut self.operation_grant_path);
        let busy = self.is_busy();
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(
                        self.locale
                            .text("Prepare exact binding", "生成精确 binding"),
                    ),
                )
                .clicked()
            {
                self.prepare_operation_binding();
            }
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(
                        self.locale
                            .text("Execute with signed grant", "使用签名 grant 执行"),
                    ),
                )
                .clicked()
            {
                self.execute_operation();
            }
        });
        if let Some(binding) = &self.operation_binding {
            ui.label(self.locale.text(
                "Binding for the independent issuer:",
                "交给独立签发方的 binding：",
            ));
            let mut binding = binding.clone();
            ui.add(
                egui::TextEdit::multiline(&mut binding)
                    .font(egui::TextStyle::Monospace)
                    .desired_rows(10)
                    .interactive(false),
            );
        }
        if let Some(message) = &self.operation_message {
            ui.label(message);
        }

        ui.separator();
        ui.label(self.locale.text(
            "Indeterminate operations are never automatically replayed. Reconcile asks the platform adapter for a trustworthy terminal observation.",
            "不确定操作绝不会自动重放。对账只接受平台适配器提供的可信终态观察。",
        ));
        if self.operations.is_empty() {
            ui.label(self.locale.text("No operation receipts.", "暂无操作回执。"));
            return;
        }
        egui::ScrollArea::vertical().show(ui, |ui| {
            for receipt in self.operations.iter().rev() {
                ui.group(|ui| {
                    ui.label(format!("{} · {}", receipt.key.operation_id, receipt.action));
                    ui.label(format!(
                        "session={} generation={}",
                        receipt.key.session_id, receipt.key.session_generation
                    ));
                    ui.label(format!(
                        "terminal={} status={:?}",
                        receipt.terminal_observed, receipt.terminal_status
                    ));
                    ui.label(format!("payload={}", receipt.payload_digest));
                });
            }
        });
    }

    fn operation_payload(&self) -> Result<PlatformPayload, ShellError> {
        let payload = match self.operation_action {
            PlatformAction::OpenPath => PlatformPayload::OpenPath {
                path: PathBuf::from(self.operation_path.trim()),
            },
            PlatformAction::RevealPath => PlatformPayload::RevealPath {
                path: PathBuf::from(self.operation_path.trim()),
            },
            PlatformAction::CopyText => PlatformPayload::CopyText {
                text: self.operation_text.clone(),
            },
            PlatformAction::Notify => PlatformPayload::Notify {
                title: self.notification_title.clone(),
                body: self.notification_body.clone(),
            },
        };
        payload.validate()?;
        Ok(payload)
    }

    fn prepare_operation_binding(&mut self) {
        let outcome = (|| -> Result<String, ShellError> {
            let payload = self.operation_payload()?;
            let runtime = self.runtime.try_lock().map_err(|_| {
                ShellError::State("native runtime is busy; retry after the current task".to_owned())
            })?;
            let binding = runtime.prepare_platform_binding(
                self.operation_subject_id.trim(),
                self.operation_id.trim(),
                &payload,
            )?;
            serde_json::to_string_pretty(&binding).map_err(ShellError::from)
        })();
        match outcome {
            Ok(binding) => {
                self.operation_binding = Some(binding);
                self.operation_message = Some(
                    self.locale
                        .text(
                            "Binding prepared. The independent authority owner must choose grant identity, nonce, epoch and lifetime and sign the complete grant.",
                            "Binding 已生成。独立 authority owner 必须自行选择 grant identity、nonce、epoch 与有效期，并签署完整 grant。",
                        )
                        .to_owned(),
                );
                self.last_error = None;
            }
            Err(error) => {
                self.operation_binding = None;
                self.operation_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }

    fn execute_operation(&mut self) {
        let outcome = (|| -> Result<PlatformRequest, ShellError> {
            let grant_path = PathBuf::from(self.operation_grant_path.trim());
            if !grant_path.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "signed final-use grant path must be absolute".to_owned(),
                ));
            }
            let metadata = std::fs::metadata(&grant_path)?;
            if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 16 * 1024 {
                return Err(ShellError::InvalidInput(
                    "signed final-use grant must be a non-empty regular file <= 16 KiB".to_owned(),
                ));
            }
            let grant: SignedFinalUseGrant = serde_json::from_slice(&std::fs::read(&grant_path)?)?;
            let displayed_revision = self.view_revision.ok_or_else(|| {
                ShellError::State("native runtime view is unavailable".to_owned())
            })?;
            Ok(PlatformRequest {
                subject_id: self.operation_subject_id.trim().to_owned(),
                operation_id: self.operation_id.trim().to_owned(),
                displayed_revision,
                payload: self.operation_payload()?,
                grant,
            })
        })();
        match outcome {
            Ok(request) => {
                let runtime = Arc::clone(&self.runtime);
                self.operation_message = None;
                self.start_task(UiTaskKind::Execute, move || {
                    let mut runtime = lock_runtime(&runtime)?;
                    let receipt = runtime.request_platform_capability(request)?;
                    let message = format!(
                        "{}: terminal={} status={:?}",
                        receipt.key.operation_id,
                        receipt.terminal_observed,
                        receipt.terminal_status
                    );
                    Ok(UiTaskOutput::Execute {
                        message,
                        operations: runtime.operation_history(),
                    })
                });
            }
            Err(error) => {
                self.operation_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }
}

impl eframe::App for HeptaNativeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.poll_task();
        if self.is_busy() {
            ui.ctx().request_repaint_after(Duration::from_millis(50));
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
        if let Ok(mut runtime) = self.runtime.try_lock() {
            let _ = runtime.close();
            self.connected = false;
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;
    use std::time::Duration;

    use super::Locale;
    use super::UiTaskKind;
    use super::UiTaskOutput;
    use super::spawn_ui_task;
    use crate::error::ShellError;

    #[test]
    fn worker_slot_returns_before_the_bounded_task_completes() {
        let (release, wait) = mpsc::channel();
        let pending = spawn_ui_task(UiTaskKind::Refresh, move || {
            wait.recv()
                .map_err(|error| ShellError::State(error.to_string()))?;
            Err::<UiTaskOutput, ShellError>(ShellError::State("worker-finished".to_owned()))
        })
        .unwrap();
        assert!(matches!(
            pending.receiver.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
        release.send(()).unwrap();
        let outcome = pending
            .receiver
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
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
}
