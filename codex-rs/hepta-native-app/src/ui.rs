use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_contracts::SignedFinalUseGrant;
use eframe::egui;

use crate::runtime::EndpointManifest;
use crate::runtime::NativePresentationState;
use crate::runtime::NativeShellRuntime;
use crate::runtime::OperationReceipt;
use crate::runtime::PlatformAction;
use crate::runtime::PlatformActionKind;
use crate::runtime::PlatformRequest;
use crate::update::SignedUpdater;
use crate::update::UpdateDisposition;

enum WorkerCommand {
    Connect(EndpointManifest),
    Refresh,
    Reconcile,
    Platform(PlatformRequest),
    Update(PathBuf),
}

enum WorkerEvent {
    Status(String),
    View(NativePresentationState),
    Operations(Vec<OperationReceipt>),
    Error(String),
    UpdateScheduled(String),
}

struct Worker {
    tx: mpsc::Sender<WorkerCommand>,
    rx: mpsc::Receiver<WorkerEvent>,
}

impl Worker {
    fn spawn(mut runtime: NativeShellRuntime, updater: Option<SignedUpdater>) -> Self {
        let (command_tx, command_rx) = mpsc::channel();
        let (event_tx, event_rx) = mpsc::channel();
        let _worker = std::thread::Builder::new()
            .name("hepta-native-worker".to_string())
            .spawn(move || {
                while let Ok(command) = command_rx.recv() {
                    match command {
                        WorkerCommand::Connect(manifest) => match runtime.connect(&manifest) {
                            Ok(session) => {
                                let _sent = event_tx.send(WorkerEvent::Status(format!(
                                    "connected {} generation {}",
                                    session.endpoint_id, session.fence.generation
                                )));
                                match runtime.refresh_view() {
                                    Ok(view) => {
                                        let _sent = event_tx.send(WorkerEvent::View(view));
                                    }
                                    Err(error) => {
                                        let _sent =
                                            event_tx.send(WorkerEvent::Error(error.to_string()));
                                    }
                                }
                                let _sent =
                                    event_tx.send(WorkerEvent::Operations(runtime.operations()));
                            }
                            Err(error) => {
                                let _sent = event_tx.send(WorkerEvent::Error(error.to_string()));
                            }
                        },
                        WorkerCommand::Refresh => match runtime.refresh_view() {
                            Ok(view) => {
                                let _sent = event_tx.send(WorkerEvent::View(view));
                            }
                            Err(error) => {
                                let _sent = event_tx.send(WorkerEvent::Error(error.to_string()));
                            }
                        },
                        WorkerCommand::Reconcile => match runtime.reconcile_recovered() {
                            Ok(receipts) => {
                                let _sent = event_tx.send(WorkerEvent::Operations(receipts));
                                let _sent = event_tx.send(WorkerEvent::Status(
                                    "reconciliation completed without replay".to_string(),
                                ));
                            }
                            Err(error) => {
                                let _sent = event_tx.send(WorkerEvent::Error(error.to_string()));
                            }
                        },
                        WorkerCommand::Platform(request) => {
                            match runtime.request_platform_capability(request) {
                                Ok(receipt) => {
                                    let operation_id = &receipt.key.operation_id;
                                    let status = receipt.status;
                                    let _sent = event_tx.send(WorkerEvent::Status(format!(
                                        "{operation_id} -> {status:?}"
                                    )));
                                }
                                Err(error) => {
                                    let _sent =
                                        event_tx.send(WorkerEvent::Error(error.to_string()));
                                }
                            }
                            let _sent =
                                event_tx.send(WorkerEvent::Operations(runtime.operations()));
                        }
                        WorkerCommand::Update(path) => match &updater {
                            Some(updater) => match updater.stage_and_schedule(&path) {
                                Ok(UpdateDisposition::RestartScheduled { version }) => {
                                    let _sent =
                                        event_tx.send(WorkerEvent::UpdateScheduled(version));
                                }
                                Err(error) => {
                                    let _sent =
                                        event_tx.send(WorkerEvent::Error(error.to_string()));
                                }
                            },
                            None => {
                                let _sent = event_tx.send(WorkerEvent::Error(
                                    "signed updater is not configured".to_string(),
                                ));
                            }
                        },
                    }
                }
                let _closed = runtime.close();
            });
        Self {
            tx: command_tx,
            rx: event_rx,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Page {
    Runtime,
    Operations,
    Updates,
    Settings,
}

pub struct HeptaNativeApp {
    worker: Worker,
    manifest: EndpointManifest,
    locale: String,
    page: Page,
    status: String,
    error: Option<String>,
    view: Option<NativePresentationState>,
    operations: Vec<OperationReceipt>,
    operation_id: String,
    action: PlatformActionKind,
    resource: String,
    payload: String,
    grant_json: String,
    update_manifest_path: String,
    update_configured: bool,
    journal_warning: Option<String>,
    smoke_close: bool,
    close_after_update: bool,
}

impl HeptaNativeApp {
    pub fn new(
        runtime: NativeShellRuntime,
        manifest: EndpointManifest,
        updater: Option<SignedUpdater>,
        locale: String,
        journal_warning: Option<String>,
        smoke_close: bool,
    ) -> Self {
        let update_configured = updater.is_some();
        let worker = Worker::spawn(runtime, updater);
        let app = Self {
            worker,
            manifest: manifest.clone(),
            locale,
            page: Page::Runtime,
            status: "connecting".to_string(),
            error: None,
            view: None,
            operations: Vec::new(),
            operation_id: "operation.1".to_string(),
            action: PlatformActionKind::CopyText,
            resource: String::new(),
            payload: String::new(),
            grant_json: String::new(),
            update_manifest_path: String::new(),
            update_configured,
            journal_warning,
            smoke_close,
            close_after_update: false,
        };
        let _sent = app.worker.tx.send(WorkerCommand::Connect(manifest));
        app
    }

    fn zh(&self) -> bool {
        self.locale.to_ascii_lowercase().starts_with("zh")
    }

    fn t<'a>(&self, en: &'a str, zh: &'a str) -> &'a str {
        if self.zh() { zh } else { en }
    }

    fn drain_events(&mut self) {
        while let Ok(event) = self.worker.rx.try_recv() {
            match event {
                WorkerEvent::Status(status) => {
                    self.status = status;
                    self.error = None;
                }
                WorkerEvent::View(view) => {
                    self.view = Some(view);
                    self.error = None;
                }
                WorkerEvent::Operations(operations) => self.operations = operations,
                WorkerEvent::Error(error) => self.error = Some(error),
                WorkerEvent::UpdateScheduled(version) => {
                    self.status = format!("update {version} scheduled; closing for restart");
                    self.close_after_update = true;
                }
            }
        }
    }

    fn shortcuts(&mut self, ctx: &egui::Context) {
        ctx.input(|input| {
            if input.modifiers.command && input.key_pressed(egui::Key::R) {
                let _sent = self.worker.tx.send(WorkerCommand::Refresh);
            }
            if input.modifiers.alt && input.key_pressed(egui::Key::Num1) {
                self.page = Page::Runtime;
            }
            if input.modifiers.alt && input.key_pressed(egui::Key::Num2) {
                self.page = Page::Operations;
            }
            if input.modifiers.alt && input.key_pressed(egui::Key::Num3) {
                self.page = Page::Updates;
            }
            if input.modifiers.alt && input.key_pressed(egui::Key::Num4) {
                self.page = Page::Settings;
            }
            if input.key_pressed(egui::Key::Escape) {
                self.error = None;
            }
        });
    }

    fn nav(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading("Hepta");
            ui.separator();
            if ui.selectable_label(self.page == Page::Runtime, self.t("Runtime [Alt+1]", "运行时 [Alt+1]")).clicked() {
                self.page = Page::Runtime;
            }
            if ui.selectable_label(self.page == Page::Operations, self.t("Operations [Alt+2]", "操作 [Alt+2]")).clicked() {
                self.page = Page::Operations;
            }
            if ui.selectable_label(self.page == Page::Updates, self.t("Updates [Alt+3]", "更新 [Alt+3]")).clicked() {
                self.page = Page::Updates;
            }
            if ui.selectable_label(self.page == Page::Settings, self.t("Settings [Alt+4]", "设置 [Alt+4]")).clicked() {
                self.page = Page::Settings;
            }
            ui.separator();
            if ui.button(self.t("Refresh [Cmd/Ctrl+R]", "刷新 [Cmd/Ctrl+R]")).clicked() {
                let _sent = self.worker.tx.send(WorkerCommand::Refresh);
            }
        });
        ui.separator();
    }

    fn runtime(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.t("Runtime status", "运行时状态"));
        ui.label(&self.status);
        if let Some(error) = &self.error {
            ui.colored_label(ui.visuals().error_fg_color, error);
        }
        if let Some(view) = &self.view {
            egui::Grid::new("runtime-grid").striped(true).show(ui, |ui| {
                ui.label(self.t("Session", "会话"));
                ui.monospace(&view.fence.session_id);
                ui.end_row();
                ui.label(self.t("Generation", "代次"));
                ui.monospace(view.generation.to_string());
                ui.end_row();
                ui.label(self.t("Revision", "修订"));
                ui.monospace(view.revision.to_string());
                ui.end_row();
                ui.label(self.t("Digest", "摘要"));
                ui.monospace(view.digest.as_str());
                ui.end_row();
            });
            ui.separator();
            ui.label(self.t("Negotiated capabilities", "协商能力"));
            for module in &view.modules {
                ui.monospace(module);
            }
            ui.separator();
            ui.label(self.t("Owner observation", "所有者观测"));
            egui::ScrollArea::vertical().max_height(260.0).show(ui, |ui| {
                ui.monospace(&view.summary);
            });
        }
    }

    fn operations(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.t("Platform effects", "平台操作"));
        ui.label(self.t(
            "Effects require an externally signed FinalUse grant. Pending/indeterminate effects reconcile and never auto-replay.",
            "平台操作必须使用外部签发的 FinalUse grant。Pending/Indeterminate 只做对账，绝不自动重放。",
        ));
        if let Some(warning) = &self.journal_warning {
            ui.colored_label(
                ui.visuals().warn_fg_color,
                format!("secure journal unavailable; effects fail closed: {warning}"),
            );
        }

        let operation_label = ui.label(self.t("Operation ID", "操作 ID"));
        ui.text_edit_singleline(&mut self.operation_id)
            .labelled_by(operation_label.id);
        egui::ComboBox::from_id_salt("platform-action")
            .selected_text(self.action.to_string())
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.action, PlatformActionKind::CopyText, "copy_text");
                ui.selectable_value(&mut self.action, PlatformActionKind::OpenPath, "open_path");
                ui.selectable_value(&mut self.action, PlatformActionKind::RevealPath, "reveal_path");
                ui.selectable_value(&mut self.action, PlatformActionKind::Notify, "notify");
            });

        match self.action {
            PlatformActionKind::OpenPath | PlatformActionKind::RevealPath => {
                let label = ui.label(self.t("Absolute path", "绝对路径"));
                ui.text_edit_singleline(&mut self.resource).labelled_by(label.id);
            }
            PlatformActionKind::CopyText => {
                let label = ui.label(self.t("Clipboard text", "剪贴板文本"));
                ui.add(egui::TextEdit::multiline(&mut self.payload).desired_rows(4))
                    .labelled_by(label.id);
            }
            PlatformActionKind::Notify => {
                let title = ui.label(self.t("Notification title", "通知标题"));
                ui.text_edit_singleline(&mut self.resource).labelled_by(title.id);
                let body = ui.label(self.t("Notification body", "通知正文"));
                ui.add(egui::TextEdit::multiline(&mut self.payload).desired_rows(3))
                    .labelled_by(body.id);
            }
        }

        let grant_label = ui.label(self.t("Signed FinalUse grant JSON", "已签名 FinalUse grant JSON"));
        ui.add(
            egui::TextEdit::multiline(&mut self.grant_json)
                .desired_rows(8)
                .code_editor()
                .hint_text(self.t("Paste SignedFinalUseGrant", "粘贴 SignedFinalUseGrant")),
        )
        .labelled_by(grant_label.id);

        let enabled = self.view.is_some()
            && !self.operation_id.trim().is_empty()
            && !self.grant_json.trim().is_empty();
        if ui.add_enabled(enabled, egui::Button::new(self.t("Execute", "执行"))).clicked() {
            match self.platform_request() {
                Ok(request) => {
                    self.error = None;
                    let _sent = self.worker.tx.send(WorkerCommand::Platform(request));
                }
                Err(error) => self.error = Some(error),
            }
        }
        if ui.button(self.t("Reconcile pending effects", "对账 Pending 操作")).clicked() {
            let _sent = self.worker.tx.send(WorkerCommand::Reconcile);
        }

        ui.separator();
        ui.heading(self.t("Operation journal", "操作日志"));
        egui::ScrollArea::vertical().max_height(260.0).show(ui, |ui| {
            for receipt in &self.operations {
                ui.group(|ui| {
                    ui.horizontal_wrapped(|ui| {
                        ui.monospace(&receipt.key.operation_id);
                        ui.label(receipt.action.to_string());
                        ui.strong(format!("{:?}", receipt.status));
                    });
                    ui.small(format!(
                        "session={} generation={} terminal={}",
                        receipt.key.session_id,
                        receipt.key.session_generation,
                        receipt.terminal_observed
                    ));
                    if let Some(detail) = &receipt.last_error {
                        ui.small(detail);
                    }
                });
            }
        });
    }

    fn platform_request(&self) -> Result<PlatformRequest, String> {
        let view = self
            .view
            .as_ref()
            .ok_or_else(|| "runtime view is not ready".to_string())?;
        let action = match self.action {
            PlatformActionKind::OpenPath => PlatformAction::OpenPath {
                path: PathBuf::from(self.resource.trim()),
            },
            PlatformActionKind::RevealPath => PlatformAction::RevealPath {
                path: PathBuf::from(self.resource.trim()),
            },
            PlatformActionKind::CopyText => PlatformAction::CopyText {
                text: self.payload.clone(),
            },
            PlatformActionKind::Notify => PlatformAction::Notify {
                title: self.resource.clone(),
                body: self.payload.clone(),
            },
        };
        let grant = serde_json::from_str::<SignedFinalUseGrant>(&self.grant_json)
            .map_err(|error| format!("invalid SignedFinalUseGrant JSON: {error}"))?;
        Ok(PlatformRequest {
            session: view.fence.clone(),
            operation_id: self.operation_id.trim().to_string(),
            displayed_revision: view.revision,
            action,
            grant,
        })
    }

    fn updates(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.t("Signed shell updates", "签名 Shell 更新"));
        if cfg!(windows) {
            ui.colored_label(
                ui.visuals().warn_fg_color,
                self.t(
                    "Windows apply is fail-closed pending a hardened kernel authority/update state store.",
                    "Windows 更新应用在 kernel authority/update 安全状态存储完成前保持 fail-closed。",
                ),
            );
        }
        if !self.update_configured {
            ui.colored_label(
                ui.visuals().warn_fg_color,
                self.t("No pinned update key configured.", "未配置固定更新公钥。"),
            );
        }
        let label = ui.label(self.t("Signed manifest path", "签名 Manifest 路径"));
        ui.text_edit_singleline(&mut self.update_manifest_path).labelled_by(label.id);
        let enabled = self.update_configured && !self.update_manifest_path.trim().is_empty();
        if ui.add_enabled(enabled, egui::Button::new(self.t("Verify and stage", "验证并暂存"))).clicked() {
            let path = PathBuf::from(self.update_manifest_path.trim());
            let _sent = self.worker.tx.send(WorkerCommand::Update(path));
        }
        ui.separator();
        ui.label(self.t(
            "Portable-binary updates retain the predecessor. macOS notarized app bundles and Windows Authenticode/MSIX remain release-time external gates.",
            "portable-binary 更新保留前序版本。macOS notarized app bundle 与 Windows Authenticode/MSIX 仍属于发布阶段外部证据门。",
        ));
    }

    fn settings(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.t("Native platform matrix", "Native 平台矩阵"));
        egui::Grid::new("native-platform-matrix").striped(true).show(ui, |ui| {
            ui.strong(self.t("Platform", "平台"));
            ui.strong(self.t("Status", "状态"));
            ui.strong(self.t("Boundary", "边界"));
            ui.end_row();
            ui.label("Linux");
            ui.label("Tier 1");
            ui.label("FinalUse + clipboard/open/notify + signed portable updater");
            ui.end_row();
            ui.label("macOS");
            ui.label("Tier 1 shell");
            ui.label("FinalUse + effects; notarized .app updater is release-gated");
            ui.end_row();
            ui.label("Windows 11");
            ui.label("Preview");
            ui.label("window/backend/read-only; effects/update fail closed");
            ui.end_row();
        });
        ui.separator();
        ui.label(format!("locale: {}", self.locale));
        ui.label(self.t(
            "Accessibility: native AccessKit semantics, keyboard navigation and high-DPI viewport scaling.",
            "无障碍：原生 AccessKit 语义、键盘导航与高 DPI viewport 缩放。",
        ));
        ui.label(self.t(
            "Shortcuts: Cmd/Ctrl+R refresh, Alt+1..4 pages, Esc dismisses errors.",
            "快捷键：Cmd/Ctrl+R 刷新，Alt+1..4 切换页面，Esc 清除错误。",
        ));
        ui.small(format!(
            "endpoint={} protocol={} manifest={}",
            self.manifest.endpoint_id,
            self.manifest.protocol_version,
            self.manifest.manifest_digest.as_str()
        ));
    }
}

impl eframe::App for HeptaNativeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.drain_events();
        let context = ui.ctx().clone();
        self.shortcuts(&context);
        egui::CentralPanel::default().show(ui, |ui| {
            self.nav(ui);
            match self.page {
                Page::Runtime => self.runtime(ui),
                Page::Operations => self.operations(ui),
                Page::Updates => self.updates(ui),
                Page::Settings => self.settings(ui),
            }
        });
        if self.smoke_close || self.close_after_update {
            context.send_viewport_cmd(egui::ViewportCommand::Close);
            self.smoke_close = false;
        } else {
            context.request_repaint_after(Duration::from_millis(250));
        }
    }
}

pub fn run_native_ui(
    runtime: NativeShellRuntime,
    manifest: EndpointManifest,
    updater: Option<SignedUpdater>,
    locale: String,
    journal_warning: Option<String>,
    smoke_close: bool,
) -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Hepta")
            .with_inner_size([1120.0, 760.0])
            .with_min_inner_size([760.0, 520.0]),
        ..Default::default()
    };
    eframe::run_native(
        "hepta-native",
        options,
        Box::new(move |_creation| {
            Ok(Box::new(HeptaNativeApp::new(
                runtime,
                manifest,
                updater,
                locale,
                journal_warning,
                smoke_close,
            )))
        }),
    )
}
