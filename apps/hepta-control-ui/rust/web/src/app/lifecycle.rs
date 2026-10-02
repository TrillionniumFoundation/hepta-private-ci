use super::*;
use hepta_control_core::projection::PROTOCOL_VERSION;
use wasm_bindgen_futures::JsFuture;

pub(super) async fn start_once(app: Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let (ticket, transport, signal, epoch) = {
        let mut state = app.borrow_mut();
        (
            state.core.begin_connect()?,
            state.transport.clone(),
            state.lifecycle.signal(),
            state.epoch,
        )
    };
    let raw = transport
        .connect(
            &json!({"protocolVersion":PROTOCOL_VERSION,"client":"hepta-control-ui",
        "requestedCapabilities":["runtime.read","runtime.request","runtime.start","runtime.stop"]}),
            Some(signal),
        )
        .await?;
    let adopted = {
        let mut state = app.borrow_mut();
        state
            .active(epoch)
            .and_then(|()| state.core.connected(&ticket, &raw, now()))
    };
    if let Err(error) = adopted {
        let _ = transport.close(&raw, None).await;
        return Err(error);
    }
    spawn_local(chat::load(app.clone()));
    restore_recovery(&app, epoch).await;
    app.borrow().active(epoch)?;
    let console_result = effects::refresh(app.clone()).await;
    let console_unavailable = console_result.as_ref().is_err_and(|error| {
        error.code == ErrorCode::PermissionDenied && error.request_dispatched == Some(false)
    });
    app.borrow().active(epoch)?;
    schedule_poll(&app)?;
    {
        let mut state = app.borrow_mut();
        schedule_session(&mut state);
        state.render();
        if let Some(error) = state
            .cleanup_error
            .as_ref()
            .or(state.recovery_error.as_ref())
        {
            state.dom.show_error(error);
        } else {
            state.dom.announce("ui.control console connected.");
        }
    }
    arm_session_timer(&app)?;
    if console_unavailable {
        app.borrow()
            .dom
            .show_error(&ControlError::unsent(ErrorCode::PermissionDenied));
        Ok(())
    } else {
        console_result
    }
}

async fn restore_recovery(app: &Rc<RefCell<BrowserApp>>, epoch: u64) {
    let binding = {
        let mut state = app.borrow_mut();
        let view = state.core.view(now());
        view.identity_id
            .map(|identity| (state.transport.endpoint().to_owned(), identity))
    };
    let result = async {
        let (endpoint, identity) = binding.ok_or_else(ControlError::invalid)?;
        let store =
            ScopedRecoveryStore::create(&endpoint, &identity, PROTOCOL_VERSION, "default", 1024)
                .await?;
        let mut state = app.borrow_mut();
        state.active(epoch)?;
        if state.core.view(now()).identity_id.as_deref() != Some(identity.as_str()) {
            return Err(ControlError::unsent(ErrorCode::Storage));
        }
        state.core.restore_recovery(&store.load()?)?;
        state.core.persistence_changed()?;
        state.recovery = Some(Rc::new(store));
        state.recovery_error = None;
        if state
            .window
            .local_storage()
            .ok()
            .flatten()
            .and_then(|storage| {
                storage
                    .get_item("hepta.ui-control.recovery-state.v1")
                    .ok()
                    .flatten()
            })
            .is_some()
        {
            // Never assign unscoped predecessor records to the new authenticated principal.
            let error = ControlError::new(ErrorCode::Storage);
            state.recovery_error = Some(error.clone());
            state.show_error(&error);
        }
        Ok(())
    }
    .await;
    if let Err(error) = result {
        let mut state = app.borrow_mut();
        if state.active(epoch).is_ok() {
            let error = ControlError::unsent(ErrorCode::Storage)
                .retryable(true)
                .detail("causeCode", json!(error.code.as_str()));
            state.recovery = None;
            state.recovery_error = Some(error.clone());
            state.show_error(&error);
        }
    }
}

fn schedule_poll(app: &Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    if app.borrow().timer.is_some() {
        return Ok(());
    }
    let weak = Rc::downgrade(app);
    let callback = Closure::wrap(Box::new(move || {
        if let Some(app) = weak.upgrade() {
            let should_run = {
                let state = app.borrow();
                !state.destroyed
                    && now() >= state.next_poll_at
                    && !state.dom.document.hidden()
                    && state.window.navigator().on_line()
            };
            if !should_run {
                return;
            }
            spawn_local(async move {
                chat::poll(app.clone()).await;
                let _ = effects::refresh(app).await;
            });
        }
    }) as Box<dyn FnMut()>);
    let mut state = app.borrow_mut();
    let timer = state
        .window
        .set_interval_with_callback_and_timeout_and_arguments_0(
            callback.as_ref().unchecked_ref(),
            2000,
        )
        .map_err(dom_error)?;
    state.timer = Some(timer);
    state.timer_callback = Some(callback);
    Ok(())
}

fn schedule_session(state: &mut BrowserApp) {
    let current = now();
    let view = state.core.view(current);
    state.next_session_refresh = if let Some(expiry) = view.expires_at {
        let delay = if state.session_failures > 0 {
            1000_u64
                .saturating_mul(1_u64 << state.session_failures.saturating_sub(1).min(6))
                .min(60_000)
        } else {
            expiry
                .saturating_sub(current)
                .saturating_sub(60_000)
                .max(1000)
        };
        current.saturating_add(delay.min(expiry.saturating_sub(current)))
    } else {
        u64::MAX
    };
}

fn arm_session_timer(app: &Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let weak = Rc::downgrade(app);
    let mut state = app.borrow_mut();
    if let Some(timer) = state.session_timer.take() {
        state.window.clear_timeout_with_handle(timer);
    }
    state.session_timer_callback = None;
    if state.destroyed || state.next_session_refresh == u64::MAX {
        return Ok(());
    }
    let delay = state
        .next_session_refresh
        .saturating_sub(now())
        .min(2_147_000_000) as i32;
    let callback = Closure::wrap(Box::new(move || {
        if let Some(app) = weak.upgrade() {
            spawn_local(async move {
                refresh_session(app).await;
            });
        }
    }) as Box<dyn FnMut()>);
    let timer = state
        .window
        .set_timeout_with_callback_and_timeout_and_arguments_0(
            callback.as_ref().unchecked_ref(),
            delay,
        )
        .map_err(dom_error)?;
    state.session_timer = Some(timer);
    state.session_timer_callback = Some(callback);
    Ok(())
}

async fn refresh_session(app: Rc<RefCell<BrowserApp>>) {
    let owner_epoch = app.borrow().epoch;
    let preparation = {
        let mut state = app.borrow_mut();
        if state.destroyed || state.session_refreshing {
            return;
        }
        state.session_refreshing = true;
        state.core.authentication_ticket(now()).map(|ticket| {
            (
                ticket,
                state.transport.clone(),
                state.lifecycle.signal(),
                state.epoch,
            )
        })
    };
    let result = match preparation {
        Ok((ticket, transport, signal, epoch)) => match transport
            .refresh(&json!(ticket.session()), Some(signal))
            .await
        {
            Ok(raw) => {
                let mut state = app.borrow_mut();
                state
                    .active(epoch)
                    .and_then(|()| state.core.session_refreshed(&ticket, &raw, now()))
                    .map(|_| ())
            }
            Err(error) => {
                app.borrow_mut().core.session_failed(&ticket, &error);
                Err(error)
            }
        },
        Err(error) => Err(error),
    };
    // SessionProvider parity: every authority-loss classification closes local authority,
    // including a missing CSRF token that produced no HTTP response.
    if result.as_ref().err().is_some_and(|error| {
        matches!(
            error.code,
            ErrorCode::SessionExpired
                | ErrorCode::SessionRevoked
                | ErrorCode::SessionIdentityChanged
                | ErrorCode::PermissionDenied
                | ErrorCode::StalePermissionRevision
                | ErrorCode::ProtocolMismatch
        )
    }) {
        let close = {
            let mut state = app.borrow_mut();
            if state.active(owner_epoch).is_err() {
                return;
            }
            state
                .core
                .close()
                .map(|session| (state.transport.clone(), session))
        };
        if let Some((transport, session)) = close {
            let _ = transport.close(&json!(session), None).await;
        }
    }
    let mut state = app.borrow_mut();
    if state.active(owner_epoch).is_err() {
        return;
    }
    state.session_refreshing = false;
    match result {
        Ok(()) => state.session_failures = 0,
        Err(error) => {
            state.session_failures = state.session_failures.saturating_add(1);
            state.show_error(&error);
        }
    }
    schedule_session(&mut state);
    state.render();
    drop(state);
    let _ = arm_session_timer(&app);
}

pub(super) async fn close_session(app: Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let (session, transport) = {
        let mut state = app.borrow_mut();
        state.active(state.epoch)?;
        state.epoch = state.epoch.saturating_add(1);
        state.chat.reset_session();
        state.chat_host = chat::ChatHost::default();
        state.lifecycle.abort();
        state.lifecycle = AbortController::new().map_err(dom_error)?;
        if let Some(timer) = state.timer.take() {
            state.window.clear_interval_with_handle(timer);
        }
        state.timer_callback = None;
        if let Some(timer) = state.session_timer.take() {
            state.window.clear_timeout_with_handle(timer);
        }
        state.session_timer_callback = None;
        state.pending_action = None;
        state.in_flight = false;
        state.refreshing = false;
        state.session_refreshing = false;
        state.recovering.clear();
        state.dom.confirm.set_disabled(false);
        state.dom.close_confirmation();
        state.recovery = None;
        state.recovery_error = None;
        state.cleanup_error = None;
        state.cleanup_outstanding.clear();
        state.cleanup_success.clear();
        state.session_failures = 0;
        state.next_session_refresh = u64::MAX;
        let session = state.core.close();
        state.render();
        (session, state.transport.clone())
    };
    while app.borrow().cleanup_running {
        tick().await;
    }
    if let Some(session) = session {
        transport.close(&json!(session), None).await?;
    }
    Ok(())
}

pub(super) async fn destroy_once(app: Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let (session, transport) = {
        let mut state = app.borrow_mut();
        if state.destroyed {
            return Ok(());
        }
        state.destroyed = true;
        state.epoch = state.epoch.saturating_add(1);
        state.chat.reset_session();
        state.chat_host = chat::ChatHost::default();
        state.lifecycle.abort();
        if let Some(timer) = state.timer.take() {
            state.window.clear_interval_with_handle(timer);
        }
        state.timer_callback = None;
        if let Some(timer) = state.session_timer.take() {
            state.window.clear_timeout_with_handle(timer);
        }
        state.session_timer_callback = None;
        state.listeners.clear();
        state.pending_action = None;
        let session = state.core.close();
        (session, state.transport.clone())
    };
    while app.borrow().cleanup_running {
        tick().await;
    }
    if let Some(session) = session {
        transport.close(&json!(session), None).await?;
    }
    // A disposed instance never touches a replacement's controls or live regions.
    Ok(())
}

pub(super) fn publish_readiness(
    app: &Rc<RefCell<BrowserApp>>,
    phase: &str,
    error: Option<ErrorCode>,
) {
    let state = app.borrow();
    let global = js_sys::global();
    let key = JsValue::from_str("__heptaUiControlReadiness");
    let existing = Reflect::get(&global, &key).unwrap_or(JsValue::UNDEFINED);
    let receipt = if existing.is_object() {
        existing
    } else {
        let receipt = Object::new();
        let tab = state
            .window
            .crypto()
            .map(|crypto| format!("tab:{}", crypto.random_uuid()))
            .unwrap_or_else(|_| "tab:unavailable".into());
        let data = json!({"schema":"hepta.ui-control.readiness.v1","phase":"booting","tabId":tab,
            "startedAt":js_sys::Date::new_0().to_iso_string().as_string(),"readyAt":null,"failedAt":null,"errorCode":null,
            "stateOwnership":{"activeSession":"tab-private","selectionAndFocus":"tab-private",
                "recoveryRecords":"endpoint-protocol-identity-scoped-cross-tab","leaderAndClaims":"scope-scoped-cross-tab",
                "credentials":"memory-only-never-broadcast-or-persisted"}});
        if let Ok(value) = js_sys::JSON::parse(&data.to_string()) {
            let _ = Object::assign(&receipt, &value.unchecked_into::<Object>());
        }
        let descriptor = Object::new();
        let _ = Reflect::set(&descriptor, &"value".into(), &receipt);
        let _ = Reflect::set(&descriptor, &"writable".into(), &JsValue::FALSE);
        let _ = Reflect::set(&descriptor, &"configurable".into(), &JsValue::FALSE);
        Object::define_property(&global, &key, &descriptor);
        receipt.into()
    };
    let _ = Reflect::set(&receipt, &"phase".into(), &phase.into());
    if let Some(error) = error {
        let _ = Reflect::set(&receipt, &"errorCode".into(), &error.as_str().into());
    }
    if phase == "ready" || phase == "failed" {
        let time_key = if phase == "ready" {
            "readyAt"
        } else {
            "failedAt"
        };
        let _ = Reflect::set(
            &receipt,
            &time_key.into(),
            &js_sys::Date::new_0().to_iso_string(),
        );
    }
    if let Some(root) = state.dom.document.document_element() {
        let _ = root.set_attribute(
            "data-ui-control-ready",
            if phase == "ready" { "true" } else { phase },
        );
    }
    let init = web_sys::CustomEventInit::new();
    let copied = js_sys::JSON::stringify(&receipt)
        .ok()
        .and_then(|text| text.as_string())
        .and_then(|text| js_sys::JSON::parse(&text).ok())
        .unwrap_or(JsValue::NULL);
    if let Some(object) = copied.dyn_ref::<Object>() {
        Object::freeze(object);
    }
    init.set_detail(&copied);
    let window = state.window.clone();
    drop(state);
    if let Ok(event) =
        web_sys::CustomEvent::new_with_event_init_dict(&format!("hepta:ui-control:{phase}"), &init)
    {
        let _ = window.dispatch_event(&event);
    }
}

pub(super) async fn tick() {
    let promise = Promise::new(&mut |resolve, _reject| {
        if let Some(window) = web_sys::window() {
            let _ = window.set_timeout_with_callback_and_timeout_and_arguments_0(&resolve, 0);
        }
    });
    let _ = JsFuture::from(promise).await;
}
