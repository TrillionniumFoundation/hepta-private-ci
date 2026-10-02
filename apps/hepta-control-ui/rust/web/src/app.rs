//! Browser lifecycle orchestration. Only generation-bound core effects cross adapters.
use crate::{
    dom::{Dom, RenderState, dom_error, element, redact_identifier},
    recovery::ScopedRecoveryStore,
    transport::SameOriginHttpTransport,
};
use hepta_control_core::{
    chat::{AppTab, ChatState},
    controller::{Controller, SubmissionInput},
    error::{ControlError, ErrorCode},
    projection::Action,
};
use js_sys::{Object, Promise, Reflect};
use serde_json::{Value, json};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
};
use wasm_bindgen::{JsCast, JsValue, closure::Closure, prelude::wasm_bindgen};
use wasm_bindgen_futures::{future_to_promise, spawn_local};
use web_sys::{AbortController, Document, Event, EventTarget, HtmlElement, Window};

mod chat;
mod effects;
mod lifecycle;
mod maintenance;

thread_local! {
    static APP: RefCell<Option<Rc<RefCell<BrowserApp>>>> = const { RefCell::new(None) };
    static START: RefCell<Option<Promise>> = const { RefCell::new(None) };
    static DESTROY: RefCell<Option<Promise>> = const { RefCell::new(None) };
}

struct BrowserApp {
    window: Window,
    core: Controller,
    chat: ChatState,
    chat_host: chat::ChatHost,
    chat_rendered: Option<ChatState>,
    dom: Dom,
    transport: Rc<SameOriginHttpTransport>,
    recovery: Option<Rc<ScopedRecoveryStore>>,
    recovery_error: Option<ControlError>,
    cleanup_error: Option<ControlError>,
    cleanup_outstanding: BTreeMap<String, Value>,
    cleanup_success: BTreeMap<String, Value>,
    cleanup_running: bool,
    cleanup_cursor: Option<String>,
    pending_action: Option<SubmissionInput>,
    in_flight: bool,
    refreshing: bool,
    next_poll_at: u64,
    recovering: BTreeSet<String>,
    session_refreshing: bool,
    session_failures: u32,
    next_session_refresh: u64,
    destroyed: bool,
    epoch: u64,
    lifecycle: AbortController,
    listeners: Vec<Listener>,
    timer: Option<i32>,
    timer_callback: Option<Closure<dyn FnMut()>>,
    session_timer: Option<i32>,
    session_timer_callback: Option<Closure<dyn FnMut()>>,
}

impl BrowserApp {
    fn render(&mut self) {
        if self.destroyed {
            return;
        }
        let view = self.core.view(now());
        if !view.connected {
            self.chat.reset_session();
            self.chat_host = chat::ChatHost::default();
        }
        let _ = crate::shell::render(
            &self.dom.document,
            &self.chat,
            self.chat_rendered.as_ref(),
            &self.chat_host.note,
            self.chat_host.show_list,
        );
        self.chat_rendered = Some(self.chat.clone());
        chat::render_actions(&self.dom.document, &self.chat_host, &self.chat);
        let _ = self.dom.render(
            &view,
            &RenderState {
                destroyed: self.destroyed,
                connected: view.connected,
                in_flight: self.in_flight,
                refreshing: self.refreshing,
                recovery_ready: self.recovery.is_some(),
                recovering: &self.recovering,
            },
        );
    }
    fn show_error(&self, error: &ControlError) {
        if !self.destroyed {
            self.dom.show_error(error);
        }
    }
    fn clear_error(&self) {
        if !self.destroyed {
            if let Some(error) = self.recovery_error.as_ref().or(self.cleanup_error.as_ref()) {
                self.dom.show_error(error);
            } else {
                self.dom.clear_error();
            }
        }
    }
    fn active(&self, epoch: u64) -> Result<(), ControlError> {
        if self.destroyed || self.epoch != epoch {
            Err(ControlError::new(ErrorCode::Aborted))
        } else {
            Ok(())
        }
    }
    fn input(&mut self, action: Action) -> Result<SubmissionInput, ControlError> {
        let view = self.core.view(now());
        let snapshot = view
            .snapshot
            .ok_or_else(|| ControlError::new(ErrorCode::StaleRevision))?;
        let crypto = self.window.crypto().map_err(dom_error)?;
        let input = SubmissionInput {
            operation_id: format!("ui:{}", crypto.random_uuid()),
            action,
            target_id: self.dom.target.value(),
            reason: reason_text(&self.dom.reason)?,
            displayed_revision: snapshot.revision(),
            semantic_digest: None,
            confirmation: None,
        };
        if input.target_id.is_empty() || input.reason.is_empty() {
            return Err(ControlError::invalid());
        }
        Ok(input)
    }
}

/// Canonical Rust browser entry, invoked by the minimal fail-closed WASM loader.
#[wasm_bindgen]
pub fn start() -> Promise {
    if let Some(existing) = START.with(|value| value.borrow().clone()) {
        return existing;
    }
    let promise = future_to_promise(async {
        let app = create_app().map_err(js_error)?;
        APP.with(|value| *value.borrow_mut() = Some(app.clone()));
        let result = lifecycle::start_once(app.clone()).await;
        match result {
            Ok(()) => {
                lifecycle::publish_readiness(&app, "ready", None);
                Ok(JsValue::UNDEFINED)
            }
            Err(error) => {
                app.borrow().show_error(&error);
                let authenticated = app.borrow_mut().core.view(now()).connected;
                if !authenticated
                    && let Ok(node) = element(&app.borrow().dom.document, "startup-error")
                {
                    node.set_text_content(Some("An authenticated workspace session is required. Messaging and console actions are unavailable."));
                    let _ = node.remove_attribute("hidden");
                }
                lifecycle::publish_readiness(&app, "failed", Some(error.code));
                web_sys::console::error_2(
                    &JsValue::from_str("ui.control console failed to start"),
                    &JsValue::from_str(error.code.as_str()),
                );
                Err(js_error(error))
            }
        }
    });
    START.with(|value| *value.borrow_mut() = Some(promise.clone()));
    promise
}

#[wasm_bindgen]
pub fn destroy() -> Promise {
    if let Some(existing) = DESTROY.with(|value| value.borrow().clone()) {
        return existing;
    }
    let promise = future_to_promise(async {
        if let Some(app) = APP.with(|value| value.borrow().clone()) {
            lifecycle::destroy_once(app).await.map_err(js_error)?;
        }
        Ok(JsValue::UNDEFINED)
    });
    DESTROY.with(|value| *value.borrow_mut() = Some(promise.clone()));
    promise
}

/// Close local session authority while preserving the canonical in-memory recovery ledger.
#[wasm_bindgen]
pub fn close_session() -> Promise {
    future_to_promise(async {
        let app = APP
            .with(|value| value.borrow().clone())
            .ok_or_else(|| js_error(ControlError::new(ErrorCode::NotConnected)))?;
        lifecycle::close_session(app).await.map_err(js_error)?;
        Ok(JsValue::UNDEFINED)
    })
}

/// Reopen the same controller under a fresh authenticated observation session.
#[wasm_bindgen]
pub fn reconnect() -> Promise {
    future_to_promise(async {
        let app = APP
            .with(|value| value.borrow().clone())
            .ok_or_else(|| js_error(ControlError::new(ErrorCode::NotConnected)))?;
        {
            let state = app.borrow();
            state.active(state.epoch).map_err(js_error)?;
        }
        lifecycle::start_once(app.clone()).await.map_err(js_error)?;
        lifecycle::publish_readiness(&app, "ready", None);
        Ok(JsValue::UNDEFINED)
    })
}

/// Read-only presentation export. Full correlation values are never inserted into DOM attributes.
#[wasm_bindgen]
pub fn read_view() -> Result<JsValue, JsValue> {
    let app = APP
        .with(|value| value.borrow().clone())
        .ok_or_else(|| js_error(ControlError::new(ErrorCode::NotConnected)))?;
    let mut state = app
        .try_borrow_mut()
        .map_err(|_| js_error(ControlError::new(ErrorCode::Aborted)))?;
    let value = serde_json::to_string(&state.core.view(now()))
        .map_err(|_| js_error(ControlError::invalid()))?;
    js_sys::JSON::parse(&value).map_err(|_| js_error(ControlError::invalid()))
}

fn create_app() -> Result<Rc<RefCell<BrowserApp>>, ControlError> {
    let window = web_sys::window().ok_or_else(ControlError::invalid)?;
    let document = window.document().ok_or_else(ControlError::invalid)?;
    crate::shell::mount(&document)?;
    let dom = Dom::new(document.clone())?;
    dom.reset_interaction();
    let csrf_document = document.clone();
    let csrf = Rc::new(move || {
        csrf_document
            .query_selector("meta[name=\"csrf-token\"]")
            .ok()
            .flatten()
            .and_then(|element| element.get_attribute("content"))
            .filter(|value| !value.is_empty())
    });
    let transport = Rc::new(SameOriginHttpTransport::new(
        "/api/ui-control/v1/",
        csrf,
        15_000,
    )?);
    let app = Rc::new(RefCell::new(BrowserApp {
        window,
        core: Controller::new(1024)?,
        chat: ChatState::default(),
        chat_host: chat::ChatHost::default(),
        chat_rendered: None,
        dom,
        transport,
        recovery: None,
        recovery_error: None,
        cleanup_error: None,
        cleanup_outstanding: BTreeMap::new(),
        cleanup_success: BTreeMap::new(),
        cleanup_running: false,
        cleanup_cursor: None,
        pending_action: None,
        in_flight: false,
        refreshing: false,
        next_poll_at: 0,
        recovering: BTreeSet::new(),
        session_refreshing: false,
        session_failures: 0,
        next_session_refresh: 0,
        destroyed: false,
        epoch: 0,
        lifecycle: AbortController::new().map_err(dom_error)?,
        listeners: Vec::new(),
        timer: None,
        timer_callback: None,
        session_timer: None,
        session_timer_callback: None,
    }));
    attach_events(&app, &document)?;
    lifecycle::publish_readiness(&app, "booting", None);
    Ok(app)
}

fn attach_events(app: &Rc<RefCell<BrowserApp>>, document: &Document) -> Result<(), ControlError> {
    for (id, tab) in [("tab-chat", AppTab::Chat), ("tab-console", AppTab::Console)] {
        let weak = Rc::downgrade(app);
        listen(app, element(document, id)?.as_ref(), "click", move |_| {
            if let Some(app) = weak.upgrade() {
                let mut state = app.borrow_mut();
                if state.destroyed || state.dom.dialog.open() {
                    return;
                }
                state.chat.tab = tab;
                state.render();
            }
        })?;
    }

    for (id, action) in [
        ("request-start", Action::RequestStart),
        ("request-reconcile", Action::RequestReconcile),
        ("request-stop", Action::RequestStop),
    ] {
        let weak = Rc::downgrade(app);
        let node = element(document, id)?;
        listen(app, node.as_ref(), "click", move |event| {
            if let Some(app) = weak.upgrade() {
                open_confirmation(&app, action, event);
            }
        })?;
    }
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "confirm-submit")?.as_ref(),
        "click",
        move |_| {
            if let Some(app) = weak.upgrade() {
                spawn_local(effects::submit(app));
            }
        },
    )?;
    for (id, event_name) in [("confirm-cancel", "click"), ("confirm-operation", "cancel")] {
        let weak = Rc::downgrade(app);
        listen(
            app,
            element(document, id)?.as_ref(),
            event_name,
            move |event| {
                event.prevent_default();
                if let Some(app) = weak.upgrade() {
                    let mut state = app.borrow_mut();
                    if state.destroyed {
                        return;
                    }
                    state.pending_action = None;
                    state.dom.close_confirmation();
                }
            },
        )?;
    }
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "refresh-view")?.as_ref(),
        "click",
        move |_| {
            if let Some(app) = weak.upgrade() {
                spawn_local(async move {
                    let _ = effects::refresh(app).await;
                });
            }
        },
    )?;
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "pending-list")?.as_ref(),
        "click",
        move |event| {
            if let Some(app) = weak.upgrade() {
                let id = event
                    .target()
                    .and_then(|target| app.borrow().dom.recovery_id(&target));
                if let Some(id) = id {
                    spawn_local(async move {
                        effects::recover_one(app, id).await;
                    });
                }
            }
        },
    )?;
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "target-id")?.as_ref(),
        "change",
        move |_| {
            if let Some(app) = weak.upgrade() {
                app.borrow_mut().render();
            }
        },
    )?;
    chat::attach(app, document)?;
    let window = app.borrow().window.clone();
    listen(app, window.as_ref(), "pagehide", move |_| {
        let _ = destroy();
    })?;
    let window_copy = window.clone();
    listen(app, window.as_ref(), "pageshow", move |event| {
        if event
            .dyn_ref::<web_sys::PageTransitionEvent>()
            .is_some_and(web_sys::PageTransitionEvent::persisted)
        {
            let _ = window_copy.location().reload();
        }
    })?;
    Ok(())
}

fn open_confirmation(app: &Rc<RefCell<BrowserApp>>, action: Action, event: Event) {
    let mut state = app.borrow_mut();
    if state.destroyed
        || state.in_flight
        || state.pending_action.is_some()
        || state.recovery.is_none()
    {
        return;
    }
    state.clear_error();
    let result = (|| {
        let mut input = state.input(action)?;
        input.confirmation = Some(state.core.capture_confirmation(&input, now())?);
        let snapshot = state
            .core
            .view(now())
            .snapshot
            .ok_or_else(ControlError::invalid)?;
        let trigger = event
            .current_target()
            .and_then(|target| target.dyn_into::<HtmlElement>().ok())
            .ok_or_else(ControlError::invalid)?;
        state
            .dom
            .open_confirmation(action.as_str(), &input, &snapshot, trigger)?;
        state.pending_action = Some(input);
        Ok(())
    })();
    if let Err(error) = result {
        state.show_error(&error);
    }
}

struct Listener {
    target: EventTarget,
    name: String,
    callback: Closure<dyn FnMut(Event)>,
}
impl Drop for Listener {
    fn drop(&mut self) {
        let _ = self.target.remove_event_listener_with_callback(
            &self.name,
            self.callback.as_ref().unchecked_ref(),
        );
    }
}
fn listen(
    app: &Rc<RefCell<BrowserApp>>,
    target: &EventTarget,
    name: &str,
    callback: impl FnMut(Event) + 'static,
) -> Result<(), ControlError> {
    let callback = Closure::wrap(Box::new(callback) as Box<dyn FnMut(Event)>);
    target
        .add_event_listener_with_callback(name, callback.as_ref().unchecked_ref())
        .map_err(dom_error)?;
    app.borrow_mut().listeners.push(Listener {
        target: target.clone(),
        name: name.to_owned(),
        callback,
    });
    Ok(())
}
fn reason_text(element: &web_sys::HtmlTextAreaElement) -> Result<String, ControlError> {
    let raw = Reflect::get(element.as_ref(), &JsValue::from_str("value")).map_err(dom_error)?;
    let raw = raw
        .dyn_into::<js_sys::JsString>()
        .map_err(|_| ControlError::invalid())?;
    if !raw.is_valid_utf16() {
        return Err(ControlError::invalid());
    }
    let value: String = raw.into();
    Ok(value
        .trim_matches(crate::transport::js_whitespace)
        .to_owned())
}

fn now() -> u64 {
    js_sys::Date::now().max(1.0) as u64
}
fn js_error(error: ControlError) -> JsValue {
    let result = js_sys::Error::new(error.code.message());
    let _ = Reflect::set(&result, &"code".into(), &error.code.as_str().into());
    let _ = Reflect::set(&result, &"retryable".into(), &error.retryable.into());
    result.into()
}
