//! No key, callback, batch upload or writable owner extraction. A dropped
//! queued caller consumes its connection and cannot send a later Execute.
use super::Error;
use super::OriginalCellQ24ModelCommandReceiptV1;
use super::context::Context;
use super::now;
use super::require_clock;
use super::wire;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(super) struct Channel {
    pub(super) peer: HostAuthorityPeerChannel,
    pub(super) next: u64,
    pub(super) execution_requested: bool,
}
pub struct OriginalCellQ24ModelCommandClientV1 {
    pub(super) channel: Mutex<Option<Channel>>,
    pub(super) context: Context,
    pub(super) binding: Digest32,
    pub(super) retained: Mutex<Option<OriginalCellQ24ModelCommandReceiptV1>>,
    pub(super) observed_at: u64,
}
struct Abandoned(Arc<AtomicBool>);
impl Drop for Abandoned {
    fn drop(&mut self) {
        self.0.store(/*val*/ true, Ordering::Release);
    }
}
impl OriginalCellQ24ModelCommandClientV1 {
    pub async fn commit_model(
        &self,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        if cancellation.load(Ordering::Acquire) {
            return Err(Error::Cancelled);
        }
        if now()?
            >= self
                .context
                .material
                .initial
                .request
                .envelope
                .expiry_unix_seconds
        {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute, Some(cancellation))
            .await
    }
    pub async fn readback(&self) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        self.exchange(wire::Action::Readback, /*cancellation*/ None)
            .await
    }
    async fn exchange(
        &self,
        action: wire::Action,
        cancellation: Option<Arc<AtomicBool>>,
    ) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        let started = now()?;
        require_clock(self.observed_at, started)?;
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            if action == wire::Action::Execute
                && slot
                    .as_ref()
                    .is_some_and(|channel| channel.execution_requested)
            {
                return Err(Error::ReadbackRequired);
            }
            let mut channel = slot.take().ok_or(Error::Unavailable)?;
            if action == wire::Action::Execute {
                channel.execution_requested = true;
            }
            channel
        };
        if !(1..=128).contains(&channel.next) || self.context.binding()? != self.binding {
            return Err(Error::Unavailable);
        }
        self.context.authenticate(started)?;
        let request = wire::Request::new(&self.context, channel.next, action)?;
        let encoded = serde_json::to_vec(&request)?;
        if encoded.len() > 16_384 {
            return Err(Error::Binding("bounded original Model request"));
        }
        let abandoned = Abandoned(Arc::new(AtomicBool::default()));
        let queued = Arc::clone(&abandoned.0);
        let (mut channel, response) = tokio::task::spawn_blocking(move || {
            channel.peer.check_peer_lifetime()?;
            if queued.load(Ordering::Acquire)
                || cancellation
                    .as_ref()
                    .is_some_and(|flag| flag.load(Ordering::Acquire))
            {
                return Err(Error::Cancelled);
            }
            let response = channel
                .peer
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, response))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        if response.len() > 16_384 {
            return Err(Error::Binding("bounded original Model response"));
        }
        let response: wire::Response = serde_json::from_slice(&response)?;
        if response.request != request {
            return Err(Error::Binding("same original Model request and response"));
        }
        channel.peer.check_peer_lifetime()?;
        let current = self.context.authenticate(started)?;
        let result = match response.outcome {
            wire::Outcome::Completed { record } => {
                let current = wire::decode_completed(&self.context, &record, current)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained
                    .as_ref()
                    .is_some_and(|original| original != &current)
                {
                    return Err(Error::CommitUncertain);
                }
                *retained = Some(current.clone());
                Ok(current)
            }
            wire::Outcome::Missing | wire::Outcome::Pending
                if self
                    .retained
                    .try_lock()
                    .map_err(|_| Error::Unavailable)?
                    .is_some() =>
            {
                return Err(Error::CommitUncertain);
            }
            wire::Outcome::Missing => Err(Error::Missing),
            wire::Outcome::Pending => Err(Error::Pending),
            wire::Outcome::Ineligible => Err(Error::Ineligible),
            wire::Outcome::Busy => Err(Error::Busy),
            wire::Outcome::Expired => Err(Error::DeadlineExceeded),
            wire::Outcome::ReadbackRequired => Err(Error::ReadbackRequired),
            wire::Outcome::Unavailable => return Err(Error::Unavailable),
            wire::Outcome::Uncertain => return Err(Error::CommitUncertain),
        };
        channel.next += 1;
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        drop(abandoned);
        result
    }
}
