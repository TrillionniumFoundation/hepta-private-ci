use crate::backend::GatewayBackend;
use crate::journal::OperationJournal;
use crate::platform::SystemPlatformAdapter;
use crate::runtime::ShellRuntime;
use crate::security::GrantVerifier;
use crate::state_root;
use crate::types::GrantBinding;
use crate::types::NativeSession;
use crate::types::PlatformAction;
use crate::types::PlatformDecision;
use crate::types::PlatformPayload;
use crate::types::RuntimeView;
use crate::types::SignedPlatformGrant;
use crate::types::SignedUpdateManifest;
use crate::types::StagedUpdate;
use crate::update::UpdateManager;
use crate::update::UpdateVerifier;
use eframe::egui;
use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

type DesktopShell = ShellRuntime<GatewayBackend, SystemPlatformAdapter>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Page {
    Overview,
    Runtime,
    Effects,
    Updates,
    Diagnostics,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Locale {
    English,
    Chinese,
}

#[derive(Debug)]
enum Command {
    Connect,
    Refresh,
    Prepare {
        operation_id: String,
        action: PlatformAction,
        resource: String,
        payload: PlatformPayload,
        displayed_revision: u64,
    },
    Execute {
        operation_id: String,
        action: PlatformAction,
        resource: String,
        payload: PlatformPayload,
        displayed_revision: u64,
        grant_json: String,
    },
    StageUpdate {
        manifest_path: PathBuf,
        package_path: PathBuf,
    },
    ApplyUpdate,
}

#[derive(Debug)]
enum Event {
    Security {
        platform_authority: bool,
        update_authority: bool,
    },
    Connected(NativeSession),
    View(RuntimeView),
    Binding(GrantBinding),
    Decision(PlatformDecision),
    UpdateStaged(StagedUpdate),
    UpdateHelperLaunched(PathBuf),
    Error(String),
}

pub struct AppOptions {
    pub post_update_ready: Option<PathBuf>,
}

pub struct HeptaApp {
    tx: mpsc::Sender<Command>,
    rx: mpsc::Receiver<Event>,
    page: Page,
    locale: Locale,
    session: Option<NativeSession>,
    view: Option<RuntimeView>,
    platform_authority: bool,
    update_authority: bool,
    last_error: Option<String>,
    last_decision: Option<PlatformDecision>,
    prepared_binding: Option<GrantBinding>,
    staged_update: Option<StagedUpdate>,
    last_refresh: Instant,
    refresh_pending: bool,
    close_requested: bool,

    operation_id: String,
    resource: String,
    effect_action: PlatformAction,
    effect_payload: String,
    notification_body: String,
    grant_json: String,
    update_manifest_path: String,
    update_package_path: String,
}

impl HeptaApp {
    pub fn new(options: AppOptions) -> Result<Self, Box<dyn std::error::Error>> {
        let root = state_root()?;
        let backend = GatewayBackend::production_default()?;
        let manifest = backend.manifest();
        let journal = OperationJournal::open(root.join("operations.jsonl"))?;
        let verifier = GrantVerifier::load(&root)?;
        let platform_authority = verifier.is_some();
        let update_verifier = UpdateVerifier::load()?;
        let update_authority = update_verifier.is_some();
        let shell = DesktopShell::new(backend, SystemPlatformAdapter::new(), journal, verifier);
        let updater = UpdateManager::new(root, update_verifier);

        let (command_tx, command_rx) = mpsc::channel();
        let (event_tx, event_rx) = mpsc::channel();
        std::thread::Builder::new()
            .name("hepta-native-worker".to_string())
            .spawn(move || worker(shell, updater, manifest, command_rx, event_tx))?;

        let _ = command_tx.send(Command::Connect);
        if let Some(marker) = options.post_update_ready {
            if let Some(parent) = marker.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(marker, b"ready\n")?;
        }

        let locale = std::env::var("LANG")
            .ok()
            .filter(|lang| lang.to_ascii_lowercase().starts_with("zh"))
            .map(|_| Locale::Chinese)
            .unwrap_or(Locale::English);

        Ok(Self {
            tx: command_tx,
            rx: event_rx,
            page: Page::Overview,
            locale,
            session: None,
            view: None,
            platform_authority,
            update_authority,
            last_error: None,
            last_decision: None,
            prepared_binding: None,
            staged_update: None,
            last_refresh: Instant::now(),
            refresh_pending: true,
            close_requested: false,
            operation_id: "operation.1".to_string(),
            resource: "native.user-request".to_string(),
            effect_action: PlatformAction::CopyText,
            effect_payload: String::new(),
            notification_body: String::new(),
            grant_json: String::new(),
            update_manifest_path: String::new(),
            update_package_path: String::new(),
        })
    }

    fn tr<'a>(&self, english: &'a str, chinese: &'a str) -> &'a str {
        match self.locale {
            Locale::English => english,
            Locale::Chinese => chinese,
        }
    }

    fn drain_events(&mut self) {
        while let Ok(event) = self.rx.try_recv() {
            self.refresh_pending = false;
            match event {
                Event::Security {
                    platform_authority,
                    update_authority,
                } => {
                    self.platform_authority = platform_authority;
                    self.update_authority = update_authority;
                }
                Event::Connected(session) => {
                    self.session = Some(session);
                    self.last_error = None;
                }
                Event::View(view) => {
                    self.view = Some(view);
                    self.last_error = None;
                    self.last_refresh = Instant::now();
                }
                Event::Binding(binding) => {
                    self.prepared_binding = Some(binding);
                    self.last_error = None;
                }
                Event::Decision(decision) => {
                    self.last_decision = Some(decision);
                    self.last_error = None;
                }
                Event::UpdateStaged(staged) => {
                    self.staged_update = Some(staged);
                    self.last_error = None;
                }
                Event::UpdateHelperLaunched(path) => {
                    self.last_error = Some(format!(
                        "Updater launched with request {}; closing shell for replacement",
                        path.display()
                    ));
                    self.close_requested = true;
                }
                Event::Error(error) => self.last_error = Some(error),
            }
        }
    }

    fn request_refresh(&mut self) {
        if !self.refresh_pending {
            self.refresh_pending = self.tx.send(Command::Refresh).is_ok();
        }
    }

    fn payload(&self) -> PlatformPayload {
        match self.effect_action {
            PlatformAction::OpenPath | PlatformAction::RevealPath => PlatformPayload::Path {
                path: PathBuf::from(self.effect_payload.trim()),
            },
            PlatformAction::CopyText => PlatformPayload::Text {
                text: self.effect_payload.clone(),
            },
            PlatformAction::Notify => PlatformPayload::Notification {
                title: self.effect_payload.clone(),
                body: self.notification_body.clone(),
            },
        }
    }

    fn nav(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading("Hepta Native");
            ui.separator();
            for (page, en, zh) in [
                (Page::Overview, "Overview", "总览"),
                (Page::Runtime, "Runtime", "运行时"),
                (Page::Effects, "Effects", "系统操作"),
                (Page::Updates, "Updates", "更新"),
                (Page::Diagnostics, "Diagnostics", "诊断"),
            ] {
                if ui
                    .selectable_label(self.page == page, self.tr(en, zh))
                    .clicked()
                {
                    self.page = page;
                }
            }
            ui.separator();
            if ui
                .button(match self.locale {
                    Locale::English => "中文",
                    Locale::Chinese => "English",
                })
                .clicked()
            {
                self.locale = match self.locale {
                    Locale::English => Locale::Chinese,
                    Locale::Chinese => Locale::English,
                };
            }
        });
        ui.separator();
    }

    fn overview(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.tr("Native application status", "原生应用状态"));
        ui.label(self.tr(
            "Rust desktop host using eframe/egui with AccessKit. Runtime mutations remain owned by backend modules.",
            "Rust 桌面宿主基于 eframe/egui + AccessKit；运行时事实与变更仍由后端 owner 模块负责。",
        ));
        ui.add_space(8.0);
        egui::Grid::new("status-grid").striped(true).show(ui, |ui| {
            ui.label(self.tr("Runtime session", "运行时会话"));
            ui.label(if self.session.is_some() {
                "connected"
            } else {
                "disconnected"
            });
            ui.end_row();
            ui.label(self.tr("Coherent view", "一致视图"));
            ui.label(
                self.view
                    .as_ref()
                    .map(|view| {
                        format!(
                            "generation {} / revision {}",
                            view.generation, view.revision
                        )
                    })
                    .unwrap_or_else(|| "unavailable".to_string()),
            );
            ui.end_row();
            ui.label(self.tr("Platform grant root", "平台授权信任根"));
            ui.label(if self.platform_authority {
                "configured"
            } else {
                "fail-closed"
            });
            ui.end_row();
            ui.label(self.tr("Update trust root", "更新信任根"));
            ui.label(if self.update_authority {
                "configured"
            } else {
                "fail-closed"
            });
            ui.end_row();
            ui.label(self.tr("OS / arch", "系统 / 架构"));
            ui.label(format!(
                "{} / {}",
                std::env::consts::OS,
                std::env::consts::ARCH
            ));
            ui.end_row();
        });
        ui.add_space(8.0);
        if ui
            .button(self.tr("Refresh runtime", "刷新运行时"))
            .clicked()
        {
            self.request_refresh();
        }
        if let Some(error) = &self.last_error {
            ui.add_space(8.0);
            ui.colored_label(ui.visuals().error_fg_color, error);
        }
    }

    fn runtime_page(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.tr("Runtime view", "运行时视图"));
        if let Some(session) = &self.session {
            ui.monospace(format!(
                "session={} generation={} protocol={}",
                session.session_id, session.generation, session.protocol_version
            ));
        }
        if let Some(view) = &self.view {
            ui.monospace(format!("digest={} revision={}", view.digest, view.revision));
            ui.separator();
            let mut pretty = serde_json::to_string_pretty(&view.body).unwrap_or_default();
            ui.add(
                egui::TextEdit::multiline(&mut pretty)
                    .font(egui::TextStyle::Monospace)
                    .desired_rows(24)
                    .interactive(false),
            );
        } else {
            ui.label(self.tr("No coherent view yet.", "尚无一致视图。"));
        }
    }

    fn effects_page(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.tr("Authority-bound platform effects", "绑定授权的平台系统操作"));
        ui.label(self.tr(
            "Each effect needs an explicit per-session user confirmation and an independently signed grant binding the final payload.",
            "每次系统操作都需要本会话的显式用户确认，以及独立签名、绑定最终 payload 的 grant。",
        ));
        if !self.platform_authority {
            ui.colored_label(
                ui.visuals().warn_fg_color,
                self.tr(
                    "No platform grant trust root is configured; effects fail closed.",
                    "尚未配置平台 grant 信任根；所有系统操作默认拒绝。",
                ),
            );
        }
        ui.horizontal(|ui| {
            ui.label(self.tr("Action", "动作"));
            for (action, label) in [
                (PlatformAction::OpenPath, "open path"),
                (PlatformAction::RevealPath, "reveal path"),
                (PlatformAction::CopyText, "copy text"),
                (PlatformAction::Notify, "notify"),
            ] {
                ui.selectable_value(&mut self.effect_action, action, label);
            }
        });
        ui.horizontal(|ui| {
            ui.label("operation_id");
            ui.text_edit_singleline(&mut self.operation_id);
        });
        ui.horizontal(|ui| {
            ui.label("resource");
            ui.text_edit_singleline(&mut self.resource);
        });
        ui.label(match self.effect_action {
            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                self.tr("Absolute path", "绝对路径")
            }
            PlatformAction::CopyText => self.tr("Text", "文本"),
            PlatformAction::Notify => self.tr("Notification title", "通知标题"),
        });
        ui.text_edit_multiline(&mut self.effect_payload);
        if self.effect_action == PlatformAction::Notify {
            ui.label(self.tr("Notification body", "通知正文"));
            ui.text_edit_multiline(&mut self.notification_body);
        }
        let revision = self
            .view
            .as_ref()
            .map(|view| view.revision)
            .unwrap_or_default();
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    revision > 0,
                    egui::Button::new(self.tr("Prepare binding", "生成绑定数据")),
                )
                .clicked()
            {
                self.prepared_binding = None;
                let _ = self.tx.send(Command::Prepare {
                    operation_id: self.operation_id.clone(),
                    action: self.effect_action.clone(),
                    resource: self.resource.clone(),
                    payload: self.payload(),
                    displayed_revision: revision,
                });
            }
            if ui
                .add_enabled(
                    revision > 0 && !self.grant_json.trim().is_empty(),
                    egui::Button::new(self.tr("Execute signed request", "执行已签名请求")),
                )
                .clicked()
            {
                let _ = self.tx.send(Command::Execute {
                    operation_id: self.operation_id.clone(),
                    action: self.effect_action.clone(),
                    resource: self.resource.clone(),
                    payload: self.payload(),
                    displayed_revision: revision,
                    grant_json: self.grant_json.clone(),
                });
            }
        });
        if let Some(binding) = &self.prepared_binding {
            ui.label(self.tr(
                "Send this exact binding to the independent authority signer:",
                "将下面的精确 binding 交给独立 authority signer：",
            ));
            let mut text = serde_json::to_string_pretty(binding).unwrap_or_default();
            ui.add(
                egui::TextEdit::multiline(&mut text)
                    .font(egui::TextStyle::Monospace)
                    .desired_rows(8)
                    .interactive(false),
            );
        }
        ui.label(self.tr("SignedPlatformGrant JSON", "SignedPlatformGrant JSON"));
        ui.add(
            egui::TextEdit::multiline(&mut self.grant_json)
                .font(egui::TextStyle::Monospace)
                .desired_rows(8),
        );
        if let Some(decision) = &self.last_decision {
            let mut text = serde_json::to_string_pretty(decision).unwrap_or_default();
            ui.label(self.tr("Last decision", "最近一次结果"));
            ui.add(
                egui::TextEdit::multiline(&mut text)
                    .font(egui::TextStyle::Monospace)
                    .desired_rows(8)
                    .interactive(false),
            );
        }
    }

    fn updates_page(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.tr("Signed application update", "签名应用更新"));
        ui.label(self.tr(
            "The updater verifies Ed25519 manifest signature, exact package/predecessor hashes and compatibility. Optional OS signing checks are enforced when HEPTA_NATIVE_REQUIRE_OS_CODESIGN=1.",
            "更新器校验 Ed25519 manifest 签名、package/predecessor 精确哈希与兼容性；设置 HEPTA_NATIVE_REQUIRE_OS_CODESIGN=1 时还强制 OS 签名检查。",
        ));
        if !self.update_authority {
            ui.colored_label(
                ui.visuals().warn_fg_color,
                self.tr(
                    "No update trust root is configured.",
                    "尚未配置更新信任根。",
                ),
            );
        }
        ui.horizontal(|ui| {
            ui.label(self.tr("Manifest", "Manifest"));
            ui.text_edit_singleline(&mut self.update_manifest_path);
        });
        ui.horizontal(|ui| {
            ui.label(self.tr("Package", "安装包"));
            ui.text_edit_singleline(&mut self.update_package_path);
        });
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    self.update_authority
                        && !self.update_manifest_path.trim().is_empty()
                        && !self.update_package_path.trim().is_empty(),
                    egui::Button::new(self.tr("Verify and stage", "校验并暂存")),
                )
                .clicked()
            {
                let _ = self.tx.send(Command::StageUpdate {
                    manifest_path: PathBuf::from(self.update_manifest_path.trim()),
                    package_path: PathBuf::from(self.update_package_path.trim()),
                });
            }
            if ui
                .add_enabled(
                    self.staged_update.is_some(),
                    egui::Button::new(self.tr("Apply and restart", "应用并重启")),
                )
                .clicked()
            {
                let _ = self.tx.send(Command::ApplyUpdate);
            }
        });
        if let Some(staged) = &self.staged_update {
            ui.monospace(format!(
                "staged {} -> {}",
                staged.manifest.manifest.version,
                staged.staged_path.display()
            ));
        }
    }

    fn diagnostics_page(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.tr("Diagnostics", "诊断"));
        ui.monospace(format!(
            "app={} {}",
            crate::APP_ID,
            env!("CARGO_PKG_VERSION")
        ));
        ui.monospace(format!(
            "platform={} architecture={}",
            std::env::consts::OS,
            std::env::consts::ARCH
        ));
        if let Some(view) = &self.view {
            ui.monospace(format!(
                "runtime_generation={} revision={} stale={}",
                view.generation, view.revision, view.stale
            ));
        }
        ui.label(self.tr(
            "Indeterminate platform effects are never replayed. Retry performs reconciliation only; if the OS has no trustworthy terminal observer, the operation remains indeterminate.",
            "不确定的平台操作绝不会自动重放；重试只执行 reconciliation。若 OS 没有可信终态观察器，该操作会继续保持 indeterminate。",
        ));
    }
}

impl eframe::App for HeptaApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.drain_events();
        if self.last_refresh.elapsed() >= Duration::from_secs(3) && self.session.is_some() {
            self.request_refresh();
        }
        if self.close_requested {
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
        }
        ui.ctx().request_repaint_after(Duration::from_millis(250));

        egui::CentralPanel::default().show(ui, |ui| {
            self.nav(ui);
            match self.page {
                Page::Overview => self.overview(ui),
                Page::Runtime => self.runtime_page(ui),
                Page::Effects => self.effects_page(ui),
                Page::Updates => self.updates_page(ui),
                Page::Diagnostics => self.diagnostics_page(ui),
            }
        });
    }
}

fn worker(
    mut shell: DesktopShell,
    updater: UpdateManager,
    manifest: crate::types::RuntimeManifest,
    rx: mpsc::Receiver<Command>,
    tx: mpsc::Sender<Event>,
) {
    let _ = tx.send(Event::Security {
        platform_authority: shell.authority_configured(),
        update_authority: updater.configured(),
    });
    let mut staged: Option<StagedUpdate> = None;
    while let Ok(command) = rx.recv() {
        let event = match command {
            Command::Connect => match shell.connect(&manifest).and_then(|session| {
                let view = shell.refresh_view()?;
                Ok((session, view))
            }) {
                Ok((session, view)) => {
                    let _ = tx.send(Event::Connected(session));
                    Event::View(view)
                }
                Err(error) => Event::Error(error.to_string()),
            },
            Command::Refresh => match shell.refresh_view() {
                Ok(view) => Event::View(view),
                Err(error) => Event::Error(error.to_string()),
            },
            Command::Prepare {
                operation_id,
                action,
                resource,
                payload,
                displayed_revision,
            } => match shell.prepare_binding(
                &operation_id,
                action,
                &resource,
                &payload,
                displayed_revision,
            ) {
                Ok(binding) => Event::Binding(binding),
                Err(error) => Event::Error(error.to_string()),
            },
            Command::Execute {
                operation_id,
                action,
                resource,
                payload,
                displayed_revision,
                grant_json,
            } => match serde_json::from_str::<SignedPlatformGrant>(&grant_json) {
                Ok(grant) => {
                    shell.allow_once(action.clone());
                    match shell.request_platform_capability(
                        &operation_id,
                        action,
                        &resource,
                        &payload,
                        displayed_revision,
                        &grant,
                    ) {
                        Ok(decision) => Event::Decision(decision),
                        Err(error) => Event::Error(error.to_string()),
                    }
                }
                Err(error) => Event::Error(format!("signed grant JSON: {error}")),
            },
            Command::StageUpdate {
                manifest_path,
                package_path,
            } => {
                let result = (|| {
                    let manifest: SignedUpdateManifest =
                        serde_json::from_slice(&std::fs::read(manifest_path)?)?;
                    let current = std::env::current_exe()?;
                    updater.stage(manifest, &package_path, &current)
                })();
                match result {
                    Ok(value) => {
                        staged = Some(value.clone());
                        Event::UpdateStaged(value)
                    }
                    Err(error) => Event::Error(error.to_string()),
                }
            }
            Command::ApplyUpdate => match staged.as_ref() {
                Some(staged) => match std::env::current_exe()
                    .map_err(crate::update::UpdateError::Io)
                    .and_then(|current| updater.launch_updater(staged, &current))
                {
                    Ok(path) => Event::UpdateHelperLaunched(path),
                    Err(error) => Event::Error(error.to_string()),
                },
                None => Event::Error("no staged update".to_string()),
            },
        };
        if tx.send(event).is_err() {
            break;
        }
    }
}
