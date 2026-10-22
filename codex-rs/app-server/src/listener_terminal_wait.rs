use std::future::Future;
use std::ops::ControlFlow;

use tokio::sync::oneshot;

/// Retiring a listener discards its remaining notification; it never completes the Core owner.
/// Only this read-only wait is cancellable, after pending turn requests have been released.
pub(super) async fn wait_for_terminalization_or_listener_cancel(
    completion: impl Future<Output = ()>,
    listener_cancel: &mut oneshot::Receiver<()>,
) -> ControlFlow<()> {
    tokio::select! {
        biased;
        _ = listener_cancel => ControlFlow::Break(()),
        _ = completion => ControlFlow::Continue(()),
    }
}

#[cfg(test)]
#[path = "listener_terminal_wait_tests.rs"]
mod tests;
