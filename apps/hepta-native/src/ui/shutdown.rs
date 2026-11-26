use std::time::Instant;

use super::*;

const SHUTDOWN_GRACE: Duration = Duration::from_secs(150);

#[derive(Default)]
pub(super) struct Shutdown {
    requested_at: Option<Instant>,
    close_started: bool,
    pub(super) runtime_closed: bool,
    pub(super) update_requested: bool,
    pub(super) failure: Option<String>,
}

impl Shutdown {
    pub(super) fn requested(&self) -> bool {
        self.requested_at.is_some()
    }

    pub(super) fn request(&mut self, now: Instant) {
        // Repeated window-close events do not extend the deadline.
        self.requested_at.get_or_insert(now);
    }

    pub(super) fn check_deadline(&mut self, now: Instant) {
        if !self.runtime_closed
            && self.failure.is_none()
            && self
                .requested_at
                .is_some_and(|start| now.saturating_duration_since(start) >= SHUTDOWN_GRACE)
        {
            self.failure = Some("Shutdown deadline exceeded. Every worker is still owned; no update will activate. Do not replay unknown operations.".to_owned());
            self.update_requested = false;
        }
    }

    pub(super) fn activation_allowed(&self) -> bool {
        self.runtime_closed && self.update_requested && self.failure.is_none()
    }
}

impl HeptaNativeApp {
    /// The GUI remains alive until all three lanes and the runtime owner close.
    pub(super) fn request_shutdown(&mut self, ctx: &egui::Context) {
        let first_request = !self.shutdown.requested();
        self.shutdown.request(Instant::now());
        self.activate_update_on_exit.store(false, Ordering::Release);
        self.view_revision = None;
        self.operation_binding = None;
        task_supervisor::cancel_file_input(ctx);
        if first_request {
            for task in [
                self.pending_runtime.as_ref(),
                self.pending_read.as_ref(),
                self.pending_picker.as_ref(),
            ]
            .into_iter()
            .flatten()
            {
                task.worker.cancel_before_admission();
            }
        }
        ctx.request_repaint();
    }

    pub(super) fn shutdown_view(&mut self, ui: &mut egui::Ui) -> bool {
        let ctx = ui.ctx().clone();
        if ctx.input(|input| input.viewport().close_requested()) && !self.shutdown.runtime_closed {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.request_shutdown(&ctx);
        }
        if !self.shutdown.requested() {
            return false;
        }
        if self.shutdown.runtime_closed && self.all_tasks_idle() {
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            return true;
        }
        self.shutdown.check_deadline(Instant::now());
        if self.all_tasks_idle() && !self.shutdown.close_started {
            let runtime = Arc::clone(&self.runtime);
            // Shutdown is the only mutation admitted after closing is requested.
            match spawn_ui_task(
                UiTaskKind::Shutdown,
                Arc::clone(&self.repaint),
                move |admission| {
                    let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
                    admission
                        .begin()
                        .map_err(|message| ShellError::State(message.to_owned()))?;
                    runtime.close()?;
                    Ok(UiTaskOutput::Shutdown)
                },
            ) {
                Ok(task) => {
                    self.pending_runtime = Some(task);
                    self.shutdown.close_started = true;
                }
                Err(error) => {
                    self.shutdown.close_started = true;
                    self.shutdown.failure = Some(format!("Cannot start shutdown worker: {error}"));
                    self.shutdown.update_requested = false;
                }
            }
        }
        egui::CentralPanel::default().show(ui, |ui| {
            ui.heading(self.locale.text("Closing safely", "正在安全关闭"));
            ui.label(self.locale.text(
                "New actions are blocked. Waiting for picker, history reader, admitted mutation and runtime cleanup; unknown effects will not be replayed.",
                "已停止接纳新操作。正在等待文件选择器、历史读取、已准入 mutation 与运行时清理；不会重放结果未知的操作。",
            ));
            if let Some(error) = &self.shutdown.failure {
                ui.label(egui::RichText::new(error).strong());
            }
            if self.any_task_active() {
                ui.spinner();
            } else if ui
                .button(
                    self.locale
                        .text("Retry runtime close (no update)", "重试关闭运行时（不激活更新）"),
                )
                .clicked()
            {
                // Do not reset the deadline or manufacture success after failure.
                self.shutdown.close_started = false;
                self.shutdown.update_requested = false;
                ctx.request_repaint();
            }
        });
        if self.any_task_active() {
            ctx.request_repaint_after(Duration::from_millis(250));
        }
        true
    }
}

#[cfg(test)]
#[path = "shutdown_tests.rs"]
mod tests;
