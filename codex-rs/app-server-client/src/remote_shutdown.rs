//! A cancelled bounded shutdown must not detach its original transport worker.
pub(super) struct AbortOnDrop(pub(super) tokio::task::AbortHandle);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

#[cfg(test)]
#[path = "remote_shutdown_tests.rs"]
mod tests;
