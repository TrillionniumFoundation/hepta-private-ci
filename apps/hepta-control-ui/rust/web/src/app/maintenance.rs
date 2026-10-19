use super::*;
use crate::transport::deadline::Deadline;

pub(super) async fn cleanup(app: Rc<RefCell<BrowserApp>>) {
    // Join an existing settlement. Do not accidentally clear an outstanding error.
    if app.borrow().cleanup_running {
        while app.borrow().cleanup_running {
            lifecycle::tick().await;
        }
        return;
    }
    let prepared = {
        let mut state = app.borrow_mut();
        if state.destroyed {
            return;
        }
        let Some(store) = state.recovery.clone() else {
            return;
        };
        let completed = state.core.view(now()).completed;
        let live: BTreeSet<_> = completed
            .iter()
            .map(|item| item.operation_id.clone())
            .collect();
        state.cleanup_success.retain(|id, _| live.contains(id));
        for item in completed {
            let value = json!(item);
            if state.cleanup_success.get(&item.operation_id) != Some(&value) {
                state.cleanup_outstanding.insert(item.operation_id, value);
            }
        }
        if state.cleanup_outstanding.len() > 4096 {
            let error = ControlError::new(ErrorCode::Storage);
            state.cleanup_error = Some(error.clone());
            state.show_error(&error);
            return;
        }
        if state.cleanup_outstanding.is_empty() {
            clear_settled_error(&mut state);
            return;
        }
        let mut ids: Vec<_> = state.cleanup_outstanding.keys().cloned().collect();
        if let Some(cursor) = &state.cleanup_cursor {
            let offset = ids.iter().position(|id| id > cursor).unwrap_or(0);
            ids.rotate_left(offset);
        }
        ids.truncate(32);
        state.cleanup_running = true;
        (store, ids, state.lifecycle.signal(), state.epoch)
    };
    let (store, ids, signal, epoch) = prepared;
    let deadline = Deadline::new(Some(signal), 5000);
    let mut failed = false;
    match deadline {
        Ok(deadline) => {
            for id in ids {
                let value = {
                    let mut state = app.borrow_mut();
                    if state.active(epoch).is_err() {
                        break;
                    }
                    state.cleanup_cursor = Some(id.clone());
                    state.cleanup_outstanding.get(&id).cloned()
                };
                let Some(value) = value else {
                    continue;
                };
                let result = store.complete(&value, Some(deadline.signal())).await;
                let mut state = app.borrow_mut();
                if state.active(epoch).is_err() {
                    break;
                }
                match result {
                    Ok(_) => {
                        if state.cleanup_outstanding.get(&id) == Some(&value) {
                            state.cleanup_outstanding.remove(&id);
                            state.cleanup_success.insert(id, value);
                        }
                    }
                    Err(_) => {
                        failed = true;
                        let error = ControlError::new(ErrorCode::Storage).retryable(true);
                        state.cleanup_error = Some(error.clone());
                        state.show_error(&error);
                    }
                }
            }
        }
        Err(_) => failed = true,
    }
    let mut state = app.borrow_mut();
    state.cleanup_running = false;
    if state.active(epoch).is_err() {
        return;
    }
    if !failed && state.cleanup_outstanding.is_empty() {
        clear_settled_error(&mut state);
    } else if failed {
        let error = ControlError::new(ErrorCode::Storage).retryable(true);
        state.cleanup_error = Some(error.clone());
        state.show_error(&error);
    }
}

// Cleanup owns only its own alert. A no-op settlement must not erase a newer
// submission/storage/confirmation error displayed by another operation.
fn clear_settled_error(state: &mut BrowserApp) {
    if let Some(error) = state.cleanup_error.take()
        && state.dom.error.text_content().as_deref() == Some(error.to_string().as_str())
    {
        state.clear_error();
    }
}
