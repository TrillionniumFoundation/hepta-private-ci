//! Presentation of the existing native owner; no synthesized runtime telemetry.
use super::theme;
use super::*;

impl HeptaNativeApp {
    pub(super) fn top_bar(&mut self, ui: &mut egui::Ui) {
        let busy = self.runtime_busy();
        ui.horizontal_wrapped(|ui| {
            let (mark, _) = ui.allocate_exact_size(egui::vec2(28.0, 28.0), egui::Sense::hover());
            let vertices = (0..7)
                .map(|index| {
                    let angle =
                        std::f32::consts::TAU * index as f32 / 7.0 - std::f32::consts::FRAC_PI_2;
                    mark.center() + egui::vec2(angle.cos(), angle.sin()) * 12.0
                })
                .collect();
            ui.painter().add(egui::Shape::closed_line(
                vertices,
                egui::Stroke::new(1.5, theme::CYAN),
            ));
            ui.painter().line_segment(
                [
                    mark.center() - egui::vec2(5.0, 0.0),
                    mark.center() + egui::vec2(5.0, 0.0),
                ],
                egui::Stroke::new(1.0, theme::CYAN),
            );
            ui.label(
                egui::RichText::new("HEPTA")
                    .size(22.0)
                    .strong()
                    .color(theme::TEXT),
            );
            ui.label(
                egui::RichText::new("/ NATIVE")
                    .monospace()
                    .color(theme::MUTED),
            );
            ui.separator();
            let verifying = self
                .pending_runtime
                .as_ref()
                .is_some_and(|task| task.kind == UiTaskKind::Refresh);
            let (state, color) = if verifying {
                (
                    self.locale
                        .text("Verifying runtime view", "正在验证运行时视图"),
                    theme::AMBER,
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
                    theme::AMBER,
                )
            };
            ui.label(egui::RichText::new(state).color(color));
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(if self.view_revision.is_some() {
                        self.locale.text("Refresh", "刷新")
                    } else {
                        self.locale.text("Verify snapshot", "验证快照")
                    }),
                )
                .on_disabled_hover_text(self.locale.text(
                    "Wait for the admitted runtime task to finish.",
                    "请等待已准入运行时任务完成。",
                ))
                .clicked()
            {
                self.refresh();
            }
            if ui
                .add_enabled(
                    !busy,
                    egui::Button::new(self.locale.text("Reconcile", "对账")),
                )
                .on_hover_text(self.locale.text(
                    "Observe pending effects; never replay them.",
                    "观察待定效果；绝不重放。",
                ))
                .clicked()
            {
                self.reconcile();
            }
        });
        for task in [
            self.pending_runtime.as_ref(),
            self.pending_read.as_ref(),
            self.pending_picker.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            // A static status instead of perpetual decorative motion. The worker
            // still requests repaint on completion and owns its cancellation.
            ui.label(egui::RichText::new(task.kind.label(self.locale)).color(theme::AMBER));
        }
        if let Some(error) = &self.last_error {
            egui::Frame::new()
                .fill(egui::Color32::from_rgb(51, 28, 37))
                .inner_margin(10)
                .show(ui, |ui| {
                    ui.label(
                        egui::RichText::new(
                            self.locale.text("ACTION NEEDS ATTENTION", "操作需要处理"),
                        )
                        .strong()
                        .color(theme::ERROR),
                    );
                    let end = error.floor_char_boundary(error.len().min(2048));
                    egui::ScrollArea::vertical()
                        .id_salt("native-error-details")
                        .max_height(96.0)
                        .show(ui, |ui| {
                            ui.add(egui::Label::new(&error[..end]).wrap());
                        });
                    if end < error.len() {
                        ui.label(
                            self.locale
                                .text("Error detail preview truncated.", "错误详情预览已截断。"),
                        );
                    }
                });
        }
    }

    pub(super) fn navigation(&mut self, ui: &mut egui::Ui) {
        theme::eyebrow(ui, self.locale.text("WORKSPACE", "工作区"));
        for (screen, index, en, zh) in [
            (Screen::Runtime, "01", "Runtime", "运行时"),
            (Screen::Operations, "02", "Operations", "操作"),
            (Screen::Updates, "03", "Updates", "更新"),
            (Screen::Accessibility, "04", "Accessibility", "无障碍"),
        ] {
            let label = format!("{index}   {}", self.locale.text(en, zh));
            if ui
                .add_sized(
                    [ui.available_width(), 42.0],
                    egui::Button::new(label).selected(self.screen == screen),
                )
                .clicked()
            {
                self.select_screen(ui.ctx(), screen);
            }
        }
        ui.add_space(22.0);
        ui.separator();
        theme::eyebrow(ui, self.locale.text("LOCAL ENDPOINT", "本地端点"));
        ui.label(egui::RichText::new(&self.manifest.address).monospace());
        ui.label(
            egui::RichText::new(format!(
                "{} / {}",
                std::env::consts::OS,
                std::env::consts::ARCH
            ))
            .small()
            .color(theme::MUTED),
        );
        ui.add_space(12.0);
        ui.label(
            egui::RichText::new(self.locale.text(
                "Presentation only. Authority stays with the independent owner.",
                "仅呈现状态。权限由独立所有者掌握。",
            ))
            .small()
            .color(theme::MUTED),
        );
    }

    fn select_screen(&mut self, context: &egui::Context, screen: Screen) {
        if self.screen != screen {
            task_supervisor::cancel_file_input(context);
            self.file_input_focus = None;
            self.screen = screen;
        }
    }

    pub(super) fn workspace_view(&mut self, ui: &mut egui::Ui) {
        egui::Panel::top("hepta-native-top")
            .frame(egui::Frame::new().fill(theme::SURFACE).inner_margin(16))
            .show(ui, |ui| self.top_bar(ui));
        if ui.available_width() >= 850.0 {
            egui::Panel::left("hepta-native-navigation")
                .resizable(false)
                .default_size(210.0)
                .frame(egui::Frame::new().fill(theme::BACKGROUND).inner_margin(18))
                .show(ui, |ui| self.navigation(ui));
        } else {
            egui::Panel::top("hepta-native-compact-navigation").show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
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
                            self.select_screen(ui.ctx(), screen);
                        }
                    }
                });
            });
        }
        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(theme::BACKGROUND).inner_margin(24))
            .show(ui, |ui| {
                let background = ui.available_rect_before_wrap();
                let grid =
                    egui::Stroke::new(1.0, egui::Color32::from_rgba_unmultiplied(111, 223, 229, 9));
                for column in 0..((background.width() / 48.0).ceil() as usize).min(128) {
                    let x = background.left() + column as f32 * 48.0;
                    ui.painter().line_segment(
                        [
                            egui::pos2(x, background.top()),
                            egui::pos2(x, background.bottom()),
                        ],
                        grid,
                    );
                }
                for row in 0..((background.height() / 48.0).ceil() as usize).min(128) {
                    let y = background.top() + row as f32 * 48.0;
                    ui.painter().line_segment(
                        [
                            egui::pos2(background.left(), y),
                            egui::pos2(background.right(), y),
                        ],
                        grid,
                    );
                }
                egui::ScrollArea::vertical()
                    .id_salt(("native-screen", self.screen))
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        ui.set_width(ui.available_width());
                        match self.screen {
                            Screen::Runtime => self.runtime_view(ui),
                            Screen::Operations => self.operations_view(ui),
                            Screen::Updates => self.updates_view(ui),
                            Screen::Accessibility => self.accessibility_view(ui),
                        }
                    });
            });
    }

    pub(super) fn runtime_view(&mut self, ui: &mut egui::Ui) {
        theme::eyebrow(
            ui,
            self.locale
                .text("01 / RUNTIME OBSERVATORY", "01 / 运行时观察台"),
        );
        ui.heading(self.locale.text("Runtime overview", "运行时总览"));
        ui.label(
            egui::RichText::new(self.locale.text(
                "A verified snapshot, not a live-health or execution guarantee.",
                "经验证的状态快照，不代表实时健康状态或执行保证。",
            ))
            .color(theme::MUTED),
        );
        ui.add_space(12.0);
        let view = self
            .control_projection
            .as_ref()
            .map(|projection| &projection.observation)
            .filter(|_| self.connected && self.view_revision.is_some());
        let items = [
            (
                self.locale.text("VIEW REVISION", "视图修订"),
                view.map(|v| v.revision.to_string())
                    .unwrap_or_else(|| "—".into()),
            ),
            (
                self.locale.text("SESSION GENERATION", "会话代次"),
                view.map(|v| v.session_generation.to_string())
                    .unwrap_or_else(|| "—".into()),
            ),
            (
                self.locale.text("DECLARED MODULES", "声明模块"),
                view.map(|v| v.modules.len().to_string())
                    .unwrap_or_else(|| "—".into()),
            ),
        ];
        let longest_value = items
            .iter()
            .map(|(_, value)| value.chars().count())
            .max()
            .unwrap_or(1);
        // Valid u64 counters have up to 20 digits; choose layout from actual
        // content instead of allowing large identities to overflow a small card.
        let metric_width = (longest_value as f32 * 18.0 + 40.0).max(198.0);
        let columns = if ui.available_width() >= metric_width * 3.0 + 24.0 {
            3
        } else {
            1
        };
        ui.columns(columns, |uis| {
            for (index, (label, value)) in items.iter().enumerate() {
                theme::card().show(&mut uis[index % columns], |ui| {
                    ui.set_width(ui.available_width());
                    ui.label(egui::RichText::new(*label).small().color(theme::MUTED));
                    ui.label(
                        egui::RichText::new(value)
                            .size(30.0)
                            .monospace()
                            .color(theme::CYAN),
                    );
                });
            }
        });
        ui.add_space(16.0);
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            theme::eyebrow(ui, self.locale.text("SESSION / TRUST BOUNDARY", "会话 / 信任边界"));
            if let Some(view) = view {
                ui.label(egui::RichText::new(&view.session_id).size(19.0).strong());
                ui.label(self.locale.text("This view authorizes no effect. Each operation requires its own signed final-use grant.", "此视图不授权任何效果。每个操作仍需独立签名的 final-use grant。"));
                if !view.modules.is_empty() {
                    ui.add_space(8.0);
                    ui.horizontal_wrapped(|ui| {
                        for module in view.modules.iter().take(40) {
                            ui.add(egui::Label::new(egui::RichText::new(module).monospace().color(theme::MUTED)).wrap());
                        }
                    });
                    if view.modules.len() > 40 {
                        ui.label(format!("{} / {} {}", 40, view.modules.len(), self.locale.text("module names shown; inspect diagnostics for the full snapshot.", "个模块名称已展示；完整快照请查看诊断。")));
                    }
                }
            } else {
                ui.label(egui::RichText::new(self.locale.text("Waiting for a verified snapshot", "等待已验证快照")).size(20.0).color(theme::AMBER));
                ui.label(self.locale.text("Choose Verify snapshot in the toolbar. Operations stay unavailable until the runtime view is verified.", "请在工具栏选择“验证快照”。运行时视图验证成功前，操作保持不可用。"));
            }
        });
        ui.add_space(12.0);
        ui.label(
            egui::RichText::new(
                self.locale
                    .text("Runtime control: read-only gateway", "运行时控制：只读网关"),
            )
            .color(theme::MUTED),
        );
        ui.label(egui::RichText::new(self.locale.text("Start/stop and other runtime writes are unavailable here. Native operations still require their independent signed grants.", "此处不提供启动、停止等运行时写入。原生操作仍需要独立签名授权。")).small().color(theme::MUTED));
        ui.add_space(16.0);
        if let Some(pretty) = self.status_rendered.as_mut() {
            egui::CollapsingHeader::new(self.locale.text("Preview authenticated diagnostics (JSON)", "预览已验证诊断（JSON）")).id_salt("native-runtime-diagnostics").show(ui, |ui| {
                // A valid multi-megabyte wire response must not turn one expanded
                // diagnostic into an unbounded text-layout job on the GUI thread.
                let end = pretty.floor_char_boundary(pretty.len().min(16 * 1024));
                if end < pretty.len() {
                    ui.label(self.locale.text("Preview limited to 16 KiB; the complete snapshot remains with the runtime owner.", "预览限制为 16 KiB；完整快照仍由运行时所有者保留。"));
                }
                let mut preview = &pretty[..end];
                egui::ScrollArea::both().max_height(320.0).id_salt("native-runtime-json").show(ui, |ui| {
                    ui.add(egui::TextEdit::multiline(&mut preview).font(egui::TextStyle::Monospace).desired_rows(12).desired_width(ui.available_width()).interactive(false));
                });
            });
        }
    }
}
