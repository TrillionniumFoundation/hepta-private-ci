use super::task_supervisor::FileInputTarget;
use super::task_supervisor::FileInputTicket;
use super::task_supervisor::accept_active_dropped_file;
use super::task_supervisor::accept_file_input_result;
use super::task_supervisor::active_file_input;
use super::task_supervisor::arm_file_input;
use super::task_supervisor::cancel_file_input;
use super::*;

/// Reveal newly keyboard-focused form controls within their owning scroll area.
/// Applying this to form responses keeps sidebar focus from moving the workspace.
pub(super) trait FocusReveal {
    fn reveal_focus(self) -> Self;
}

impl FocusReveal for egui::Response {
    fn reveal_focus(self) -> Self {
        if self.gained_focus() && !self.interact_rect.contains_rect(self.rect) {
            self.scroll_to_me(Some(egui::Align::Center));
        }
        self
    }
}

impl HeptaNativeApp {
    pub(super) fn handle_file_input_intent(
        &mut self,
        ui: &mut egui::Ui,
    ) -> Option<FileInputTarget> {
        let accepted_focus = self.file_input_focus.take();
        let escape = ui
            .ctx()
            .input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Escape));
        if escape {
            if let Some(ticket) = cancel_file_input(ui.ctx()) {
                if let Some(task) = self.pending_picker.as_ref() {
                    task.worker.cancel_before_admission();
                }
                self.set_file_input_message(
                    ticket.target(),
                    self.locale
                        .text(
                            "Selection cancelled; late callbacks are stale.",
                            "选择已取消；迟到的回调将被拒绝。",
                        )
                        .into(),
                );
                self.last_error = None;
                return None;
            }
            if let Some(task) = self.pending_picker.as_ref() {
                let cancelled = task.worker.cancel_before_admission();
                self.last_error = Some(
                    if cancelled {
                        self.locale.text(
                            "Picker cancelled before admission; waiting for acknowledgement.",
                            "文件选择器已在准入前取消；正在等待确认。",
                        )
                    } else {
                        self.locale.text(
                            "Picker already admitted: the owned dialog must finish or time out.",
                            "文件选择器已准入：受控对话框必须完成或超时。",
                        )
                    }
                    .into(),
                );
            } else if let Some(task) = self.pending_read.as_ref().or(self.pending_runtime.as_ref())
            {
                let cancelled = task.worker.cancel_before_admission();
                self.last_error = Some(
                    if cancelled {
                        self.locale.text(
                            "Cancelled before admission; waiting for the worker acknowledgement.",
                            "已在准入前取消；等待 worker 确认。",
                        )
                    } else {
                        self.locale.text(
                            "Already admitted: the owned worker must finish; Escape did not undo it.",
                            "任务已准入，worker 必须完成；Escape 不会撤销任务。",
                        )
                    }
                    .into(),
                );
            }
        }
        let files = ui.ctx().input(|input| input.raw.dropped_files.clone());
        if files.is_empty() {
            return accepted_focus;
        }
        match accept_active_dropped_file(ui.ctx(), &files) {
            Ok((target, path)) => {
                if let Some(task) = self.pending_picker.as_ref() {
                    task.worker.cancel_before_admission();
                }
                self.install_file_input_path(target, path);
                self.last_error = None;
                Some(target)
            }
            Err(error) => {
                self.last_error = Some(error.to_string());
                None
            }
        }
    }

    fn install_file_input_path(&mut self, target: FileInputTarget, path: PathBuf) {
        // Both picker and drop acceptance validate representability before
        // consuming the intent. Never turn an OS path into a different name.
        let Some(path) = path.to_str() else {
            self.last_error = Some("file input path is not representable as UTF-8".into());
            return;
        };
        let path = path.to_owned();
        match target {
            FileInputTarget::OperationGrant => self.operation_grant_path = path,
            FileInputTarget::UpdateManifest => self.update_manifest_path = path,
            FileInputTarget::UpdatePackage => self.update_package_path = path,
        }
        self.set_file_input_message(
            target,
            self.locale
                .text(
                    "One absolute path is bound to the exact target. It will be reopened and validated; selection is not authority.",
                    "一个绝对路径已绑定到精确目标。准入前仍会重新打开并验证；选择文件不构成执行授权。",
                )
                .into(),
        );
    }

    pub(super) fn finish_picker_result(
        &mut self,
        context: &egui::Context,
        ticket: FileInputTicket,
        path: Option<PathBuf>,
    ) {
        if self.shutdown.requested() {
            if active_file_input(context) == Some(ticket) {
                cancel_file_input(context);
            }
            return;
        }
        let Some(path) = path else {
            if active_file_input(context) == Some(ticket) {
                cancel_file_input(context);
                self.set_file_input_message(
                    ticket.target(),
                    self.locale
                        .text("File selection cancelled.", "文件选择已取消。")
                        .into(),
                );
            }
            return;
        };
        match accept_file_input_result(context, ticket, ticket.target(), &[Some(path)]) {
            Ok(path) => {
                self.install_file_input_path(ticket.target(), path);
                self.file_input_focus = Some(ticket.target());
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(error.to_string()),
        }
    }

    pub(super) fn pick_file_input_target(
        &mut self,
        context: &egui::Context,
        target: FileInputTarget,
    ) {
        if self.picker_busy() {
            return;
        }
        let ticket = match arm_file_input(context, target) {
            Ok(ticket) => ticket,
            Err(error) => {
                self.last_error = Some(error.to_string());
                return;
            }
        };
        self.start_picker_task(move |admission| {
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            Ok(UiTaskOutput::PickedFile {
                ticket,
                path: super::native_picker::choose_file()?,
            })
        });
        if self.pending_picker.is_none() && active_file_input(context) == Some(ticket) {
            cancel_file_input(context);
        }
    }

    pub(super) fn arm_file_input_target(
        &mut self,
        context: &egui::Context,
        target: FileInputTarget,
    ) {
        match arm_file_input(context, target) {
            Ok(_) => {
                self.set_file_input_message(
                    target,
                    format!(
                        "{}: {}",
                        self.locale
                            .text("Armed exact file-input target", "已指定精确文件输入目标"),
                        target.english_name()
                    ),
                );
                self.last_error = None;
            }
            Err(error) => self.last_error = Some(error.to_string()),
        }
    }

    pub(super) fn render_file_input_intent_status(&self, ui: &mut egui::Ui) {
        if let Some(ticket) = active_file_input(ui.ctx()) {
            ui.label(format!(
                "{}: {} · {}",
                self.locale
                    .text("Waiting for one selected file", "正在等待一个所选文件"),
                ticket.target().english_name(),
                self.locale
                    .text("Escape cancels the intent", "Escape 取消输入意图")
            ));
        } else if self.picker_busy() {
            ui.colored_label(theme::AMBER, self.locale.text("File selection is busy. Finish the current dialog, or wait for cancellation or shutdown to complete.", "文件选择正忙。请完成当前对话框，或等待取消或关闭过程完成。"));
        }
    }

    fn set_file_input_message(&mut self, target: FileInputTarget, message: String) {
        match target {
            FileInputTarget::OperationGrant => self.operation_message = Some(message),
            FileInputTarget::UpdateManifest | FileInputTarget::UpdatePackage => {
                self.update_message = Some(message)
            }
        }
    }

    pub(super) fn updates_view(&mut self, ui: &mut egui::Ui) {
        let focus_target = self.file_input_focus.take();
        ui.heading(self.locale.text("Signed updates", "签名更新"));
        ui.label(self.locale.text(
            "Verify a signed stable-channel package, then activate it after a safe shutdown.",
            "验证签名的稳定通道更新包，再于安全关闭后激活。",
        ));
        ui.separator();
        theme::eyebrow(
            ui,
            self.locale
                .text("01 / SELECT UPDATE FILES", "01 / 选择更新文件"),
        );
        let label = ui.label(self.locale.text("Signed manifest path", "签名清单路径"));
        let response = ui
            .horizontal_wrapped(|ui| {
                let response = ui
                    .add(
                        egui::TextEdit::singleline(&mut self.update_manifest_path)
                            .min_size(egui::vec2(0.0, 34.0))
                            .id(egui::Id::new("native-update-manifest"))
                            .desired_width(ui.available_width().min(480.0))
                            .hint_text(self.locale.text("Absolute file path", "文件绝对路径"))
                            .char_limit(crate::model::MAX_NATIVE_PATH_BYTES),
                    )
                    .labelled_by(label.id)
                    .reveal_focus();
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(self.locale.text("Choose file", "选择文件")),
                    )
                    .on_disabled_hover_text(self.locale.text(
                        "Finish or cancel the current file selection first.",
                        "请先完成或取消当前文件选择。",
                    ))
                    .reveal_focus()
                    .clicked()
                {
                    self.pick_file_input_target(ui.ctx(), FileInputTarget::UpdateManifest);
                }
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(
                            self.locale
                                .text("Use next dropped file", "使用下一个拖放文件"),
                        ),
                    )
                    .on_disabled_hover_text(self.locale.text(
                        "Finish or cancel the current file selection first.",
                        "请先完成或取消当前文件选择。",
                    ))
                    .reveal_focus()
                    .clicked()
                {
                    self.arm_file_input_target(ui.ctx(), FileInputTarget::UpdateManifest);
                }
                response
            })
            .inner;
        if focus_target == Some(FileInputTarget::UpdateManifest) {
            response.request_focus();
        }
        response.reveal_focus();
        let label = ui.label(self.locale.text("Package path", "更新包路径"));
        let response = ui
            .horizontal_wrapped(|ui| {
                let response = ui
                    .add(
                        egui::TextEdit::singleline(&mut self.update_package_path)
                            .min_size(egui::vec2(0.0, 34.0))
                            .id(egui::Id::new("native-update-package"))
                            .desired_width(ui.available_width().min(480.0))
                            .hint_text(self.locale.text("Absolute file path", "文件绝对路径"))
                            .char_limit(crate::model::MAX_NATIVE_PATH_BYTES),
                    )
                    .labelled_by(label.id)
                    .reveal_focus();
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(self.locale.text("Choose file", "选择文件")),
                    )
                    .on_disabled_hover_text(self.locale.text(
                        "Finish or cancel the current file selection first.",
                        "请先完成或取消当前文件选择。",
                    ))
                    .reveal_focus()
                    .clicked()
                {
                    self.pick_file_input_target(ui.ctx(), FileInputTarget::UpdatePackage);
                }
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(
                            self.locale
                                .text("Use next dropped file", "使用下一个拖放文件"),
                        ),
                    )
                    .on_disabled_hover_text(self.locale.text(
                        "Finish or cancel the current file selection first.",
                        "请先完成或取消当前文件选择。",
                    ))
                    .reveal_focus()
                    .clicked()
                {
                    self.arm_file_input_target(ui.ctx(), FileInputTarget::UpdatePackage);
                }
                response
            })
            .inner;
        if focus_target == Some(FileInputTarget::UpdatePackage) {
            response.request_focus();
        }
        response.reveal_focus();
        self.render_file_input_intent_status(ui);
        ui.separator();
        theme::eyebrow(
            ui,
            self.locale.text("02 / VERIFY & STAGE", "02 / 验证并暂存"),
        );
        ui.label(self.locale.text(
            "Signature, compatibility and package integrity are checked before staging.",
            "暂存前将检查签名、兼容性与更新包完整性。",
        ));
        let blocked = if self.is_busy() {
            Some(self.locale.text(
                "Wait for the current task to finish.",
                "请等待当前任务完成。",
            ))
        } else if super::path_input::absolute_path(&self.update_manifest_path).is_err()
            || super::path_input::absolute_path(&self.update_package_path).is_err()
        {
            Some(self.locale.text(
                "Choose both files or enter their absolute paths.",
                "请选择两个文件，或输入它们的绝对路径。",
            ))
        } else {
            None
        };
        if let Some(reason) = blocked {
            ui.colored_label(theme::AMBER, reason);
        }
        if ui
            .add_enabled(
                blocked.is_none(),
                egui::Button::new(self.locale.text("Verify & stage", "验证并暂存")),
            )
            .on_disabled_hover_text(blocked.unwrap_or_default())
            .reveal_focus()
            .clicked()
        {
            self.stage_update();
        }
        ui.separator();
        theme::eyebrow(ui, self.locale.text("03 / ACTIVATION", "03 / 激活更新"));
        match &self.pending_update {
            Some(pending) => {
                ui.strong(match pending.status {
                    PendingUpdateStatus::Staged => self
                        .locale
                        .text("Staged · ready for activation", "已暂存 · 可激活"),
                    PendingUpdateStatus::ActivationStarted => self.locale.text(
                        "Activation started · completion unconfirmed",
                        "已开始激活 · 尚未确认完成",
                    ),
                    PendingUpdateStatus::ActivatedUnconfirmed => self.locale.text(
                        "Activated · waiting for readiness confirmation",
                        "已激活 · 等待就绪确认",
                    ),
                    PendingUpdateStatus::RollbackStarted => self.locale.text(
                        "Rollback started · completion unconfirmed",
                        "已开始回滚 · 尚未确认完成",
                    ),
                    PendingUpdateStatus::RolledBack => self
                        .locale
                        .text("Rolled back to the previous version", "已回滚至前一版本"),
                    PendingUpdateStatus::RecoveryRequired => self.locale.text(
                        "Recovery required · inspect the recorded reason",
                        "需要恢复 · 请检查记录的原因",
                    ),
                    PendingUpdateStatus::Confirmed => self.locale.text(
                        "Confirmed · verified GUI readiness recorded",
                        "已确认 · 已记录通过验证的界面就绪状态",
                    ),
                });
                if let Some(reason) = &pending.recovery_reason {
                    ui.colored_label(theme::AMBER, reason);
                }
                if pending.status == PendingUpdateStatus::Staged {
                    ui.label(self.locale.text("Activation closes this app. The independent helper re-verifies the manifest, predecessor and staged package before replacement.", "激活将关闭此应用。独立助手将在替换前重新验证清单、前一版本与暂存包。"));
                }
                ui.collapsing(
                    self.locale
                        .text("Update integrity details", "更新完整性详情"),
                    |ui| {
                        ui.label(format!(
                            "{}: {}",
                            self.locale.text("Package digest", "包摘要"),
                            pending.manifest.package_digest
                        ));
                        ui.label(format!(
                            "{} / {}",
                            pending.manifest.platform, pending.manifest.architecture
                        ));
                    },
                );
                if pending.status == PendingUpdateStatus::Staged
                    && ui
                        .add_enabled(
                            !self.is_busy(),
                            egui::Button::new(
                                self.locale
                                    .text("Activate on restart & close", "关闭并在重启时激活"),
                            ),
                        )
                        .on_disabled_hover_text(self.locale.text(
                            "Wait for the current task to finish before closing.",
                            "请等待当前任务完成，再关闭应用。",
                        ))
                        .reveal_focus()
                        .clicked()
                {
                    self.shutdown.update_requested = true;
                    self.update_message = Some(
                        self.locale
                            .text(
                                "Closing safely before independent activation.",
                                "正在安全关闭，随后由独立助手激活。",
                            )
                            .into(),
                    );
                    self.request_shutdown(ui.ctx());
                }
            }
            None => {
                ui.label(self.locale.text("No pending update", "无待处理更新"));
            }
        }
        ui.collapsing(
            self.locale
                .text("Pending record location", "待处理记录位置"),
            |ui| {
                ui.label(format!(
                    "{}: {}",
                    self.locale.text("Pending record", "待处理记录"),
                    self.pending_update_path.display()
                ));
            },
        );
        if let Some(message) = &self.update_message {
            ui.separator();
            ui.label(message);
        }
    }

    fn stage_update(&mut self) {
        let outcome = (|| -> Result<(PathBuf, PathBuf), ShellError> {
            let manifest_path = super::path_input::absolute_path(&self.update_manifest_path)?;
            let package_path = super::path_input::absolute_path(&self.update_package_path)?;
            Ok((manifest_path, package_path))
        })();
        match outcome {
            Ok((manifest_path, package_path)) => {
                let updater = self.updater.clone();
                let protocol_version = self.manifest.protocol_version;
                self.update_message = None;
                self.start_task(UiTaskKind::StageUpdate, move |admission| {
                    let manifest: SignedUpdateManifestV1 =
                        crate::file_input::read_json_file(&manifest_path, 64 * 1024)?;
                    admission
                        .begin()
                        .map_err(|message| ShellError::State(message.to_owned()))?;
                    let pending =
                        updater.verify_and_stage(manifest, &package_path, protocol_version)?;
                    let message = format!(
                        "staged {} for {}/{}",
                        pending.manifest.package_digest,
                        pending.manifest.platform,
                        pending.manifest.architecture
                    );
                    Ok(UiTaskOutput::StageUpdate {
                        message,
                        pending: Box::new(pending),
                    })
                });
            }
            Err(error) => {
                self.update_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }

    pub(super) fn accessibility_view(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Accessibility & input", "无障碍与输入"));
        ui.label(self.locale.text(
            "Adjust this workspace for comfortable reading and keyboard navigation.",
            "调整工作区，让阅读与键盘导航更舒适。",
        ));
        ui.separator();
        theme::eyebrow(ui, self.locale.text("READING PREFERENCES", "阅读偏好"));
        ui.label(self.locale.text("Interface size", "界面大小"));
        ui.horizontal_wrapped(|ui| {
            let current = ui.ctx().zoom_factor();
            for (label, zoom) in [("100%", 1.0), ("125%", 1.25), ("150%", 1.5)] {
                if ui
                    .selectable_label((current - zoom).abs() < 0.01, label)
                    .reveal_focus()
                    .clicked()
                {
                    ui.ctx().set_zoom_factor(zoom);
                }
            }
        });
        ui.label(self.locale.text("Interface language", "界面语言"));
        ui.horizontal_wrapped(|ui| {
            ui.selectable_value(&mut self.locale, Locale::English, "English")
                .reveal_focus();
            ui.selectable_value(&mut self.locale, Locale::Chinese, "中文")
                .reveal_focus();
        });
        ui.label(self.locale.text(
            "Language applies to this session; startup follows the system locale.",
            "语言选项适用于本次会话；启动时遵循系统语言。",
        ));
        ui.separator();
        theme::eyebrow(
            ui,
            self.locale.text("KEYBOARD & FILE INPUT", "键盘与文件输入"),
        );
        for (english, chinese) in [
            (
                "Tab / Shift+Tab · move between controls",
                "Tab / Shift+Tab · 切换控件",
            ),
            (
                "Enter / Space · activate focused buttons",
                "Enter / Space · 激活已聚焦按钮",
            ),
            (
                "Escape · cancel file selection or work before admission",
                "Escape · 取消文件选择或准入前的任务",
            ),
            (
                "Already admitted work must finish; Escape does not undo it.",
                "已准入的任务必须完成；Escape 不会撤销它。",
            ),
            (
                "Choose a file, or arm a specific field before dropping one file.",
                "选择文件，或先指定目标输入框，再拖入一个文件。",
            ),
        ] {
            ui.label(self.locale.text(english, chinese));
        }
        ui.separator();
        ui.collapsing(self.locale.text("Platform support & verification limits", "平台支持与验证边界"), |ui| {
            ui.label(self.locale.text(
                "eframe/egui with AccessKit is selected for Windows, macOS and Linux. DPI scaling is delegated to winit/eframe.",
                "Windows、macOS、Linux 使用启用 AccessKit 的 eframe/egui，DPI 缩放由 winit/eframe 处理。",
            ));
            ui.label(self.locale.text(
                "File selection uses native Rust adapters: XDG Desktop Portal on Linux and system dialogs on macOS/Windows. Script and Zenity backends are retired. A selected path is not authority.",
                "文件选择使用原生 Rust 适配器：Linux 使用 XDG Desktop Portal，macOS/Windows 使用系统对话框。脚本与 Zenity 后端已退役。选择路径不构成授权。",
            ));
            ui.label(self.locale.text(
                "Physical screen-reader, IME, focus and mixed-DPI acceptance require separate evidence.",
                "真实屏幕阅读器、输入法、焦点和混合 DPI 验收需独立证据。",
            ));
        });
    }
}

#[cfg(test)]
#[path = "form_interaction_tests.rs"]
mod tests;
