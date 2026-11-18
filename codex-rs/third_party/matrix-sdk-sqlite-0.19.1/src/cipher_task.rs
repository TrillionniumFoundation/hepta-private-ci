// SPDX-License-Identifier: Apache-2.0

use tokio::task::AbortHandle;
use tokio::task::JoinError;

struct AbortOnDrop(AbortHandle);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        // A running blocking task cannot be interrupted. Abort still prevents
        // queued work from starting after its caller has been cancelled.
        self.0.abort();
    }
}

pub(crate) async fn run<F, T>(compute: F) -> Result<T, JoinError>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    let task = tokio::task::spawn_blocking(compute);
    let _abort_on_drop = AbortOnDrop(task.abort_handle());
    task.await
}
