use super::task_supervisor::FileInputTarget;
use super::task_supervisor::accept_active_dropped_file;
use super::task_supervisor::active_file_input;
use super::task_supervisor::arm_file_input;
use super::task_supervisor::cancel_file_input;
use super::*;

impl HeptaNativeApp {
    pub(super) fn handle_file_input_intent(
        &mut self,
        ui: &mut egui::Ui,
    ) -> Option<FileInputTarget> {
        let escape_pressed = ui.ctx().input_mut(|input| {
            input.consume_key(egui::Modifiers::NONE, egui::Key::Escape)
        });
        if escape_pressed {
            if let Some(ticket) = cancel_file_input(ui.ctx()) {
                self.set_file_input_message(
                    ticket.target(),
                    self.locale
                        .text(
                            "File selection cancelled. Any late picker or drop result is stale and will be rejected.",
                            "文件选择已取消。任何迟到的选择器或拖放结果都将被视为过期并拒绝。",
                        )
                        .to_owned(),
                );
                self.last_error = None;
                return None;
            }

            let cancellation = self
                .pending_task
                .as_ref()
                .map(|task| task.worker.cancel_before_admission());
            match cancellation {
                Some(true) => {
                    self.last_error = Some(
                        self.locale
                            .text(
                                "Cancellation won before runtime admission; waiting for the worker to acknowledge the cancelled terminal result.",
                                "取消请求在进入运行时前获胜；正在等待 worker 确认取消终态。",
                            )
                            .to_owned(),
                    );
                }
                Some(false) => {
                    self.last_error = Some(
                        self.locale
                            .text(
                                "The operation is already admitted. Escape did not claim cancellation; the owned worker must finish its durable protocol.",
                                "操作已经进入运行时。Escape 未宣称取消；受管 worker 必须完成其持久化协议。",
                            )
                            .to_owned(),
                    );
                }
                None => {}
            }
        }

        let dropped_files = ui
            .ctx()
            .input(|input| input.raw.dropped_files.clone());
        if dropped_files.is_empty() {
            return None;
        }

        match accept_active_dropped_file(ui.ctx(), &dropped_files) {
            Ok((target, path)) => {
                let rendered_path = path.display().to_string();
                match target {
                    FileInputTarget::OperationGrant => {
                        self.operation_grant_path = rendered_path;
                    }
                    FileInputTarget::UpdateManifest => {
                        self.update_manifest_path = rendered_path;
                    }
                    FileInputTarget::UpdatePackage => {
                        self.update_package_path = rendered_path;
                    }
                }
                self.set_file_input_message(
                    target,
                    self.locale
                        .text(
                            "Bound one absolute filesystem path to the armed target. The operation will reopen and validate the file before admission.",
                            "已将一个绝对文件系统路径绑定到指定目标。操作在准入前仍会重新打开并验证该文件。",
                        )
                        .to_owned(),
                );
                self.last_error = None;
                Some(target)
            }
            Err(error) => {
                self.last_error = Some(error.to_string());
                None
            }
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
                        self.locale.text(
                            "Armed exact file-input target",
                            "已指定精确文件输入目标"
                        ),
                        target.english_name()
                    ),
                );
                self.last_error = None;
            }
            Err(error) => {
                self.last_error = Some(error.to_string());
            }
        }
    }

    pub(super) fn render_file_input_intent_status(&self, ui: &mut egui::Ui) {
        if let Some(ticket) = active_file_input(ui.ctx()) {
            ui.label(format!(
                "{}: {} · {}",
                self.locale
                    .text("Waiting for one dropped file", "正在等待一个拖放文件"),
                ticket.target().english_name(),
                self.locale.text("Escape cancels", "Escape 取消")
            ));
        }
    }

    fn set_file_input_message(&mut self, target: FileInputTarget, message: String) {
        match target {
            FileInputTarget::OperationGrant => self.operation_message = Some(message),
            FileInputTarget::UpdateManifest | FileInputTarget::UpdatePackage => {
                self.update_message = Some(message);
            }
        }
    }

    pub(super) fn updates_view(&mut self, ui: &mut egui::Ui) {
        let focus_target = self.handle_file_input_intent(ui);
        ui.heading(self.locale.text("Signed updates", "签名更新"));
        ui.label(self.locale.text(
            "Only a signed stable-channel manifest can be staged. Activation closes this GUI first, then a separate updater helper re-verifies the manifest, installed predecessor and staged package before replacement.",
            "只有签名的 stable-channel 清单才能进入暂存。激活时先关闭 GUI，再由独立 updater 辅助程序重新验证清单、已安装前任版本和暂存包后执行替换。",
        ));
        ui.separator();
        ui.label(self.locale.text("Signed manifest path", "签名清单路径"));
        let manifest_response = ui
            .horizontal(|ui| {
                let response = ui.text_edit_singleline(&mut self.update_manifest_path);
                if ui
                    .button(
                        self.locale
                            .text("Use next dropped file", "使用下一个拖放文件"),
                    )
                    .clicked()
                {
                    self.arm_file_input_target(ui.ctx(), FileInputTarget::UpdateManifest);
                }
                response
            })
            .inner;
        if focus_target == Some(FileInputTarget::UpdateManifest) {
            manifest_response.request_focus();
        }

        ui.label(self.locale.text("Package path", "更新包路径"));
        let package_response = ui
            .horizontal(|ui| {
                let response = ui.text_edit_singleline(&mut self.update_package_path);
                if ui
                    .button(
                        self.locale
                            .text("Use next dropped file", "使用下一个拖放文件"),
                    )
                    .clicked()
                {
                    self.arm_file_input_target(ui.ctx(), FileInputTarget::UpdatePackage);
                }
                response
            })
            .inner;
        if focus_target == Some(FileInputTarget::UpdatePackage) {
            package_response.request_focus();
        }
        self.render_file_input_intent_status(ui);

        if ui
            .add_enabled(
                !self.is_busy(),
                egui::Button::new(self.locale.text("Verify & stage", "验证并暂存")),
            )
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
        match &self.pending_update {
            Some(pending) => {
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
                        .add_enabled(
                            !self.is_busy(),
                            egui::Button::new(
                                self.locale
                                    .text("Activate on restart & close", "关闭并在重启时激活"),
                            ),
                        )
                        .clicked()
                {
                    self.shutdown.update_requested = true;
                    self.update_message = Some(
                        self.locale
                            .text(
                                "Closing the GUI; the external updater will perform final verification and activation.",
                                "正在关闭 GUI；外部 updater 将执行最终验证与激活。",
                            )
                            .to_owned(),
                    );
                    self.request_shutdown(ui.ctx());
                }
            }
            None => {
                ui.label(self.locale.text("No pending update", "无待处理更新"));
            }
        }
        if let Some(message) = &self.update_message {
            ui.separator();
            ui.label(message);
        }
    }

    fn stage_update(&mut self) {
        let outcome = (|| -> Result<(PathBuf, PathBuf), ShellError> {
            let manifest_path = PathBuf::from(self.update_manifest_path.trim());
            let package_path = PathBuf::from(self.update_package_path.trim());
            if !manifest_path.is_absolute() || !package_path.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "update manifest and package paths must be absolute".to_owned(),
                ));
            }
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

    pub(super) fn accessibility_view(&self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Accessibility & input", "无障碍与输入"));
        ui.label(self.locale.text(
            "The selected native framework is eframe/egui with AccessKit enabled. Windows, macOS and Linux are first-class build targets. Native DPI scaling is delegated to winit/eframe.",
            "选定的原生框架为 eframe/egui，并启用 AccessKit。Windows、macOS、Linux 均为一等构建目标；原生 DPI 缩放交由 winit/eframe 处理。",
        ));
        ui.separator();
        ui.label(self.locale.text(
            "Keyboard focus follows egui's native focus order. Use Tab/Shift+Tab to move between controls, Enter/Space to activate focused buttons, and Escape to cancel only an armed file input or a task that has not crossed runtime admission.",
            "键盘焦点遵循 egui 原生焦点顺序。使用 Tab/Shift+Tab 切换控件，Enter/Space 激活当前按钮；Escape 仅取消已指定的文件输入，或尚未跨过运行时准入点的任务。",
        ));
        ui.label(self.locale.text(
            "File drag/drop is accepted only after arming one exact target. Exactly one absolute filesystem path is consumed; URI-only, in-memory, multi-file, stale and wrong-target results are rejected.",
            "文件拖放仅在指定一个精确目标后接受。系统只消费一个绝对文件路径；URI-only、内存、多文件、过期和错误目标结果都会被拒绝。",
        ));
        ui.label(self.locale.text(
            "Locale selection currently follows LC_ALL/LC_MESSAGES/LANG and includes English and Chinese shell strings.",
            "当前区域设置依据 LC_ALL/LC_MESSAGES/LANG，壳层字符串支持英文与中文。",
        ));
    }
}
