//! Small semantic-DOM renderer. Interaction state is in Rust, not HTML attributes.
use hepta_control_core::{
    controller::ControlView,
    error::{ControlError, ErrorCode},
    ledger::{OperationState, OperationView},
    projection::{RuntimeSnapshot, RuntimeStatus},
};
use std::collections::{BTreeMap, BTreeSet};
use wasm_bindgen::JsCast;
use web_sys::{
    Document, Element, HtmlButtonElement, HtmlDialogElement, HtmlElement, HtmlSelectElement,
    HtmlTextAreaElement,
};

mod lists;
use lists::{ModuleRow, OperationRow};

pub(crate) struct Dom {
    pub document: Document,
    pub target: HtmlSelectElement,
    pub reason: HtmlTextAreaElement,
    pub dialog: HtmlDialogElement,
    pub confirm: HtmlButtonElement,
    pub cancel: HtmlButtonElement,
    pub start: HtmlButtonElement,
    pub reconcile: HtmlButtonElement,
    pub stop: HtmlButtonElement,
    pub refresh: HtmlButtonElement,
    pub pending: Element,
    pub live: HtmlElement,
    pub error: Element,
    modules: Element,
    completed: Element,
    module_rows: BTreeMap<String, ModuleRow>,
    pending_rows: BTreeMap<String, OperationRow>,
    completed_rows: BTreeMap<String, OperationRow>,
    module_order: Vec<String>,
    pending_order: Vec<String>,
    completed_order: Vec<String>,
    target_order: Vec<String>,
    target_initialized: bool,
    pub trigger: Option<HtmlElement>,
}

pub(crate) struct RenderState<'a> {
    pub destroyed: bool,
    pub connected: bool,
    pub in_flight: bool,
    pub refreshing: bool,
    pub recovery_ready: bool,
    pub recovering: &'a BTreeSet<String>,
}

impl Dom {
    pub fn new(document: Document) -> Result<Self, ControlError> {
        let node = |id: &str| element(&document, id);
        Ok(Self {
            target: cast(node("target-id")?)?,
            reason: cast(node("operation-reason")?)?,
            dialog: cast(node("confirm-operation")?)?,
            confirm: cast(node("confirm-submit")?)?,
            cancel: cast(node("confirm-cancel")?)?,
            start: cast(node("request-start")?)?,
            reconcile: cast(node("request-reconcile")?)?,
            stop: cast(node("request-stop")?)?,
            refresh: cast(node("refresh-view")?)?,
            pending: node("pending-list")?,
            live: cast(node("live-status")?)?,
            error: node("error-status")?,
            modules: node("modules-body")?,
            completed: node("completed-list")?,
            document,
            module_rows: BTreeMap::new(),
            pending_rows: BTreeMap::new(),
            completed_rows: BTreeMap::new(),
            module_order: Vec::new(),
            pending_order: Vec::new(),
            completed_order: Vec::new(),
            target_order: Vec::new(),
            target_initialized: false,
            trigger: None,
        })
    }

    pub fn reset_interaction(&self) {
        self.confirm.set_disabled(false);
        self.reason.set_value("");
        self.target.set_value("");
        if self.dialog.open() {
            self.dialog.close();
        }
    }

    pub fn announce(&self, message: &str) {
        set_text(&self.live, message);
    }
    pub fn show_error(&self, error: &ControlError) {
        let _ = self.error.remove_attribute("hidden");
        set_text(&self.error, &error.to_string());
        self.announce(&error.to_string());
    }
    pub fn clear_error(&self) {
        let _ = self.error.set_attribute("hidden", "");
        set_text(&self.error, "");
    }

    pub fn render(
        &mut self,
        view: &ControlView,
        state: &RenderState<'_>,
    ) -> Result<(), ControlError> {
        self.set(
            "connection-state",
            if view.connected {
                "Connected"
            } else {
                "Disconnected"
            },
        )?;
        self.set(
            "session-state",
            &redact_identifier(view.session_id.as_deref().unwrap_or("")),
        )?;
        self.set("identity-state", view.identity_id.as_deref().unwrap_or("—"))?;
        self.set(
            "generation-state",
            &view
                .snapshot
                .as_ref()
                .map(|s| s.generation().to_string())
                .unwrap_or("—".into()),
        )?;
        self.set(
            "revision-state",
            &view
                .snapshot
                .as_ref()
                .map(|s| s.revision().to_string())
                .unwrap_or("—".into()),
        )?;
        let stale = element(&self.document, "stale-banner")?;
        if view.stale {
            stale.remove_attribute("hidden").map_err(dom_error)?;
            set_text(
                &stale,
                "The displayed runtime view is stale. Control actions are disabled until refresh succeeds.",
            );
        } else {
            stale.set_attribute("hidden", "").map_err(dom_error)?;
            set_text(&stale, "");
        }
        self.render_modules(view)?;
        self.render_operations(&view.pending, state)?;
        self.render_completed(&view.completed)?;
        let disabled = state.destroyed
            || state.in_flight
            || view.stale
            || !view.connected
            || self.target.value().is_empty()
            || !state.recovery_ready;
        let has = |permission: &str| view.permissions.iter().any(|item| item == permission);
        self.start
            .set_disabled(disabled || !has("hepta://ui.control/runtime.start"));
        self.reconcile
            .set_disabled(disabled || !has("hepta://ui.control/runtime.request"));
        self.stop
            .set_disabled(disabled || !has("hepta://ui.control/runtime.stop"));
        self.refresh
            .set_disabled(state.destroyed || state.refreshing || !view.connected);
        if let Some(metrics) = self.document.get_element_by_id("recovery-metrics") {
            set_text(
                &metrics,
                &format!(
                    "Pending age: {} ms; snapshot age: {} ms; unknown: {}; lookup failures: {}; maximum lookup wait: {} ms.",
                    view.pending_max_age_ms,
                    view.snapshot_age_ms
                        .map(|age| age.to_string())
                        .unwrap_or("unknown".into()),
                    view.indeterminate_count,
                    view.recovery_metrics.failures,
                    view.recovery_metrics.max_lookup_wait_ms
                ),
            );
        }
        Ok(())
    }

    fn set(&self, id: &str, text: &str) -> Result<(), ControlError> {
        set_text(&element(&self.document, id)?, text);
        Ok(())
    }

    pub fn open_confirmation(
        &mut self,
        action: &str,
        input: &hepta_control_core::controller::SubmissionInput,
        snapshot: &RuntimeSnapshot,
        trigger: HtmlElement,
    ) -> Result<(), ControlError> {
        self.set(
            "confirm-title",
            match action {
                "request_stop" => "Confirm runtime stop request",
                "request_start" => "Confirm runtime start request",
                _ => "Confirm runtime reconciliation request",
            },
        )?;
        self.set("confirm-summary", &format!("Target: {}. Generation: {}. Revision: {}. Snapshot digest: {}. Operation ID: {}. Reason: {}.",
            input.target_id,snapshot.generation(),snapshot.revision(),redact_digest(snapshot.semantic_digest()),redact_identifier(&input.operation_id),input.reason))?;
        self.trigger = Some(trigger);
        self.dialog.show_modal().map_err(dom_error)?;
        self.cancel.focus().map_err(dom_error)?;
        Ok(())
    }

    pub fn close_confirmation(&mut self) {
        if self.dialog.open() {
            self.dialog.close();
        }
        self.restore_focus();
    }

    pub fn restore_focus(&mut self) {
        if let Some(trigger) = self.trigger.take()
            && trigger.is_connected()
            && !trigger.has_attribute("disabled")
        {
            let _ = trigger.focus();
            return;
        }
        let _ = self.live.set_attribute("tabindex", "-1");
        let _ = self.live.focus();
    }

    pub fn recovery_id(&self, target: &web_sys::EventTarget) -> Option<String> {
        let node = target.dyn_ref::<web_sys::Node>()?;
        self.pending_rows.iter().find_map(|(id, row)| {
            row.button
                .as_ref()
                .filter(|button| button.is_same_node(Some(node)))
                .map(|_| id.clone())
        })
    }
}

pub(crate) fn element(document: &Document, id: &str) -> Result<Element, ControlError> {
    document
        .get_element_by_id(id)
        .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))
}
pub(crate) fn cast<T: JsCast>(element: Element) -> Result<T, ControlError> {
    element.dyn_into().map_err(|_| ControlError::invalid())
}
pub(crate) fn dom_error(_: wasm_bindgen::JsValue) -> ControlError {
    ControlError::new(ErrorCode::InvalidInput)
}
pub(crate) fn set_text(element: &Element, value: &str) {
    if element.text_content().as_deref() != Some(value) {
        element.set_text_content(Some(value));
    }
}
pub(crate) fn redact_identifier(value: &str) -> String {
    if value.is_empty() {
        return "—".into();
    }
    if value.len() <= 4 {
        return "••••".into();
    }
    if value.len() <= 12 {
        return format!("{}…{}", &value[..4], &value[value.len() - 2..]);
    }
    format!("{}…{}", &value[..8], &value[value.len() - 6..])
}
pub(crate) fn redact_digest(value: &str) -> String {
    if value.len() <= 24 {
        return redact_identifier(value);
    }
    format!("{}…{}", &value[..12], &value[value.len() - 8..])
}
fn runtime_status(status: RuntimeStatus) -> &'static str {
    match status {
        RuntimeStatus::Ready => "ready",
        RuntimeStatus::Degraded => "degraded",
        RuntimeStatus::Quarantined => "quarantined",
        RuntimeStatus::Recovering => "recovering",
        RuntimeStatus::Unavailable => "unavailable",
    }
}
fn operation_state(state: OperationState) -> &'static str {
    match state {
        OperationState::Submitting => "submitting",
        OperationState::Pending => "pending",
        OperationState::Indeterminate => "indeterminate",
        OperationState::Terminal => "terminal",
    }
}
