//! The native shell adapts to logical points, including user-requested zoom.
use super::*;

const DIAGNOSTIC_PREVIEW_BYTES: usize = 16 * 1024;

pub(super) fn diagnostic_preview(text: &str) -> (&str, bool) {
    let mut end = text.len().min(DIAGNOSTIC_PREVIEW_BYTES);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    (&text[..end], end < text.len())
}

impl HeptaNativeApp {
    pub(super) fn top_bar(&mut self, ui: &mut egui::Ui) {
        let busy = self.runtime_busy();
        ui.horizontal_wrapped(|ui| {
            theme::brand_mark(ui);
            ui.label(
                egui::RichText::new("HEPTA")
                    .size(23.0)
                    .strong()
                    .color(theme::CYAN),
            );
            ui.label(
                egui::RichText::new("NATIVE / CONTROL")
                    .small()
                    .color(theme::MUTED),
            );
            ui.separator();
            let (status, color) = if self
                .pending_runtime
                .as_ref()
                .is_some_and(|task| task.kind == UiTaskKind::Refresh)
            {
                (
                    self.locale
                        .text("Verifying runtime view", "正在验证运行时视图"),
                    theme::WARNING,
                )
            } else if self.connected && self.view_revision.is_some() {
                (
                    self.locale
                        .text("Authenticated view available", "已验证视图可用"),
                    theme::CYAN,
                )
            } else {
                (
                    self.locale
                        .text("No current authenticated view", "当前没有有效的已验证视图"),
                    theme::WARNING,
                )
            };
            ui.label(egui::RichText::new(status).color(color));
        });
        ui.horizontal_wrapped(|ui| {
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
            for task in [
                self.pending_runtime.as_ref(),
                self.pending_read.as_ref(),
                self.pending_picker.as_ref(),
            ]
            .into_iter()
            .flatten()
            {
                ui.spinner();
                ui.label(task.kind.label(self.locale));
            }
        });
        if let Some(error) = &self.last_error {
            theme::card().show(ui, |ui| {
                ui.label(
                    egui::RichText::new(self.locale.text("Action needs attention", "操作需要处理"))
                        .strong()
                        .color(theme::ERROR),
                );
                egui::ScrollArea::vertical()
                    .id_salt("native-error")
                    .max_height(88.0)
                    .show(ui, |ui| {
                        ui.label(error);
                    });
            });
        }
    }

    pub(super) fn navigation(&mut self, ui: &mut egui::Ui) {
        ui.label(
            egui::RichText::new(self.locale.text("WORKSPACE", "工作区"))
                .small()
                .color(theme::VIOLET),
        );
        for (screen, en, zh) in [
            (Screen::Runtime, "Runtime", "运行时"),
            (Screen::Operations, "Operations", "操作"),
            (Screen::Updates, "Updates", "更新"),
            (Screen::Accessibility, "Accessibility", "无障碍"),
        ] {
            let width = if ui.layout().is_vertical() {
                ui.available_width()
            } else {
                0.0
            };
            if ui
                .add(
                    egui::Button::new(self.locale.text(en, zh))
                        .selected(self.screen == screen)
                        .min_size(egui::vec2(width, 36.0))
                        .wrap_mode(egui::TextWrapMode::Extend),
                )
                .clicked()
                && self.screen != screen
            {
                task_supervisor::cancel_file_input(ui.ctx());
                self.file_input_focus = None;
                self.screen = screen;
            }
        }
    }

    pub(super) fn runtime_view(&mut self, ui: &mut egui::Ui) {
        theme::section(
            ui,
            self.locale.text("Runtime overview", "运行时概览"),
            self.locale.text(
                "Authenticated observations from the local gateway",
                "来自本地网关的已验证观察",
            ),
        );
        theme::card().show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            if let Some(view) = &self.ready_view {
                ui.label(egui::RichText::new(self.locale.text("Current verified snapshot", "当前已验证快照")).strong().color(theme::CYAN));
                ui.horizontal_wrapped(|ui| {
                    ui.label(format!("{} {}", self.locale.text("Revision", "修订"), view.revision));
                    ui.separator();
                    ui.label(format!("{} {}", self.locale.text("Generation", "代次"), view.generation));
                    ui.separator();
                    ui.label(format!("{} {}", self.locale.text("Modules", "模块"), view.modules.len()));
                });
                ui.label(format!("{}: {}", self.locale.text("Session", "会话"), view.session_id));
            } else {
                ui.label(self.locale.text("No runtime snapshot.", "暂无运行时快照。"));
                ui.label(self.locale.text("Refresh to request a current authenticated view. Actions requiring that view remain unavailable.", "刷新以获取当前已验证视图。依赖该视图的操作暂不可用。"));
            }
        });
        ui.add_space(12.0);
        theme::card().show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.label(
                egui::RichText::new(self.locale.text("CONNECTION DETAILS", "连接信息"))
                    .small()
                    .color(theme::VIOLET),
            );
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
        });
        if let Some(status) = &self.status_rendered {
            ui.add_space(12.0);
            ui.collapsing(self.locale.text("Snapshot diagnostics", "快照诊断"), |ui| {
                let (mut preview, truncated) = diagnostic_preview(status);
                if truncated {
                    ui.label(egui::RichText::new(self.locale.text("Preview limited to 16 KiB; the complete snapshot remains cached. This preview is not the authority record.", "预览限制为 16 KiB；完整快照仍保留在缓存中。预览不是权限记录。")).color(theme::WARNING));
                }
                ui.add(egui::TextEdit::multiline(&mut preview).font(egui::TextStyle::Monospace).desired_width(f32::INFINITY).desired_rows(12).interactive(false));
            });
        }
    }

    pub(super) fn shell_view(&mut self, ui: &mut egui::Ui) {
        let compact = ui.available_width() < 980.0;
        egui::Panel::top("hepta-native-top")
            .frame(theme::card())
            .show(ui, |ui| self.top_bar(ui));
        if compact {
            egui::Panel::top("hepta-native-navigation-compact").show(ui, |ui| {
                ui.horizontal_wrapped(|ui| self.navigation(ui));
            });
        } else {
            egui::Panel::left("hepta-native-navigation")
                .resizable(false)
                .exact_size(204.0)
                .frame(egui::Frame::new().fill(theme::SURFACE).inner_margin(16))
                .show(ui, |ui| {
                    ui.set_min_width(ui.available_width());
                    ui.add_space(8.0);
                    self.navigation(ui);
                });
        }
        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(theme::BACKGROUND).inner_margin(24))
            .show(ui, |ui| {
                let screen_id = match self.screen {
                    Screen::Runtime => "runtime",
                    Screen::Operations => "operations",
                    Screen::Updates => "updates",
                    Screen::Accessibility => "accessibility",
                };
                egui::ScrollArea::vertical()
                    .id_salt(("native-screen", screen_id))
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        ui.set_min_width(ui.available_width());
                        match self.screen {
                            Screen::Runtime => self.runtime_view(ui),
                            Screen::Operations => self.operations_view(ui),
                            Screen::Updates => self.updates_view(ui),
                            Screen::Accessibility => self.accessibility_view(ui),
                        }
                        ui.add_space(20.0);
                    });
            });
    }
}

#[cfg(test)]
#[path = "shell_view_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "visual_capture_tests.rs"]
mod visual_capture_tests;
