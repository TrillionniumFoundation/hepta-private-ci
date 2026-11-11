//! Share the original command poll while retaining Tokio's cleanup context.

pub(super) fn block_on_original<F: std::future::Future>(
    runtime: &tokio::runtime::Runtime,
    future: F,
) -> F::Output {
    // Match locked Tokio 1.53.3: retain its original large-future boxing path.
    const BOX_FUTURE_THRESHOLD: usize = if cfg!(debug_assertions) { 2048 } else { 16384 };
    if std::mem::size_of::<F>() > BOX_FUTURE_THRESHOLD {
        return runtime.block_on(future);
    }
    let mut future = std::pin::pin!(Some(future));
    runtime.block_on(OriginalPoll {
        future: future.as_mut(),
    })
}

struct OriginalPoll<'a, F> {
    future: std::pin::Pin<&'a mut Option<F>>,
}

impl<F: std::future::Future> std::future::Future for OriginalPoll<'_, F> {
    type Output = F::Output;

    fn poll(
        self: std::pin::Pin<&mut Self>,
        context: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Self::Output> {
        let Some(future) = self.get_mut().future.as_mut().as_pin_mut() else {
            unreachable!("the original future is retained until forwarder drop");
        };
        poll_original(future, context)
    }
}

impl<F> Drop for OriginalPoll<'_, F> {
    fn drop(&mut self) {
        // Drop in place where Tokio drops its owned future, while its original
        // scheduler guards remain active. The outer pinned slot becomes empty.
        self.future.set(None);
    }
}

// Keep the concrete command poll outside scheduler inlining.
#[inline(never)]
fn poll_original<F: std::future::Future>(
    future: std::pin::Pin<&mut F>,
    context: &mut std::task::Context<'_>,
) -> std::task::Poll<F::Output> {
    future.poll(context)
}

#[cfg(test)]
#[path = "command_runtime_tests.rs"]
mod tests;
