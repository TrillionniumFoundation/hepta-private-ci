//! Failure presentation never creates trust, authority, or an effect retry.
use super::*;
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StartupStage {
    Configuration,
    Trust,
    Endpoint,
    Credential,
    Backend,
    Initialization,
}

impl StartupStage {
    fn label(self, locale: Locale) -> &'static str {
        match self {
            Self::Configuration => locale.text("Launch configuration", "启动配置"),
            Self::Trust => locale.text("Trusted public keys", "受信任公钥"),
            Self::Endpoint => locale.text("Signed endpoint verification", "签名端点验证"),
            Self::Credential => locale.text("OS keyring access", "系统密钥环访问"),
            Self::Backend => locale.text("Local gateway configuration", "本地网关配置"),
            Self::Initialization => locale.text("Native initialization", "原生初始化"),
        }
    }

    fn remediation(self, locale: Locale) -> &'static str {
        match self {
            Self::Configuration => locale.text("Check the configuration path and required absolute paths. Ask your operator for the signed endpoint and trust inputs; this screen cannot create them.", "检查配置文件路径及所需的绝对路径。请向管理员获取签名端点与信任输入；此界面不能创建它们。"),
            Self::Trust | Self::Endpoint => locale.text("Ask the independent authority owner to correct or renew the signed inputs. Verification cannot be skipped, and unknown keys cannot be trusted here.", "请独立权限所有者修正或续签输入。不能跳过验证，也不能在此信任未知密钥。"),
            Self::Credential => locale.text("Unlock your OS keyring and check the provisioned gateway account with your operator. Do not paste credentials into this window.", "解锁系统密钥环，并与管理员核对已配置的网关账户。请勿将凭据粘贴到此窗口。"),
            Self::Backend => locale.text("Check that the operator-provided endpoint names the intended local gateway. Remote endpoints and insecure fallback are not enabled.", "检查管理员提供的端点是否指向预期的本地网关。不会启用远程端点或不安全回退。"),
            Self::Initialization => locale.text("Close this window and resolve the reported startup failure before launching again. Do not delete the operation journal or replay an unknown operation.", "请关闭此窗口，解决报告的启动故障后重新启动。请勿删除操作日志或重放结果未知的操作。"),
        }
    }
}

#[derive(Debug)]
pub struct StartupFailure {
    stage: StartupStage,
    detail: String,
}

impl StartupFailure {
    pub fn new(stage: StartupStage, error: impl fmt::Display) -> Self {
        let mut detail = error.to_string();
        if detail.len() > 4096 {
            let mut end = 4096;
            while !detail.is_char_boundary(end) {
                end -= 1;
            }
            detail.truncate(end);
            detail.push_str("\n[details truncated]");
        }
        Self { stage, detail }
    }
}

impl fmt::Display for StartupFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{}: {}",
            self.stage.label(Locale::English),
            self.detail
        )
    }
}

impl std::error::Error for StartupFailure {}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum StartupRetry {
    InputsOnly,
    ExitOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StartupDecision {
    RetryInputs,
    Exit,
}

pub(super) fn recovery_view(
    ui: &mut egui::Ui,
    failure: &StartupFailure,
    retry: StartupRetry,
    locale: Locale,
) -> Option<StartupDecision> {
    theme::ensure_initialized(ui.ctx());
    let mut decision = None;
    egui::CentralPanel::default().frame(egui::Frame::new().fill(theme::BACKGROUND).inner_margin(24)).show(ui, |ui| {
        egui::ScrollArea::vertical().show(ui, |ui| {
            ui.horizontal(|ui| {
                theme::brand_mark(ui);
                ui.label(egui::RichText::new("HEPTA").size(23.0).color(theme::CYAN));
            });
            ui.add_space(20.0);
            theme::section(ui, locale.text("Startup needs attention", "启动需要处理"), failure.stage.label(locale));
            theme::card().show(ui, |ui| {
                ui.set_min_width(ui.available_width());
                ui.label(egui::RichText::new(failure.stage.remediation(locale)).color(theme::WARNING));
                ui.separator();
                ui.label(locale.text("Technical details", "技术详情"));
                egui::ScrollArea::vertical().id_salt("startup-technical-details").max_height(120.0).show(ui, |ui| {
                    ui.add(egui::Label::new(egui::RichText::new(&failure.detail).monospace()).wrap());
                });
            });
            ui.add_space(16.0);
            ui.label(match retry {
                StartupRetry::InputsOnly => locale.text("Retry reloads the same configuration, signed inputs and keyring entry. No runtime session, update recovery or native operation has been admitted.", "重试仅重新读取同一配置、签名输入与密钥环条目。尚未接纳运行时会话、更新恢复或原生操作。"),
                StartupRetry::ExitOnly => locale.text("Initialization has advanced beyond the input-only boundary. This screen will not repeat recovery, session admission or native operations.", "初始化已越过仅输入阶段。此界面不会重复恢复、会话准入或原生操作。"),
            });
            ui.horizontal_wrapped(|ui| {
                if retry == StartupRetry::InputsOnly && ui.button(locale.text("Retry setup", "重试设置")).clicked() {
                    decision = Some(StartupDecision::RetryInputs);
                }
                if ui.button(locale.text("Exit", "退出")).clicked() {
                    decision = Some(StartupDecision::Exit);
                }
            });
        });
    });
    decision
}

struct RecoveryApp {
    failure: StartupFailure,
    retry: StartupRetry,
    decision: Arc<Mutex<StartupDecision>>,
    closing: bool,
}

impl eframe::App for RecoveryApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if self.closing {
            return;
        }
        if let Some(decision) = recovery_view(ui, &self.failure, self.retry, Locale::detect()) {
            *self
                .decision
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = decision;
            self.closing = true;
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
        }
    }
}

/// Present an ordinary-launch failure. Machine/helper/update-handoff invocations
/// must stay noninteractive; the caller owns the input-only retry boundary.
pub fn show_startup_recovery(
    failure: StartupFailure,
    retry: StartupRetry,
) -> Result<StartupDecision, eframe::Error> {
    let decision = Arc::new(Mutex::new(StartupDecision::Exit));
    let result = Arc::clone(&decision);
    let fonts = crate::fonts::load_fallback(None).ok().flatten();
    eframe::run_native(
        "hepta-native-startup",
        eframe::NativeOptions {
            renderer: eframe::Renderer::Glow,
            viewport: egui::ViewportBuilder::default()
                .with_title("Hepta Native / Startup")
                .with_inner_size([800.0, 560.0])
                .with_min_inner_size([640.0, 480.0]),
            ..Default::default()
        },
        Box::new(move |context| {
            if let Some(fonts) = fonts {
                context.egui_ctx.set_fonts(fonts);
            }
            Ok(Box::new(RecoveryApp {
                failure,
                retry,
                decision,
                closing: false,
            }))
        }),
    )?;
    let decision = *result
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    Ok(decision)
}

#[cfg(test)]
#[path = "startup_recovery_tests.rs"]
mod tests;
