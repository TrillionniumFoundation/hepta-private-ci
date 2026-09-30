use super::history_page::HISTORY_PAGE_SIZE;
use super::history_page::history_last_page;
use super::task_supervisor::FileInputTarget;
use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum OperationPresentation {
    TerminalObserved,
    PreparedNotDispatched,
    AwaitingObservation,
    ObservationClosedUnknown,
}

fn project_operation_presentation(
    terminal_observed: bool,
    may_have_executed: bool,
    observation_closed: bool,
) -> OperationPresentation {
    if terminal_observed {
        OperationPresentation::TerminalObserved
    } else if observation_closed {
        OperationPresentation::ObservationClosedUnknown
    } else if may_have_executed {
        OperationPresentation::AwaitingObservation
    } else {
        OperationPresentation::PreparedNotDispatched
    }
}

impl HeptaNativeApp {
    pub(super) fn operations_view(&mut self, ui: &mut egui::Ui) {
        let focus_target = self.file_input_focus.take();
        ui.heading(self.locale.text("Native operations", "原生操作"));
        if let Ok(runtime) = self.runtime.try_lock() {
            let capacity = runtime.journal_capacity();
            ui.label(format!(
                "active={}/{} pending={} closed={} retired={} segments={} wal_entries={} wal_bytes={}",
                capacity.active_records,
                capacity.active_limit,
                capacity.pending_records,
                capacity.closed_observations,
                capacity.retired_identities,
                capacity.retirement_segments,
                capacity.wal_entries,
                capacity.wal_bytes
            ));
            if capacity.active_records >= capacity.active_limit * 4 / 5 {
                ui.label(self.locale.text(
                    "Journal pressure: reconcile or close observations; NEVER delete the journal to retry.",
                    "日志容量告警：请对账或结束观察；绝不能删除日志后重试。",
                ));
            }
        }
        ui.label(self.locale.text(
            "The shell never signs its own authority. Prepare the exact binding, have the independent authority owner issue a SignedFinalUseGrant, then select that grant file for one final-use operation.",
            "壳层绝不会自行签发权限。先生成精确 binding，由独立 authority owner 签发 SignedFinalUseGrant，再选择该 grant 文件执行一次 final-use 操作。",
        ));
        ui.separator();
        ui.label(self.locale.text("Authority subject", "权限主体"));
        ui.add(
            egui::TextEdit::singleline(&mut self.operation_subject_id)
                .id(egui::Id::new("native-operation-subject"))
                .char_limit(crate::model::MAX_STABLE_ID_BYTES),
        );
        ui.label(self.locale.text("Operation ID", "操作 ID"));
        ui.add(
            egui::TextEdit::singleline(&mut self.operation_id)
                .id(egui::Id::new("native-operation-id"))
                .char_limit(crate::model::MAX_STABLE_ID_BYTES),
        );
        egui::ComboBox::from_id_salt("native-operation-action")
            .selected_text(self.operation_action.to_string())
            .show_ui(ui, |ui| {
                for action in [
                    PlatformAction::OpenPath,
                    PlatformAction::RevealPath,
                    PlatformAction::CopyText,
                    PlatformAction::Notify,
                ] {
                    ui.selectable_value(&mut self.operation_action, action, action.to_string());
                }
            });
        match self.operation_action {
            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                if cfg!(target_os = "linux") {
                    ui.label(self.locale.text(
                        "Linux: the path is opened with NOFOLLOW, the exact device/inode/metadata identity is bound into final-use confirmation, then the already-open descriptor is handed to XDG OpenURI. No mutable name is reopened after admission.",
                        "Linux：路径以 NOFOLLOW 打开，精确的设备/inode/元数据身份被绑定到 final-use 确认，随后把已打开描述符交给 XDG OpenURI。准入后不会重新按可变名称打开。",
                    ));
                } else {
                    ui.label(self.locale.text(
                        "Unavailable on this platform until a verified OS resource-capability adapter is qualified; mutable path-string launch remains disabled.",
                        "当前平台尚未通过已验证 OS 资源能力适配器资格；可变路径字符串启动仍被禁用。",
                    ));
                }
                ui.label(self.locale.text("Absolute path", "绝对路径"));
                ui.add(
                    egui::TextEdit::singleline(&mut self.operation_path)
                        .id(egui::Id::new("native-operation-path"))
                        .char_limit(crate::model::MAX_NATIVE_PATH_BYTES),
                );
            }
            PlatformAction::CopyText => {
                ui.label(self.locale.text("Clipboard text", "剪贴板文本"));
                ui.add(
                    egui::TextEdit::multiline(&mut self.operation_text)
                        .id(egui::Id::new("native-operation-text"))
                        .char_limit(crate::model::MAX_COPY_TEXT_BYTES),
                );
            }
            PlatformAction::Notify => {
                ui.label(self.locale.text("Notification title", "通知标题"));
                ui.add(
                    egui::TextEdit::singleline(&mut self.notification_title)
                        .id(egui::Id::new("native-notification-title"))
                        .char_limit(crate::model::MAX_NOTIFICATION_TITLE_BYTES),
                );
                ui.label(self.locale.text("Notification body", "通知正文"));
                ui.add(
                    egui::TextEdit::multiline(&mut self.notification_body)
                        .id(egui::Id::new("native-notification-body"))
                        .char_limit(crate::model::MAX_NOTIFICATION_BODY_BYTES),
                );
            }
        }
        ui.label(self.locale.text("Signed grant path", "签名 grant 路径"));
        let grant_response = ui
            .horizontal(|ui| {
                let response = ui.add(
                    egui::TextEdit::singleline(&mut self.operation_grant_path)
                        .id(egui::Id::new("native-operation-grant"))
                        .char_limit(crate::model::MAX_NATIVE_PATH_BYTES),
                );
                if ui
                    .add_enabled(
                        !self.picker_busy(),
                        egui::Button::new(self.locale.text("Choose file", "选择文件")),
                    )
                    .clicked()
                {
                    self.pick_file_input_target(ui.ctx(), FileInputTarget::OperationGrant);
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
                    self.arm_file_input_target(ui.ctx(), FileInputTarget::OperationGrant);
                }
                response
            })
            .inner;
        if focus_target == Some(FileInputTarget::OperationGrant) {
            grant_response.request_focus();
        }
        self.render_file_input_intent_status(ui);
        let busy = self.is_busy();
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    !busy && self.view_revision.is_some(),
                    egui::Button::new(
                        self.locale
                            .text("Prepare exact binding", "生成精确 binding"),
                    ),
                )
                .clicked()
            {
                self.prepare_operation_binding();
            }
            if ui
                .add_enabled(
                    !busy && self.view_revision.is_some(),
                    egui::Button::new(
                        self.locale
                            .text("Execute with signed grant", "使用签名 grant 执行"),
                    ),
                )
                .clicked()
            {
                self.execute_operation();
            }
        });
        if let Some(binding) = &mut self.operation_binding {
            ui.label(self.locale.text(
                "Binding for the independent issuer:",
                "交给独立签发方的 binding：",
            ));
            ui.add(
                egui::TextEdit::multiline(binding)
                    .font(egui::TextStyle::Monospace)
                    .desired_rows(10)
                    .interactive(false),
            );
        }
        if let Some(message) = &self.operation_message {
            ui.label(message);
        }
        ui.separator();
        ui.label(self.locale.text(
            "Indeterminate operations are never automatically replayed. Reconcile asks the platform adapter for a trustworthy terminal observation.",
            "不确定操作绝不会自动重放。对账只接受平台适配器提供的可信终态观察。",
        ));
        if ui
            .add_enabled(
                !busy,
                egui::Button::new(self.locale.text(
                    "Archive closed history (retain last 256)",
                    "归档已结案历史（保留最近 256 条）",
                )),
            )
            .clicked()
        {
            let runtime = Arc::clone(&self.runtime);
            self.start_task(UiTaskKind::Reconcile, move |admission| {
                let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
                admission
                    .begin()
                    .map_err(|message| ShellError::State(message.to_owned()))?;
                runtime.compact_closed_history(256)?;
                Ok(UiTaskOutput::Reconcile {
                    history: runtime.operation_history_page(0, HISTORY_PAGE_SIZE)?,
                })
            });
        }
        if self.history_total == 0 {
            self.history_page = 0;
            self.operations.clear();
            ui.label(self.locale.text("No operation receipts.", "暂无操作回执。"));
            return;
        }
        let last_page = history_last_page(self.history_total);
        let page_busy = self.history_read_busy() || busy;
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    !page_busy && self.history_page > 0,
                    egui::Button::new(self.locale.text("Previous page", "上一页")),
                )
                .clicked()
            {
                self.load_history_page(self.history_page - 1);
            }
            ui.label(format!(
                "{} / {} · {}",
                self.history_page + 1,
                last_page + 1,
                self.history_total
            ));
            if ui
                .add_enabled(
                    !page_busy && self.history_page < last_page,
                    egui::Button::new(self.locale.text("Next page", "下一页")),
                )
                .clicked()
            {
                self.load_history_page(self.history_page + 1);
            }
        });
        let mut close_observation = None;
        egui::ScrollArea::vertical().show(ui, |ui| {
            for receipt in &self.operations {
                ui.push_id(
                    (
                        &receipt.key.session_id,
                        receipt.key.session_generation,
                        &receipt.key.operation_id,
                    ),
                    |ui| {
                        ui.group(|ui| {
                            ui.label(format!(
                                "{} · {}",
                                receipt.key.operation_id, receipt.action
                            ));
                            ui.label(format!(
                                "session={} generation={}",
                                receipt.key.session_id, receipt.key.session_generation
                            ));
                            ui.label(format!(
                                "terminal={} status={:?}",
                                receipt.terminal_observed, receipt.terminal_status
                            ));
                            ui.label(format!("payload={}", receipt.payload_digest));
                            match project_operation_presentation(
                                receipt.terminal_observed,
                                receipt.may_have_executed,
                                receipt.observation_closed,
                            ) {
                                OperationPresentation::TerminalObserved => {
                                    ui.label(self.locale.text(
                                        "Terminal platform observation recorded.",
                                        "已记录平台终态观察。",
                                    ));
                                }
                                OperationPresentation::PreparedNotDispatched => {
                                    ui.label(self.locale.text(
                                        "Prepared; not dispatched.",
                                        "已准备；尚未派发。",
                                    ));
                                }
                                OperationPresentation::AwaitingObservation => {
                                    ui.label(self.locale.text(
                                        "May have executed; awaiting a trustworthy terminal observation.",
                                        "可能已经执行；正在等待可信终态观察。",
                                    ));
                                }
                                OperationPresentation::ObservationClosedUnknown => {
                                    ui.label(self.locale.text(
                                        "Observation closed; outcome UNKNOWN; replay forbidden.",
                                        "已结束观察；执行结果仍未知；禁止重放。",
                                    ));
                                }
                            }
                            if !receipt.observation_closed
                                && receipt.can_close_observation
                                && ui
                                    .add_enabled(
                                        !busy,
                                        egui::Button::new(self.locale.text(
                                            "End observation (may have executed)",
                                            "结束观察（可能已执行）",
                                        )),
                                    )
                                    .clicked()
                            {
                                close_observation = Some(receipt.key.clone());
                            }
                        });
                    },
                );
            }
        });
        if let Some(key) = close_observation {
            let requested_page = self.history_page;
            let runtime = Arc::clone(&self.runtime);
            self.start_task(UiTaskKind::Reconcile, move |admission| {
                let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
                admission
                    .begin()
                    .map_err(|message| ShellError::State(message.to_owned()))?;
                runtime.close_operation_observation(&key)?;
                runtime.compact_closed_history(256)?;
                Ok(UiTaskOutput::Reconcile {
                    history: runtime
                        .operation_history_page(requested_page, HISTORY_PAGE_SIZE)?,
                })
            });
        }
    }

    fn operation_payload(&self) -> Result<PlatformPayload, ShellError> {
        let payload = match self.operation_action {
            PlatformAction::OpenPath => PlatformPayload::OpenPath {
                path: super::path_input::absolute_path(&self.operation_path)?,
            },
            PlatformAction::RevealPath => PlatformPayload::RevealPath {
                path: super::path_input::absolute_path(&self.operation_path)?,
            },
            PlatformAction::CopyText => PlatformPayload::CopyText {
                text: self.operation_text.clone(),
            },
            PlatformAction::Notify => PlatformPayload::Notify {
                title: self.notification_title.clone(),
                body: self.notification_body.clone(),
            },
        };
        payload.validate()?;
        Ok(payload)
    }

    fn prepare_operation_binding(&mut self) {
        let outcome = (|| -> Result<String, ShellError> {
            let payload = self.operation_payload()?;
            let runtime = self.runtime.try_lock().map_err(|_| {
                ShellError::State("native runtime is busy; retry after the current task".to_owned())
            })?;
            let binding = runtime.prepare_platform_binding(
                self.operation_subject_id.trim(),
                self.operation_id.trim(),
                &payload,
            )?;
            serde_json::to_string_pretty(&binding).map_err(ShellError::from)
        })();
        match outcome {
            Ok(binding) => {
                self.operation_binding = Some(binding);
                self.operation_message = Some(
                    self.locale
                        .text(
                            "Binding prepared. The independent authority owner must choose grant identity, nonce, epoch and lifetime and sign the complete grant.",
                            "Binding 已生成。独立 authority owner 必须自行选择 grant identity、nonce、epoch 与有效期，并签署完整 grant。",
                        )
                        .to_owned(),
                );
                self.last_error = None;
            }
            Err(error) => {
                self.operation_binding = None;
                self.operation_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }

    fn execute_operation(&mut self) {
        let outcome = (|| -> Result<(PathBuf, u64, PlatformPayload), ShellError> {
            let grant_path = super::path_input::absolute_path(&self.operation_grant_path)?;
            let displayed_revision = self.view_revision.ok_or_else(|| {
                ShellError::State("native runtime view is unavailable".to_owned())
            })?;
            Ok((grant_path, displayed_revision, self.operation_payload()?))
        })();
        match outcome {
            Ok((grant_path, displayed_revision, payload)) => {
                let runtime = Arc::clone(&self.runtime);
                let subject_id = self.operation_subject_id.trim().to_owned();
                let operation_id = self.operation_id.trim().to_owned();
                self.operation_message = None;
                self.start_task(UiTaskKind::Execute, move |admission| {
                    let grant: SignedFinalUseGrant =
                        crate::file_input::read_json_file(&grant_path, 16 * 1024)?;
                    let request = PlatformRequest {
                        subject_id,
                        operation_id,
                        displayed_revision,
                        payload,
                        grant,
                    };
                    let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
                    admission
                        .begin()
                        .map_err(|message| ShellError::State(message.to_owned()))?;
                    let receipt = runtime.request_platform_capability(request)?;
                    let message = format!(
                        "{}: terminal={} status={:?}",
                        receipt.key.operation_id,
                        receipt.terminal_observed,
                        receipt.terminal_status
                    );
                    Ok(UiTaskOutput::Execute {
                        message,
                        history: runtime.operation_history_page(0, HISTORY_PAGE_SIZE)?,
                    })
                });
            }
            Err(error) => {
                self.operation_message = None;
                self.last_error = Some(error.to_string());
            }
        }
    }
}

#[cfg(test)]
mod projection_tests {
    use super::OperationPresentation;
    use super::project_operation_presentation;

    #[test]
    fn operation_projection_has_one_unambiguous_state() {
        assert_eq!(
            project_operation_presentation(true, true, true),
            OperationPresentation::TerminalObserved
        );
        assert_eq!(
            project_operation_presentation(false, false, false),
            OperationPresentation::PreparedNotDispatched
        );
        assert_eq!(
            project_operation_presentation(false, true, false),
            OperationPresentation::AwaitingObservation
        );
        assert_eq!(
            project_operation_presentation(false, true, true),
            OperationPresentation::ObservationClosedUnknown
        );
    }
}
