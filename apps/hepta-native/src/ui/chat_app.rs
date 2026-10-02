//! Shared native chat presentation, independent from optional console readiness.
use super::*;
use crate::chat_runtime::ChatConfig;

pub(super) struct ChatShell {
    pub(super) chat: chat_model::ChatState,
    pub(super) chat_show_list: bool,
    pub(super) chat_bridge: chat_bridge::ChatBridge,
    pub(super) locale: Locale,
}
impl Default for ChatShell {
    fn default() -> Self {
        Self {
            chat: Default::default(),
            chat_show_list: true,
            chat_bridge: Default::default(),
            locale: Locale::detect(),
        }
    }
}
impl ChatShell {
    pub(super) fn navigation(&mut self, ui: &mut egui::Ui) {
        egui::Panel::left("hepta-workspace-rail")
            .exact_size(chat_model::design::RAIL_WIDTH)
            .resizable(false)
            .frame(egui::Frame::new().fill(theme::SURFACE).inner_margin(4))
            .show(ui, |ui| {
                ui.spacing_mut().button_padding.x = 4.0;
                ui.vertical_centered(|ui| {
                    theme::brand_mark(ui);
                    ui.label(
                        egui::RichText::new("HEPTA")
                            .small()
                            .strong()
                            .color(theme::CYAN),
                    );
                    ui.add_space(20.0);
                    for (tab, en, zh) in [
                        (chat_model::AppTab::Chat, "Chat", "聊天"),
                        (chat_model::AppTab::Console, "Console", "控制台"),
                    ] {
                        if ui
                            .add(
                                egui::Button::new(
                                    egui::RichText::new(self.locale.text(en, zh)).size(11.0),
                                )
                                .wrap_mode(egui::TextWrapMode::Extend)
                                .selected(self.chat.tab == tab)
                                .min_size(egui::vec2(52.0, chat_model::design::CONTROL_HEIGHT)),
                            )
                            .clicked()
                        {
                            self.chat.tab = tab;
                        }
                    }
                });
            });
    }
}

struct ChatOnlyApp {
    chat: ChatShell,
    console_failure: String,
}
impl ChatOnlyApp {
    fn show(&mut self, ui: &mut egui::Ui) {
        theme::ensure_initialized(ui.ctx());
        self.chat.poll_chat(ui.ctx());
        self.chat.navigation(ui);
        match self.chat.chat.tab {
            chat_model::AppTab::Chat => self.chat.chat_view(ui),
            chat_model::AppTab::Console => {
                egui::CentralPanel::default().frame(theme::card()).show(ui, |ui| {
                    ui.heading(self.chat.locale.text("Console unavailable", "控制台不可用"));
                    ui.label(self.chat.locale.text("Chat has its own authenticated connection. Console actions remain unavailable until its signed configuration and runtime are ready.", "聊天使用独立的已验证连接。控制台操作需等待其签名配置和运行时就绪。"));
                    egui::ScrollArea::vertical().show(ui, |ui| {
                        ui.label(&self.console_failure);
                        ui.separator();
                        ui.heading(self.chat.locale.text("Console setup", "控制台设置"));
                        ui.label(self.chat.locale.text("Provision the signed endpoint manifest and trusted keys in the native configuration, then restart Hepta. No signing credentials or permissions are created here.", "请在原生配置中设置签名端点清单和受信密钥，然后重启 Hepta。此处不会创建签名凭据或权限。"));
                        if ui.button(self.chat.locale.text("Exit to configure", "退出并配置")).clicked() { ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close); }
                    });
                });
            }
        }
    }
}

impl eframe::App for ChatOnlyApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.show(ui);
    }
}

/// Presents independent setup failures without manufacturing either authority.
pub fn show_chat_setup_shell(
    config: Option<ChatConfig>,
    chat_failure: Option<String>,
    console_failure: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut chat = ChatShell::default();
    if let Some(config) = config {
        if let Err(error) = chat.configure_chat(config) {
            chat.chat.availability = chat_model::ChatAvailability::Failed;
            chat.chat_bridge.error = Some(error);
        }
    } else if let Some(error) = chat_failure {
        chat.chat.availability = chat_model::ChatAvailability::Failed;
        chat.chat_bridge.error = Some(error);
    }
    let app = ChatOnlyApp {
        chat,
        console_failure,
    };
    let fonts = crate::fonts::load_fallback(None)?;
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Hepta")
            .with_inner_size([1180.0, 760.0])
            .with_min_inner_size([520.0, 420.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Hepta",
        options,
        Box::new(move |context| {
            if let Some(fonts) = fonts {
                context.egui_ctx.set_fonts(fonts);
            }
            Ok(Box::new(app))
        }),
    )
    .map_err(|error| error.to_string().into())
}

#[cfg(test)]
#[path = "chat_app_tests.rs"]
mod tests;
