//! UI task handoff. Browser SDK objects remain on the browser's owning thread.
//! Native dispatch keeps Makepad's existing cross-thread Send requirement.
use makepad_widgets::{ActionTrait, Cx};
#[cfg(any(target_family = "wasm", test))]
use makepad_widgets::Action;

#[cfg(any(target_family = "wasm", test))]
const MAX_PENDING_ACTIONS: usize = 512;

#[cfg(any(target_family = "wasm", test))]
struct LocalActions {
    epoch: u64,
    pending: Vec<Action>,
    overflowed: bool,
    reported: bool,
}
#[cfg(any(target_family = "wasm", test))]
impl LocalActions {
    fn new() -> Self { Self { epoch: 0, pending: Vec::new(), overflowed: false, reported: false } }
    fn push(&mut self, epoch: u64, action: Action) {
        if epoch != self.epoch || self.overflowed { return; }
        if self.pending.len() >= MAX_PENDING_ACTIONS {
            self.pending.clear();
            self.overflowed = true;
            return;
        }
        self.pending.push(action);
    }
    fn advance(&mut self) -> u64 {
        self.epoch = self.epoch.checked_add(1).expect("UI session epoch exhausted");
        self.pending.clear();
        self.overflowed = false;
        self.reported = false;
        self.epoch
    }
}

#[cfg(target_family = "wasm")]
thread_local! {
    static ACTIONS: std::cell::RefCell<LocalActions> = std::cell::RefCell::new(LocalActions::new());
}
#[cfg(target_family = "wasm")]
tokio::task_local! { static ORIGIN_EPOCH: std::cell::Cell<u64>; }

#[cfg(not(target_family = "wasm"))]
pub fn post_action(action: impl ActionTrait + Send) { Cx::post_action(action); }
#[cfg(target_family = "wasm")]
pub fn post_action(action: impl ActionTrait) { post_action_for(origin_epoch(), action); }

/// Once UI delivery is poisoned, reject new outbound work until resynchronization.
#[cfg(target_family = "wasm")]
pub fn accepts_requests() -> bool { ACTIONS.with_borrow(|q| !q.overflowed) }

#[cfg(target_family = "wasm")]
pub fn current_epoch() -> u64 { ACTIONS.with_borrow(|q| q.epoch) }
#[cfg(target_family = "wasm")]
pub fn origin_epoch() -> u64 { ORIGIN_EPOCH.try_with(|epoch| epoch.get()).unwrap_or_else(|_| current_epoch()) }
#[cfg(target_family = "wasm")]
pub fn advance_epoch() -> u64 {
    let epoch = ACTIONS.with_borrow_mut(LocalActions::advance);
    let _ = ORIGIN_EPOCH.try_with(|origin| origin.set(epoch));
    epoch
}
#[cfg(target_family = "wasm")]
pub fn post_action_for(epoch: u64, action: impl ActionTrait) {
    ACTIONS.with_borrow_mut(|q| q.push(epoch, Box::new(action)));
    makepad_widgets::SignalToUI::set_ui_signal();
}

/// Preserve the epoch captured when registering an SDK callback.
#[cfg(target_family = "wasm")]
pub fn scope_epoch<F: std::future::Future>(epoch: u64, future: F) -> impl std::future::Future<Output = F::Output> {
    ORIGIN_EPOCH.scope(std::cell::Cell::new(epoch), future)
}

#[cfg(target_family = "wasm")]
pub fn report_overflow() {
    ACTIONS.with_borrow_mut(|q| { q.pending.clear(); q.overflowed = true; q.reported = false; });
    makepad_widgets::SignalToUI::set_ui_signal();
}

/// Move locally queued objects into Makepad only on the owning UI thread.
#[cfg(target_family = "wasm")]
pub fn drain(cx: &mut Cx) {
    let (actions, overflow) = ACTIONS.with_borrow_mut(|q| {
        // A single visible error is emitted; updates stay fail-closed until a new session.
        let overflow = q.overflowed && !q.reported;
        q.reported |= overflow;
        (std::mem::take(&mut q.pending), overflow)
    });
    cx.extend_actions(actions);
    if overflow {
        crate::shared::popup_list::enqueue_popup_notification(
            "UI update queue exceeded its limit. Reload to resynchronize; message delivery is not confirmed.",
            crate::shared::popup_list::PopupKind::Error,
            None,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_account_actions_cannot_enter_new_epoch() {
        let mut q = LocalActions::new();
        q.push(0, Box::new("old"));
        assert_eq!(q.advance(), 1);
        q.push(0, Box::new("late old callback"));
        assert!(q.pending.is_empty());
        q.push(1, Box::new("new"));
        assert_eq!(q.pending.len(), 1);
    }
    #[test]
    fn queued_logout_actions_do_not_clear_a_new_account() {
        use crate::logout::logout_confirm_modal::LogoutAction;
        let mut q = LocalActions::new();
        q.push(0, Box::new(LogoutAction::ClearAppState { on_clear_appstate: std::sync::Arc::new(tokio::sync::Notify::new()) }));
        q.push(0, Box::new(LogoutAction::LogoutSuccess));
        q.advance();
        q.push(0, Box::new(LogoutAction::ProgressUpdate { message: "late old logout".into(), percentage: 100 }));
        assert!(q.pending.is_empty());
        q.push(1, Box::new("current account remains visible"));
        assert_eq!(q.pending.len(), 1);
    }
    #[test]
    fn overflow_is_bounded_and_requires_new_epoch() {
        let mut q = LocalActions::new();
        for _ in 0..=MAX_PENDING_ACTIONS { q.push(0, Box::new(())); }
        assert!(q.overflowed);
        assert!(!q.reported);
        assert!(q.pending.is_empty());
        q.push(0, Box::new("not silently resumed"));
        assert!(q.pending.is_empty());
        q.advance();
        q.push(1, Box::new("resynchronized"));
        assert_eq!(q.pending.len(), 1);
    }
}

/// Browser-only bounded queue for SDK objects that never leave their owning thread.
#[cfg(target_family = "wasm")]
pub(crate) struct EpochQueue<T> {
    epoch: u64,
    items: std::collections::VecDeque<T>,
}
#[cfg(target_family = "wasm")]
impl<T> EpochQueue<T> {
    pub const fn new() -> Self { Self { epoch: 0, items: std::collections::VecDeque::new() } }
    fn refresh(&mut self) {
        let epoch = current_epoch();
        if self.epoch != epoch { self.items.clear(); self.epoch = epoch; }
    }
    pub fn push(&mut self, value: T) {
        self.refresh();
        if origin_epoch() != self.epoch { return; }
        if self.items.len() >= MAX_PENDING_ACTIONS { self.items.clear(); report_overflow(); return; }
        self.items.push_back(value);
    }
    pub fn pop(&mut self) -> Option<T> { self.refresh(); self.items.pop_front() }
    pub fn clear(&mut self) { self.items.clear(); }
}
