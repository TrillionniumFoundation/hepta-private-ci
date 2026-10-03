use super::*;

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
            self.tasks.cancel_waiting();
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
            let repaint = Arc::clone(&self.repaint);
            match self.tasks.start_close(&self.shutdown, || {
                spawn_ui_task(UiTaskKind::Shutdown, repaint, move |admission| {
                    let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
                    admission
                        .begin()
                        .map_err(|message| ShellError::State(message.to_owned()))?;
                    runtime.close()?;
                    Ok(UiTaskOutput::Shutdown)
                })
            }) {
                Ok(()) => {
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
