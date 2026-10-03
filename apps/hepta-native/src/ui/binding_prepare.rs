//! Preparing a resource-bound grant input may perform OS I/O. The runtime lane
//! owns that work; a completed binding is displayed only for its exact UI input.

use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct BindingInput {
    subject: String,
    operation: String,
    payload: PlatformPayload,
    view: RuntimeView,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) struct PreparedBinding {
    pub(super) text: String,
    pub(super) input: BindingInput,
}

impl BindingInput {
    pub(super) fn capture(app: &HeptaNativeApp) -> Result<Self, ShellError> {
        let view = app
            .ready_view
            .clone()
            .ok_or_else(|| ShellError::State("native runtime view is unavailable".to_owned()))?;
        if !app.connected || app.view_revision != Some(view.revision) {
            return Err(ShellError::State(
                "native binding requires the current authenticated view".to_owned(),
            ));
        }
        Ok(Self {
            subject: app.operation_subject_id.clone(),
            operation: app.operation_id.clone(),
            payload: app.operation_payload()?,
            view,
        })
    }

    fn matches(&self, app: &HeptaNativeApp) -> bool {
        if app.screen != Screen::Operations
            || app.shutdown.requested()
            || !app.connected
            || app.view_revision != Some(self.view.revision)
            || app.ready_view.as_ref() != Some(&self.view)
            || app.operation_subject_id != self.subject
            || app.operation_id != self.operation
            || app.operation_action != self.payload.action()
        {
            return false;
        }
        match &self.payload {
            PlatformPayload::OpenPath { path } | PlatformPayload::RevealPath { path } => {
                path.as_os_str() == std::ffi::OsStr::new(&app.operation_path)
            }
            PlatformPayload::CopyText { text } => app.operation_text == *text,
            PlatformPayload::Notify { title, body } => {
                app.notification_title == *title && app.notification_body == *body
            }
        }
    }
}

impl HeptaNativeApp {
    pub(super) fn prepare_operation_binding(&mut self) {
        self.operation_binding = None;
        self.operation_message = None;
        let input = match BindingInput::capture(self) {
            Ok(input) => input,
            Err(error) => {
                self.last_error = Some(error.to_string());
                return;
            }
        };
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::PrepareBinding, move |admission| {
            let runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.to_owned()))?;
            if runtime.view() != Some(&input.view) {
                return Err(ShellError::State(
                    "binding input does not match the current runtime view".to_owned(),
                ));
            }
            let binding = runtime.prepare_platform_binding(
                input.subject.trim(),
                input.operation.trim(),
                &input.payload,
            )?;
            let text = serde_json::to_string_pretty(&binding)?;
            Ok(UiTaskOutput::PrepareBinding(PreparedBinding {
                text,
                input,
            }))
        });
    }

    pub(super) fn install_prepared_binding(&mut self, binding: PreparedBinding) {
        if binding.input.matches(self) {
            self.operation_binding = Some(binding);
            self.operation_message = Some(
                self.locale
                    .text(
                        "Binding prepared. The independent authority owner must choose grant identity, nonce, epoch and lifetime and sign the complete grant.",
                        "Binding 已生成。独立 authority owner 必须自行选择 grant identity、nonce、epoch 与有效期，并签署完整 grant。",
                    )
                    .to_owned(),
            );
        } else {
            self.operation_binding = None;
            self.operation_message = Some(
                self.locale
                    .text(
                        "Prepared binding discarded because the input, screen or view changed; prepare it again.",
                        "输入、页面或视图已改变，已丢弃生成的 binding；请重新生成。",
                    )
                    .to_owned(),
            );
        }
        self.last_error = None;
    }

    pub(super) fn invalidate_edited_binding(&mut self) {
        if self
            .operation_binding
            .as_ref()
            .is_some_and(|binding| !binding.input.matches(self))
        {
            self.operation_binding = None;
            self.operation_message = None;
        }
    }
}

#[cfg(test)]
#[path = "binding_prepare_tests.rs"]
mod tests;
