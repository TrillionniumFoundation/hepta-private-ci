//! One original Version connection. It cannot reconnect, renew, send grants,
//! upload a future observation or replay its one publication request.
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use super::Error;
use super::Origin;
use super::OriginalCircuitModelVersionReadbackV1 as Readback;
use super::now;
use super::require_clock;
use super::wire;
use crate::OriginalCircuitCandidateLearningReadContextV1 as Context;

struct Channel {
    peer: HostAuthorityPeerChannel,
    next: u64,
    requested: bool,
}
struct Cancelled(Arc<AtomicBool>);
impl Drop for Cancelled {
    fn drop(&mut self) { self.0.store(/*val*/ true, Ordering::Release); }
}
pub struct OriginalCircuitModelVersionClientV1 {
    channel: Mutex<Option<Channel>>,
    context: Context,
    retained: Mutex<Option<Readback>>,
}
impl OriginalCircuitModelVersionClientV1 {
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel, context: Context,
    ) -> Result<Self, Error> {
        Self::bind(peer, context, Origin::Fresh)
    }
    pub(crate) fn recover_original_stage_channel(
        peer: HostAuthorityPeerChannel, context: Context,
    ) -> Result<Self, Error> {
        Self::bind(peer, context, Origin::Recovered)
    }
    fn bind(peer: HostAuthorityPeerChannel, context: Context, origin: Origin) -> Result<Self, Error> {
        let started = now()?;
        if context.prefix() != context.decision() || context.decision().receipts.len() != 5 {
            return Err(Error::Binding("exact original Model before positive Version"));
        }
        context.model_publication_context().authenticate(started, /*new_work*/ false)?;
        let expected = context.model_publication_context().original_version_binding(started)?;
        peer.check_peer_lifetime()?;
        let fresh = now()?;
        require_clock(started, fresh)?;
        if context.model_publication_context().original_version_binding(fresh)? != expected {
            return Err(Error::Binding("unchanged original Version late binding"));
        }
        Ok(Self {
            channel: Mutex::new(Some(Channel { peer, next: 1, requested: origin == Origin::Recovered })),
            context, retained: Mutex::new(None),
        })
    }
    pub async fn publish_original_version(
        &self, original_cancellation: Arc<AtomicBool>,
    ) -> Result<Readback, Error> {
        self.exchange(Some(original_cancellation)).await
    }
    pub async fn readback(&self) -> Result<Readback, Error> {
        self.exchange(None).await
    }
    async fn exchange(&self, original_cancellation: Option<Arc<AtomicBool>>) -> Result<Readback, Error> {
        let started = now()?;
        let action = if original_cancellation.is_some() {
            wire::Action::Publish
        } else { wire::Action::Readback };
        self.context.model_publication_context().authenticate(
            started, action == wire::Action::Publish,
        )?;
        if original_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire)) {
            return Err(Error::Cancelled);
        }
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Busy)?;
            let original = slot.as_mut().ok_or(Error::Unavailable)?;
            if action == wire::Action::Publish && original.requested {
                return Err(Error::ReadbackRequired);
            }
            // Even first readback attenuates this one channel permanently.
            original.requested = true;
            slot.take().ok_or(Error::Unavailable)?
        };
        if !(1..=128).contains(&channel.next) { return Err(Error::Unavailable); }
        let request = wire::Request::new(self.context.model_publication_context(), channel.next, action)?;
        let bytes = serde_json::to_vec(&request)?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded positive Version request"));
        }
        channel.next += 1;
        let cancellation = Cancelled(Arc::new(AtomicBool::new(/*v*/ false)));
        let queued = Arc::clone(&cancellation.0);
        let (channel, response) = tokio::task::spawn_blocking(move || {
            channel.peer.check_peer_lifetime()?;
            if queued.load(Ordering::Acquire)
                || original_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire))
            {
                return Err(Error::Cancelled);
            }
            let response = channel.peer.request(&bytes).map_err(|_| Error::CommitUncertain)?;
            channel.peer.check_peer_lifetime()?;
            if queued.load(Ordering::Acquire)
                || original_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire))
            {
                return Err(Error::CommitUncertain);
            }
            Ok::<_, Error>((channel, response))
        }).await.map_err(|_| Error::CommitUncertain)??;
        if response.is_empty() || response.len() > 16_384 {
            return Err(Error::Binding("bounded positive Version response"));
        }
        let response: wire::Response = serde_json::from_slice(&response)?;
        if response.request != request { return Err(Error::Binding("same positive Version response")); }
        let fresh = now()?;
        require_clock(started, fresh).map_err(|_| Error::CommitUncertain)?;
        self.context.model_publication_context().authenticate(fresh, /*new_work*/ false)
            .map_err(|_| Error::CommitUncertain)?;
        let structured = matches!(&response.result, wire::Outcome::Busy
            | wire::Outcome::ReadbackRequired | wire::Outcome::Uncertain
            | wire::Outcome::Unavailable | wire::Outcome::FinalUseDenied);
        let decoded = response.result.decode(self.context.model_publication_context());
        match &decoded {
            Ok(actual) => {
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained.as_ref().is_some_and(|prior| prior.intent != actual.intent
                    || prior.publication.is_some() && prior.publication != actual.publication)
                {
                    return Err(Error::CommitUncertain);
                }
                *retained = Some(actual.clone());
            }
            Err(_) if structured => {}
            Err(_) => return decoded,
        }
        let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
        if slot.is_some() { return Err(Error::CommitUncertain); }
        *slot = Some(channel);
        drop(slot);
        drop(cancellation);
        decoded
    }
}
