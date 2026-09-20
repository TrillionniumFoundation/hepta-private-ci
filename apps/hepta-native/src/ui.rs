use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::SignedFinalUseGrant;
use eframe::egui;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::PlatformAction;
use crate::model::PlatformPayload;
use crate::model::PlatformRequest;
use crate::runtime::NativeShellRuntime;
use crate::security::now_unix_ms;
use crate::session_store::SessionReferenceStore;
use crate::updater::PendingUpdateStatus;
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
            .unwrap_or_default()
            .to_ascii_lowercase();
        if locale.starts_with("zh") {
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

pub struct HeptaNativeApp {
    runtime: NativeShellRuntime,
    manifest: EndpointManifest,
    screen: Screen,
    locale: Locale,
    status: Option<serde_json::Value>,
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
    pending_update_path: PathBuf,
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
        let mut app = Self {
            runtime,
            manifest,
            screen: Screen::Runtime,
            locale: Locale::detect(),
            status: None,
            last_error: None,
            operation_subject_id: "operator.local".to_owned(),
            operation_id: format!(
                "native.ui.{}.{}",
                std::process::id(),
                now_unix_ms()?.max(1)
            ),
            operation_action: PlatformAction::CopyText,
            operation_path: String::new(),
            operation_text: String::new(),
            notification_title: String::new(),
            notification_body: String::new(),
            operation_grant_path: String::new(),
            operation_binding: None,
            operation_message: None,
            pending_update_path: updater.pending_path(),
            updater,
            activate_update_on_exit,
            update_manifest_path: String::new(),
            update_package_path: String::new(),
            update_message: None,
        };
        app.refresh();
        Ok(app)
    }

    fn refresh(&mut self) {
        match self.runtime.refresh_runtime_view() {
            Ok((_presentation, status)) => {
                self.status = Some(status);
                self.operation_binding = None;
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(error.to_string()),
        }
    }

    fn reconcile(&mut self) {
        match self.runtime.reconcile_pending() {
            Ok(_) => self.last_error = None,
            Err(error) => self.last_error = Some(error.to_string()),
        }
    }

    fn top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.heading("Hepta Native");
            ui.separator();
            if self.runtime.session().is_some() {
                ui.label(self.locale.text("Connected", "已连接"));
            } else {
                ui.label(self.locale.text("Disconnected", "未连接"));
            }
            if ui.button(self.locale.text("Refresh", "刷新")).clicked() {
                self.refresh();
            }
            if ui.button(self.locale.text("Reconcile", "对账")).clicked() {
                self.reconcile();
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
                    ui.selectable_value(
                        &mut self.operation_action,
                        action,
                        action.to_string(),
                    );
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
        ui.horizontal(|ui| {
            if ui
                .button(self.locale.text("Prepare exact binding", "生成精确 binding"))
                .clicked()
            {
                self.prepare_operation_binding();
            }
            if ui
                .button(self.locale.text("Execute with signed grant", "使用签名 grant 执行"))
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
        let operations = self.runtime.operation_history();
        if operations.is_empty() {
            ui.label(self.locale.text("No operation receipts.", "暂无操作回执。"));
            return;
        }
        egui::ScrollArea::vertical().show(ui, |ui| {
            for receipt in operations.iter().rev() {
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
            let binding = self.runtime.prepare_platform_binding(
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
        let outcome = (|| -> Result<String, ShellError> {
            let grant_path = PathBuf::from(self.operation_grant_path.trim());
            if !grant_path.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "signed final-use grant path must be absolute".to_owned(),
                ));
            }
            let metadata = std::fs::metadata(&grant_path)?;
            if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 16 * 1024 {
                return Err(ShellError::InvalidInput(
                    "signed final-use grant must be a non-empty regular file <= 16 KiB"
                        .to_owned(),
                ));
            }
            let grant: SignedFinalUseGrant =
                serde_json::from_slice(&std::fs::read(&grant_path)?)?;
            let displayed_revision = self
                .runtime
                .view()
                .map(|view| view.revision)
                .ok_or_else(|| ShellError::State("native runtime view is unavailable".to_owned()))?;
            let receipt = self.runtime.request_platform_capability(PlatformRequest {
                subject_id: self.operation_subject_id.trim().to_owned(),
                operation_id: self.operation_id.trim().to_owned(),
                displayed_revision,
                payload: self.operation_payload()?,
                grant,
            })?;
            Ok(format!(
                "{}: terminal={} status={:?}",
                receipt.key.operation_id, receipt.terminal_observed, receipt.terminal_status
            ))
        })();
        match outcome {
            Ok(message) => {
                self.operation_message = Some(message);
                self.last_error = None;
            }
            Err(error) => {
                self.operation_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }

    fn updates_view(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Signed updates", "签名更新"));
        ui.label(self.locale.text(
            "Only a signed stable-channel manifest can be staged. Activation closes this GUI first, then a separate updater helper re-verifies the manifest, installed predecessor and staged package before replacement.",
            "只有签名的 stable-channel 清单才能进入暂存。激活时先关闭 GUI，再由独立 updater 辅助程序重新验证清单、已安装前任版本和暂存包后执行替换。",
        ));
        ui.separator();
        ui.label(self.locale.text("Signed manifest path", "签名清单路径"));
        ui.text_edit_singleline(&mut self.update_manifest_path);
        ui.label(self.locale.text("Package path", "更新包路径"));
        ui.text_edit_singleline(&mut self.update_package_path);
        if ui
            .button(self.locale.text("Verify & stage", "验证并暂存"))
            .clicked()
        {
            self.stage_update();
        }
        ui.separator();
        ui.label(format!(
            "{}: {}",
            self.locale.text("Pending record", "待处理记录"),
            self.pending_update_path.display()
        ));
        match self.updater.load_pending() {
            Ok(Some(pending)) => {
                ui.label(format!(
                    "{}: {:?}",
                    self.locale.text("Pending status", "待处理状态"),
                    pending.status
                ));
                ui.label(format!(
                    "{}: {}",
                    self.locale.text("Package digest", "包摘要"),
                    pending.manifest.package_digest
                ));
                if pending.status == PendingUpdateStatus::Staged
                    && ui
                        .button(
                            self.locale
                                .text("Activate on restart & close", "关闭并在重启时激活"),
                        )
                        .clicked()
                {
                    self.activate_update_on_exit.store(true, Ordering::SeqCst);
                    self.update_message = Some(
                        self.locale
                            .text(
                                "Closing the GUI; the external updater will perform final verification and activation.",
                                "正在关闭 GUI；外部 updater 将执行最终验证与激活。",
                            )
                            .to_owned(),
                    );
                    ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
            Ok(None) => {
                ui.label(self.locale.text("No pending update", "无待处理更新"));
            }
            Err(error) => {
                self.last_error = Some(error.to_string());
            }
        }
        if let Some(message) = &self.update_message {
            ui.separator();
            ui.label(message);
        }
    }

    fn stage_update(&mut self) {
        let outcome = (|| -> Result<String, ShellError> {
            let manifest_path = PathBuf::from(self.update_manifest_path.trim());
            let package_path = PathBuf::from(self.update_package_path.trim());
            if !manifest_path.is_absolute() || !package_path.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "update manifest and package paths must be absolute".to_owned(),
                ));
            }
            let manifest: SignedUpdateManifestV1 =
                serde_json::from_slice(&std::fs::read(&manifest_path)?)?;
            let pending = self.updater.verify_and_stage(
                manifest,
                &package_path,
                self.manifest.protocol_version,
            )?;
            Ok(format!(
                "staged {} for {}/{}",
                pending.manifest.package_digest,
                pending.manifest.platform,
                pending.manifest.architecture
            ))
        })();
        match outcome {
            Ok(message) => {
                self.update_message = Some(message);
                self.last_error = None;
            }
            Err(error) => {
                self.update_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }

    fn accessibility_view(&self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Accessibility & input", "无障碍与输入"));
        ui.label(self.locale.text(
            "The selected native framework is eframe/egui with AccessKit enabled. Windows, macOS and Linux are first-class build targets. Native DPI scaling is delegated to winit/eframe.",
            "选定的原生框架为 eframe/egui，并启用 AccessKit。Windows、macOS、Linux 均为一等构建目标；原生 DPI 缩放交由 winit/eframe 处理。",
        ));
        ui.separator();
        ui.label(self.locale.text(
            "Keyboard focus follows egui's native focus order. Use Tab/Shift+Tab to move between controls and Enter/Space to activate focused buttons.",
            "键盘焦点遵循 egui 原生焦点顺序。使用 Tab/Shift+Tab 切换控件，Enter/Space 激活当前按钮。",
        ));
        ui.label(self.locale.text(
            "Locale selection currently follows LC_ALL/LC_MESSAGES/LANG and includes English and Chinese shell strings.",
            "当前区域设置依据 LC_ALL/LC_MESSAGES/LANG，壳层字符串支持英文与中文。",
        ));
    }
}

impl eframe::App for HeptaNativeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
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
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        let _ = self.runtime.close();
    }
}
