use super::*;
use hepta_control_core::{
    controller::{LookupAdmission, SubmissionAdmission},
    ledger::OperationState,
};
use wasm_bindgen_futures::JsFuture;

pub(super) async fn submit(app: Rc<RefCell<BrowserApp>>) {
    let owner_epoch = app.borrow().epoch;
    let prepared = {
        let mut state = app.borrow_mut();
        if state.destroyed || state.in_flight || state.recovery.is_none() {
            return;
        }
        let Some(input) = state.pending_action.take() else {
            return;
        };
        state.in_flight = true;
        state.dom.confirm.set_disabled(true);
        state.clear_error();
        let admission = state.core.begin_submit(input, now());
        state.render();
        admission.map(|admission| {
            (
                admission,
                state.transport.clone(),
                state.recovery.clone(),
                state.lifecycle.signal(),
                state.epoch,
            )
        })
    };
    let result = match prepared {
        Ok((SubmissionAdmission::New(ticket), transport, Some(store), signal, epoch)) => {
            let record = app.borrow().core.recovery_record(&ticket);
            match record {
                Ok(record) => match store.prepare(&record, Some(signal.clone())).await {
                    Ok(persisted) => {
                        let current = {
                            let mut state = app.borrow_mut();
                            state
                                .active(epoch)
                                .map_err(|error| error.with_dispatch(false))
                                .and_then(|()| state.core.revalidate_dispatch(&ticket, now()))
                        };
                        if let Err(error) = current {
                            let _ = persisted.discard_rejected().await;
                            app.borrow_mut()
                                .core
                                .submission_failed(&ticket, &error, now())
                        } else {
                            let outcome = transport
                                .request(
                                    ticket.request().method(),
                                    &ticket.request().as_value(),
                                    Some(signal),
                                )
                                .await;
                            match outcome {
                                Ok(ack) => {
                                    if hepta_control_core::ledger::validate_response_object(&ack)
                                        .is_ok()
                                        && ack.get("accepted") == Some(&Value::Bool(false))
                                    {
                                        let _ = persisted.discard_rejected().await;
                                    }
                                    app.borrow_mut().core.submission_acknowledged(
                                        &ticket,
                                        &ack,
                                        now(),
                                    )
                                }
                                Err(error) => {
                                    if error.definitely_not_accepted() {
                                        let _ = persisted.discard_rejected().await;
                                    }
                                    app.borrow_mut()
                                        .core
                                        .submission_failed(&ticket, &error, now())
                                }
                            }
                        }
                    }
                    Err(error) => app
                        .borrow_mut()
                        .core
                        .submission_failed(&ticket, &error, now()),
                },
                Err(error) => app.borrow_mut().core.submission_failed(
                    &ticket,
                    &error.with_dispatch(false),
                    now(),
                ),
            }
        }
        Ok((
            SubmissionAdmission::Existing(view) | SubmissionAdmission::InFlight(view),
            _,
            _,
            _,
            _,
        )) => Ok(view),
        Ok((SubmissionAdmission::New(_), _, None, _, _)) => {
            Err(ControlError::unsent(ErrorCode::Storage))
        }
        Err(error) => Err(error),
    };
    if app.borrow().active(owner_epoch).is_err() {
        return;
    }
    {
        let state = app.borrow();
        if !state.destroyed {
            match result {
                Ok(view) => state.dom.announce(&format!(
                    "Submitted {}. Audit trace {}.",
                    redact_identifier(&view.operation_id),
                    redact_identifier(view.audit_trace_id.as_deref().unwrap_or(""))
                )),
                Err(error) => state.show_error(&error),
            }
        }
    }
    maintenance::cleanup(app.clone()).await;
    let mut state = app.borrow_mut();
    if state.active(owner_epoch).is_err() {
        return;
    }
    state.in_flight = false;
    state.dom.confirm.set_disabled(false);
    state.dom.close_confirmation();
    state.render();
}

pub(super) async fn refresh(app: Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let owner_epoch = app.borrow().epoch;
    let prepared = {
        let mut state = app.borrow_mut();
        if state.destroyed || state.refreshing {
            return Ok(());
        }
        state.refreshing = true;
        state.clear_error();
        state.render();
        state.core.session_ticket(now()).map(|ticket| {
            (
                ticket,
                state.transport.clone(),
                state.lifecycle.signal(),
                state.epoch,
            )
        })
    };
    let mut result = match prepared {
        Ok((ticket, transport, signal, epoch)) => match transport
            .read_snapshot(&ticket.request(), Some(signal))
            .await
        {
            Ok(raw) => {
                let mut state = app.borrow_mut();
                state
                    .active(epoch)
                    .and_then(|()| state.core.snapshot_received(&ticket, &raw, now()))
                    .map(|_| ())
            }
            Err(error) => {
                app.borrow_mut().core.snapshot_failed(&ticket, &error);
                Err(error)
            }
        },
        Err(error) => Err(error),
    };
    app.borrow().active(owner_epoch)?;
    if result.is_ok() {
        result = recover_pending(app.clone()).await;
        maintenance::cleanup(app.clone()).await;
    }
    let mut state = app.borrow_mut();
    state.active(owner_epoch)?;
    state.refreshing = false;
    if !state.destroyed {
        if let Err(error) = &result {
            state.show_error(error);
        } else if state.cleanup_error.is_none() {
            state.dom.announce("Runtime view refreshed.");
        }
        state.render();
    }
    result
}

async fn lookup(
    app: Rc<RefCell<BrowserApp>>,
    id: &str,
) -> Result<hepta_control_core::ledger::OperationView, ControlError> {
    let (admission, transport, signal, epoch) = {
        let mut state = app.borrow_mut();
        state.active(state.epoch)?;
        (
            state.core.begin_lookup(id, now())?,
            state.transport.clone(),
            state.lifecycle.signal(),
            state.epoch,
        )
    };
    match admission {
        LookupAdmission::Local(view) => Ok(view),
        LookupAdmission::Query(ticket) => {
            match transport.lookup(&ticket.request(), Some(signal)).await {
                Ok(observation) => {
                    let mut state = app.borrow_mut();
                    state.active(epoch)?;
                    state.core.lookup_received(&ticket, &observation, now())
                }
                Err(error) => {
                    app.borrow_mut().core.lookup_failed(&ticket, &error);
                    Err(error)
                }
            }
        }
    }
}

pub(super) async fn recover_one(app: Rc<RefCell<BrowserApp>>, id: String) {
    let owner_epoch = app.borrow().epoch;
    {
        let mut state = app.borrow_mut();
        if state.destroyed || state.recovering.contains(&id) || !state.core.view(now()).connected {
            return;
        }
        state.recovering.insert(id.clone());
        state.clear_error();
        state.render();
    }
    let result = lookup(app.clone(), &id).await;
    {
        let mut state = app.borrow_mut();
        if state.active(owner_epoch).is_err() {
            return;
        }
        match result {
            Ok(view) => {
                state.core.recovery_observed(&id, view.state, now());
                if !state.destroyed {
                    state.dom.announce(&format!(
                        "Recovered {}: {}.",
                        redact_identifier(&id),
                        if view.state == OperationState::Terminal {
                            "terminal"
                        } else {
                            "pending"
                        }
                    ));
                }
            }
            Err(error) => {
                state.core.recovery_failed(&id, now());
                state.show_error(&error);
            }
        }
    }
    maintenance::cleanup(app.clone()).await;
    let mut state = app.borrow_mut();
    if state.active(owner_epoch).is_err() {
        return;
    }
    state.recovering.remove(&id);
    state.render();
}

async fn recover_pending(app: Rc<RefCell<BrowserApp>>) -> Result<(), ControlError> {
    let owner_epoch = app.borrow().epoch;
    let failure: Rc<RefCell<Option<ControlError>>> = Rc::new(RefCell::new(None));
    let started = now();
    let ids = {
        let mut state = app.borrow_mut();
        state.core.select_recovery(started)
    };
    // At most four simultaneous read-only lookups; each batch remains bounded to 32.
    for chunk in ids.chunks(4) {
        app.borrow().active(owner_epoch)?;
        if let Some(error) = failure.borrow().clone() {
            return Err(error);
        }
        let jobs = js_sys::Array::new();
        for id in chunk {
            let app = app.clone();
            let id = id.clone();
            let failure = failure.clone();
            let duplicate = {
                let mut state = app.borrow_mut();
                if state.destroyed || state.recovering.contains(&id) {
                    true
                } else {
                    state.recovering.insert(id.clone());
                    false
                }
            };
            if duplicate {
                continue;
            }
            jobs.push(&future_to_promise(async move {
                let result = lookup(app.clone(), &id).await;
                let mut state = app.borrow_mut();
                if state.active(owner_epoch).is_err() {
                    return Ok(JsValue::UNDEFINED);
                }
                match result {
                    Ok(view) => state.core.recovery_observed(&id, view.state, now()),
                    Err(error) => {
                        state.core.recovery_failed(&id, now());
                        if hepta_control_core::scheduler::is_fatal_recovery_error(&error)
                            || (error.code == ErrorCode::Aborted
                                && state.lifecycle.signal().aborted())
                        {
                            state.show_error(&error);
                            *failure.borrow_mut() = Some(error);
                        }
                    }
                }
                state.recovering.remove(&id);
                Ok(JsValue::UNDEFINED)
            }));
        }
        let _ = JsFuture::from(Promise::all(&jobs)).await;
        if !app.borrow_mut().core.view(now()).connected {
            break;
        }
    }
    let mut state = app.borrow_mut();
    state.active(owner_epoch)?;
    state.core.recovery_batch_finished(started, now());
    if let Some(error) = failure.borrow().clone() {
        Err(error)
    } else {
        Ok(())
    }
}
