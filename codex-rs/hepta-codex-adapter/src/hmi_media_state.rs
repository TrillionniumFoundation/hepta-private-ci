//! Bounded request state and cancellation-safe ownership of the media writer.
use super::*;

pub(super) struct Pending {
    pub(super) operation: &'static str,
    pub(super) reply: oneshot::Sender<Result<Value, HmiError>>,
}
pub(super) struct MediaPendingState {
    pub(super) closed: AtomicBool,
    pub(super) closed_notify: tokio::sync::Notify,
    pub(super) next: AtomicU64,
    pub(super) pending: Mutex<BTreeMap<u64, Pending>>,
}
impl MediaPendingState {
    pub(super) fn fail(&self, error: HmiError) {
        self.closed.store(true, Ordering::SeqCst);
        self.closed_notify.notify_waiters();
        for (_, pending) in std::mem::take(
            &mut *self
                .pending
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
        ) {
            let _ = pending.reply.send(Err(error.clone()));
        }
    }
    pub(super) fn ack(
        &self,
        id: u64,
        operation: &str,
        result: Result<Value, HmiError>,
    ) -> Result<(), HmiError> {
        let pending = self
            .pending
            .lock()
            .map_err(|_| HmiError::Fenced)?
            .remove(&id)
            .ok_or(HmiError::Identity)?;
        if pending.operation != operation {
            let _ = pending.reply.send(Err(HmiError::Identity));
            return Err(HmiError::Identity);
        }
        let _ = pending.reply.send(result);
        Ok(())
    }
}
pub(super) struct RequestGuard {
    pub(super) shared: Arc<MediaPendingState>,
    pub(super) id: u64,
}
impl Drop for RequestGuard {
    fn drop(&mut self) {
        // An abandoned write/ack is ambiguous. Reusing that stream could admit
        // half a JSON frame or replay a command; fence every outstanding waiter.
        let pending = self
            .shared
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .contains_key(&self.id);
        if pending {
            self.shared.fail(HmiError::Fenced);
        }
    }
}
pub(super) struct WriterSlot<W> {
    pub(super) writer: Mutex<Option<W>>,
    pub(super) gate: tokio::sync::Semaphore,
}
pub(super) struct WriterLease<W> {
    pub(super) owner: Arc<WriterSlot<W>>,
    pub(super) shared: Arc<MediaPendingState>,
    pub(super) writer: Option<W>,
    pub(super) reusable: bool,
}
impl<W> Drop for WriterLease<W> {
    fn drop(&mut self) {
        if self.reusable && !self.shared.closed.load(Ordering::SeqCst) {
            *self
                .owner
                .writer
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = self.writer.take();
        }
        // Cancellation during a partial frame drops its owned writer, closing
        // the native stdin. No lock guard crosses I/O or acknowledgement awaits.
    }
}
