use super::history_page::HISTORY_PAGE_SIZE;
use super::history_page::history_last_page;
use super::task_supervisor::FileInputTarget;
use super::update_views::FocusReveal as _;
use super::*;
use crate::model::TerminalStatus;

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

fn operation_action_label(action: PlatformAction, locale: Locale) -> &'static str {
    match action {
        PlatformAction::OpenPath => locale.text("Open path", "打开路径"),
        PlatformAction::RevealPath => locale.text("Reveal path", "显示路径"),
        PlatformAction::CopyText => locale.text("Copy text", "复制文本"),
        PlatformAction::Notify => locale.text("Show notification", "显示通知"),
    }
}

fn operation_receipt_label(receipt: &PlatformReceipt, locale: Locale) -> &'static str {
    match project_operation_presentation(
        receipt.terminal_observed,
        receipt.may_have_executed,
        receipt.observation_closed,
    ) {
        OperationPresentation::TerminalObserved => match receipt.terminal_status {
            Some(TerminalStatus::Succeeded) => locale.text(
                "Succeeded · terminal platform observation recorded",
                "已成功 · 已记录平台终态观察",
            ),
            Some(TerminalStatus::Failed) => locale.text(
                "Failed · terminal platform observation recorded",
                "已失败 · 已记录平台终态观察",
            ),
            Some(TerminalStatus::Rejected) => locale.text(
                "Rejected · terminal platform observation recorded",
                "已拒绝 · 已记录平台终态观察",
            ),
            Some(TerminalStatus::Quarantined) => locale.text(
                "Quarantined · terminal platform observation recorded",
                "已隔离 · 已记录平台终态观察",
            ),
            None => locale.text(
                "Terminal observation recorded; status unavailable",
                "已记录终态观察；状态不可用",
            ),
        },
        OperationPresentation::PreparedNotDispatched => {
            locale.text("Prepared; not dispatched.", "已准备；尚未派发。")
        }
        OperationPresentation::AwaitingObservation => locale.text(
            "May have executed; awaiting a trustworthy terminal observation.",
            "可能已经执行；正在等待可信终态观察。",
        ),
        OperationPresentation::ObservationClosedUnknown => locale.text(
            "Observation closed; outcome UNKNOWN; replay forbidden.",
            "已结束观察；执行结果仍未知；禁止重放。",
        ),
    }
}

impl HeptaNativeApp {
    pub(super) fn operations_view(&mut self, ui: &mut egui::Ui) {
        let focus_target = self.file_input_focus.take();
        ui.heading(self.locale.text("Native operations", "原生操作"));
        ui.label(self.locale.text(
            "Prepare the exact request, obtain an independently signed grant, then execute once.",
            "准备精确请求，取得独立签发的授权，再执行一次。",
        ));
        ui.separator();
        theme::eyebrow(
            ui,
            self.locale.text("01 / DEFINE OPERATION", "01 / 定义操作"),
        );
        let label = ui.label(self.locale.text("Authority subject", "权限主体"));
        ui.add(
            egui::TextEdit::singleline(&mut self.operation_subject_id)
                .min_size(egui::vec2(0.0, 34.0))
                .id(egui::Id::new("native-operation-subject"))
                .desired_width(ui.available_width().min(640.0))
                .char_limit(crate::model::MAX_STABLE_ID_BYTES),
        )
        .labelled_by(label.id)
        .reveal_focus();
        let label = ui.label(self.locale.text("Operation ID", "操作 ID"));
        ui.add(
            egui::TextEdit::singleline(&mut self.operation_id)
                .min_size(egui::vec2(0.0, 34.0))
                .id(egui::Id::new("native-operation-id"))
                .desired_width(ui.available_width().min(640.0))
                .char_limit(crate::model::MAX_STABLE_ID_BYTES),
        )
        .labelled_by(label.id)
        .reveal_focus();
        egui::ComboBox::from_label(self.locale.text("Action", "操作类型"))
            .selected_text(operation_action_label(self.operation_action, self.locale))
            .show_ui(ui, |ui| {
                for action in [
                    PlatformAction::OpenPath,
                    PlatformAction::RevealPath,
                    PlatformAction::CopyText,
                    PlatformAction::Notify,
                ] {
                    ui.selectable_value(
                        &mut self.operation_action,
                        action,
                        operation_action_label(action, self.locale),
                    );
                }
            })
            .response
            .reveal_focus();
        match self.operation_action {
            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                ui.collapsing(self.locale.text("Path safety details", "路径安全详情"), |ui| {
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
                });
                let label = ui.label(self.locale.text("Absolute path", "绝对路径"));
                ui.add(
                    egui::TextEdit::singleline(&mut self.operation_path)
                        .min_size(egui::vec2(0.0, 34.0))
                        .id(egui::Id::new("native-operation-path"))
                        .desired_width(ui.available_width().min(640.0))
                        .char_limit(crate::model::MAX_NATIVE_PATH_BYTES),
                )
                .labelled_by(label.id)
                .reveal_focus();
            }
            PlatformAction::CopyText => {
                let label = ui.label(self.locale.text("Clipboard text", "剪贴板文本"));
                ui.add(
                    egui::TextEdit::multiline(&mut self.operation_text)
                        .id(egui::Id::new("native-operation-text"))
                        .desired_rows(3)
                        .desired_width(ui.available_width().min(640.0))
                        .char_limit(crate::model::MAX_COPY_TEXT_BYTES),
                )
                .labelled_by(label.id)
                .reveal_focus();
            }
            PlatformAction::Notify => {
                let label = ui.label(self.locale.text("Notification title", "通知标题"));
                ui.add(
                    egui::TextEdit::singleline(&mut self.notification_title)
                        .min_size(egui::vec2(0.0, 34.0))
                        .id(egui::Id::new("native-notification-title"))
                        .desired_width(ui.available_width().min(640.0))
                        .char_limit(crate::model::MAX_NOTIFICATION_TITLE_BYTES),
                )
                .labelled_by(label.id)
                .reveal_focus();
                let label = ui.label(self.locale.text("Notification body", "通知正文"));
                ui.add(
                    egui::TextEdit::multiline(&mut self.notification_body)
                        .id(egui::Id::new("native-notification-body"))
                        .desired_rows(3)
                        .desired_width(ui.available_width().min(640.0))
                        .char_limit(crate::model::MAX_NOTIFICATION_BODY_BYTES),
                )
                .labelled_by(label.id)
                .reveal_focus();
            }
        }
        self.invalidate_edited_binding();
        let busy = self.is_busy();
        let blocked = if busy {
            Some(self.locale.text(
                "Wait for the current task to finish.",
                "请等待当前任务完成。",
            ))
        } else if !self.connected
            || self
                .ready_view
                .as_ref()
                .is_none_or(|view| self.view_revision != Some(view.revision))
        {
            Some(self.locale.text(
                "Verify or refresh the runtime snapshot before preparing an operation.",
                "请先验证或刷新运行时快照，再准备操作。",
            ))
        } else if !cfg!(target_os = "linux")
            && matches!(
                self.operation_action,
                PlatformAction::OpenPath | PlatformAction::RevealPath
            )
        {
            Some(self.locale.text("Path actions are unavailable on this platform until its resource-capability adapter is qualified.", "当前平台的资源能力适配器尚未通过资格验证，路径操作不可用。"))
        } else {
            None
        };
        ui.separator();
        theme::eyebrow(
            ui,
            self.locale
                .text("02 / PREPARE AUTHORIZATION", "02 / 准备授权"),
        );
        ui.label(self.locale.text("The shell cannot sign authority. Give the exact binding to the independent authority owner for a SignedFinalUseGrant.", "壳层不能签发权限。请将精确 binding 交给独立权限所有者，由其签发 SignedFinalUseGrant。"));
        if let Some(reason) = blocked {
            ui.colored_label(theme::AMBER, reason);
        }
        if ui
            .add_enabled(
                blocked.is_none(),
                egui::Button::new(
                    self.locale
                        .text("Prepare exact binding", "生成精确 binding"),
                ),
            )
            .on_disabled_hover_text(blocked.unwrap_or_default())
            .reveal_focus()
            .clicked()
        {
            self.prepare_operation_binding();
        }
        if let Some(binding) = &mut self.operation_binding {
            ui.collapsing(
                self.locale.text(
                    "Exact binding for independent issuer",
                    "交给独立签发方的精确 binding",
                ),
                |ui| {
                    let label = ui.label(
                        self.locale
                            .text("Binding content (read-only)", "Binding 内容（只读）"),
                    );
                    ui.add(
                        egui::TextEdit::multiline(&mut binding.text)
                            .font(egui::TextStyle::Monospace)
                            .desired_width(f32::INFINITY)
                            .desired_rows(8)
                            .interactive(false),
                    )
                    .labelled_by(label.id)
                    .reveal_focus();
                },
            );
        }
        ui.separator();
        theme::eyebrow(ui, self.locale.text("03 / EXECUTE ONCE", "03 / 执行一次"));
        let label = ui.label(self.locale.text("Signed grant path", "签名授权路径"));
        let grant_response = ui
            .horizontal_wrapped(|ui| {
                let response = ui
                    .add(
                        egui::TextEdit::singleline(&mut self.operation_grant_path)
                            .min_size(egui::vec2(0.0, 34.0))
                            .id(egui::Id::new("native-operation-grant"))
                            .desired_width(ui.available_width().min(480.0))
                            .hint_text(self.locale.text(
                                "Absolute path to the signed grant",
                                "签名授权文件的绝对路径",
                            ))
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
                    .on_disabled_hover_text(self.locale.text(
                        "Finish or cancel the current file selection first.",
                        "请先完成或取消当前文件选择。",
                    ))
                    .reveal_focus()
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
        grant_response.reveal_focus();
        self.render_file_input_intent_status(ui);
        let execute_blocked = blocked.or_else(|| {
            super::path_input::absolute_path(&self.operation_grant_path)
                .err()
                .map(|_| {
                    self.locale.text(
                        "Choose a signed grant or enter its absolute path.",
                        "请选择签名授权文件，或输入其绝对路径。",
                    )
                })
        });
        if blocked.is_none()
            && let Some(reason) = execute_blocked
        {
            ui.colored_label(theme::AMBER, reason);
        }
        if ui
            .add_enabled(
                execute_blocked.is_none(),
                egui::Button::new(
                    self.locale
                        .text("Execute with signed grant", "使用签名授权执行"),
                ),
            )
            .on_disabled_hover_text(execute_blocked.unwrap_or_default())
            .reveal_focus()
            .clicked()
        {
            self.execute_operation();
        }
        if let Some(message) = &self.operation_message {
            ui.label(message);
        }
        ui.separator();
        theme::eyebrow(ui, self.locale.text("OPERATION RECEIPTS", "操作回执"));
        if let Ok(runtime) = self.runtime.try_lock() {
            let capacity = runtime.journal_capacity();
            ui.collapsing(self.locale.text("Journal capacity details", "日志容量详情"), |ui| { ui.label(format!(
                "active={}/{} pending={} closed={} retired={} segments={} wal_entries={} wal_bytes={}",
                capacity.active_records,
                capacity.active_limit,
                capacity.pending_records,
                capacity.closed_observations,
                capacity.retired_identities,
                capacity.retirement_segments,
                capacity.wal_entries,
                capacity.wal_bytes
            )); });
            if capacity.active_records >= capacity.active_limit * 4 / 5 {
                ui.label(self.locale.text(
                    "Journal pressure: reconcile or close observations; NEVER delete the journal to retry.",
                    "日志容量告警：请对账或结束观察；绝不能删除日志后重试。",
                ));
            }
        }
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
            .on_disabled_hover_text(self.locale.text(
                "Wait for the current task to finish.",
                "请等待当前任务完成。",
            ))
            .reveal_focus()
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
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    !page_busy && self.history_page > 0,
                    egui::Button::new(self.locale.text("Previous page", "上一页")),
                )
                .reveal_focus()
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
                .reveal_focus()
                .clicked()
            {
                self.load_history_page(self.history_page + 1);
            }
        });
        let mut close_observation = None;
        ui.scope(|ui| {
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
                                receipt.key.operation_id,
                                operation_action_label(receipt.action, self.locale)
                            ));
                            ui.label(operation_receipt_label(receipt, self.locale));
                            ui.collapsing(
                                self.locale.text("Receipt details", "回执详情"),
                                |ui| {
                                    ui.label(format!(
                                        "session={} generation={}",
                                        receipt.key.session_id, receipt.key.session_generation
                                    ));
                                    ui.label(format!(
                                        "terminal={} status={:?}",
                                        receipt.terminal_observed, receipt.terminal_status
                                    ));
                                    ui.label(format!("payload={}", receipt.payload_digest));
                                },
                            );
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
                                    .reveal_focus()
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
                    history: runtime.operation_history_page(requested_page, HISTORY_PAGE_SIZE)?,
                })
            });
        }
    }

    pub(super) fn operation_payload(&self) -> Result<PlatformPayload, ShellError> {
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
                let locale = self.locale;
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
                        "{}: {}",
                        receipt.key.operation_id,
                        operation_receipt_label(&receipt, locale)
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
