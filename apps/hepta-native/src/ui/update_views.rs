use super::task_supervisor::FileInputTarget;
use super::task_supervisor::FileInputTicket;
use super::task_supervisor::accept_active_dropped_file;
use super::task_supervisor::accept_file_input_result;
use super::task_supervisor::active_file_input;
use super::task_supervisor::arm_file_input;
use super::task_supervisor::cancel_file_input;
use super::*;

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
            } else if let Some(task) = self
                .pending_read
                .as_ref()
                .or(self.pending_runtime.as_ref())
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
        let path = path.display().to_string();
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
        let focus_target = self.handle_file_input_intent(ui);
        ui.heading(self.locale.text("Signed updates", "签名更新"));
        ui.label(self.locale.text(
            "Only a signed stable-channel manifest can be staged. Activation closes this GUI first; the independent helper re-verifies the manifest, predecessor and staged package.",
            "只有签名的 stable-channel 清单才能暂存。激活先关闭 GUI；独立助手重新验证清单、前任版本和暂存包。",
        ));
        ui.separator();
        ui.label(self.locale.text("Signed manifest path", "签名清单路径"));
        let response = ui
            .horizontal(|ui| {
                let response = ui.text_edit_singleline(&mut self.update_manifest_path);
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(self.locale.text("Choose file", "选择文件")),
                    )
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
        ui.label(self.locale.text("Package path", "更新包路径"));
        let response = ui
            .horizontal(|ui| {
                let response = ui.text_edit_singleline(&mut self.update_package_path);
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(self.locale.text("Choose file", "选择文件")),
                    )
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
                    "update manifest and package paths must be absolute".into(),
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
            "eframe/egui with AccessKit is selected for Windows, macOS and Linux. DPI scaling is delegated to winit/eframe.",
            "Windows、macOS、Linux 使用启用 AccessKit 的 eframe/egui，DPI 缩放由 winit/eframe 处理。",
        ));
        ui.separator();
        ui.label(self.locale.text(
            "Tab/Shift+Tab traverses controls; Enter/Space activates buttons. Escape cancels an input intent or a task before admission, not admitted work.",
            "Tab/Shift+Tab 切换控件，Enter/Space 激活按钮。Escape 取消输入意图或准入前任务，不撤销已准入工作。",
        ));
        ui.label(self.locale.text(
            "Choose file uses XDG Desktop Portal by default on Linux; Zenity is an explicit compatibility backend. Exact tickets reject stale callbacks. A selected path is not an OS resource capability.",
            "Linux 的“选择文件”默认使用 XDG Desktop Portal；Zenity 仅作为显式兼容后端。精确票据拒绝过期回调。所选路径不是 OS 资源能力。",
        ));
        ui.label(self.locale.text(
            "Picker, persistent history read and single mutation owner lanes are separate. Shutdown still owns and joins every admitted worker before update activation.",
            "文件选择、持久历史读取与单一 mutation owner 分属独立 lane。关机仍会持有并等待所有已准入 worker，之后才允许更新激活。",
        ));
        ui.label(self.locale.text(
            "English/Chinese strings follow LC_ALL/LC_MESSAGES/LANG. Physical screen-reader, IME, focus and mixed-DPI acceptance require separate evidence.",
            "中英文字符串依据 LC_ALL/LC_MESSAGES/LANG。真实屏幕阅读器、输入法、焦点和混合 DPI 验收需独立证据。",
        ));
    }
}
