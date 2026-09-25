use super::*;

impl HeptaNativeApp {
    pub(super) fn updates_view(&mut self, ui: &mut egui::Ui) {
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
        let outcome = (|| -> Result<(SignedUpdateManifestV1, PathBuf), ShellError> {
            let manifest_path = PathBuf::from(self.update_manifest_path.trim());
            let package_path = PathBuf::from(self.update_package_path.trim());
            if !manifest_path.is_absolute() || !package_path.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "update manifest and package paths must be absolute".to_owned(),
                ));
            }
            let metadata = std::fs::metadata(&manifest_path)?;
            if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 64 * 1024 {
                return Err(ShellError::InvalidInput(
                    "signed update manifest must be a non-empty regular file <= 64 KiB".to_owned(),
                ));
            }
            let manifest = serde_json::from_slice(&std::fs::read(&manifest_path)?)?;
            Ok((manifest, package_path))
        })();
        match outcome {
            Ok((manifest, package_path)) => {
                let updater = self.updater.clone();
                let protocol_version = self.manifest.protocol_version;
                self.update_message = None;
                self.start_task(UiTaskKind::StageUpdate, move || {
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
            "Keyboard focus follows egui's native focus order. Use Tab/Shift+Tab to move between controls and Enter/Space to activate focused buttons.",
            "键盘焦点遵循 egui 原生焦点顺序。使用 Tab/Shift+Tab 切换控件，Enter/Space 激活当前按钮。",
        ));
        ui.label(self.locale.text(
            "Locale selection currently follows LC_ALL/LC_MESSAGES/LANG and includes English and Chinese shell strings.",
            "当前区域设置依据 LC_ALL/LC_MESSAGES/LANG，壳层字符串支持英文与中文。",
        ));
    }
}
