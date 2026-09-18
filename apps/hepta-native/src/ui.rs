use std::path::PathBuf;

use eframe::egui;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::RuntimeView;
use crate::model::sha256_hex;
use crate::runtime::NativeShellRuntime;
use crate::session_store::SessionReferenceStore;

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
    view_revision: u64,
    pending_update_path: PathBuf,
}

impl HeptaNativeApp {
    pub fn new(
        mut runtime: NativeShellRuntime,
        manifest: EndpointManifest,
        pending_update_path: PathBuf,
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
            view_revision: 0,
            pending_update_path,
        };
        app.refresh();
        Ok(app)
    }

    fn refresh(&mut self) {
        match self.runtime.runtime_status() {
            Ok(status) => {
                let Some(session) = self.runtime.session().cloned() else {
                    self.last_error = Some("native session disappeared during refresh".to_owned());
                    return;
                };
                let bytes = match serde_json::to_vec(&status) {
                    Ok(bytes) => bytes,
                    Err(error) => {
                        self.last_error = Some(error.to_string());
                        return;
                    }
                };
                self.view_revision = self.view_revision.saturating_add(1).max(1);
                let view = RuntimeView {
                    session_id: session.session_id,
                    session_generation: session.generation,
                    generation: 1,
                    revision: self.view_revision,
                    digest: sha256_hex(bytes),
                    modules: vec!["runtime.agentd".to_owned(), "ui.native".to_owned()],
                };
                if let Err(error) = self.runtime.render_runtime_view(view) {
                    self.last_error = Some(error.to_string());
                    return;
                }
                self.status = Some(status);
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
        ui.label(format!("{}: {}", self.locale.text("Endpoint", "端点"), self.manifest.address));
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

    fn operations_view(&self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Native operations", "原生操作"));
        ui.label(self.locale.text(
            "Indeterminate operations are never automatically replayed. Reconcile asks the platform adapter for a trustworthy terminal observation.",
            "不确定操作绝不会自动重放。对账只接受平台适配器提供的可信终态观察。",
        ));
        ui.separator();
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

    fn updates_view(&self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Signed updates", "签名更新"));
        ui.label(self.locale.text(
            "Update selection, Ed25519 verification, staging, predecessor backup and rollback are implemented in Rust. Activation is performed by the separate hepta-native-updater helper so the running application never replaces itself.",
            "更新选择、Ed25519 验签、暂存、前任版本备份与回滚已由 Rust 实现。激活由独立 hepta-native-updater 辅助程序执行，运行中的应用不会自行替换自身。",
        ));
        ui.separator();
        ui.label(format!(
            "{}: {}",
            self.locale.text("Pending record", "待处理记录"),
            self.pending_update_path.display()
        ));
        ui.label(if self.pending_update_path.exists() {
            self.locale.text("Pending update exists", "存在待处理更新")
        } else {
            self.locale.text("No pending update", "无待处理更新")
        });
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
        egui::TopBottomPanel::top("hepta-native-top").show_inside(ui, |ui| {
            self.top_bar(ui);
        });
        egui::SidePanel::left("hepta-native-navigation")
            .resizable(false)
            .default_width(210.0)
            .show_inside(ui, |ui| self.navigation(ui));
        egui::CentralPanel::default().show_inside(ui, |ui| match self.screen {
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
