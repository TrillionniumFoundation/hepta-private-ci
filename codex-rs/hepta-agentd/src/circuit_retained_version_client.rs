//! One original, initially pinned Version connection. Lost ACK and queued
//! cancellation consume its dispatch surface; only the same operation reads.
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_types::Digest32;

use super::super::context::PublicationAccess;
use super::Error;
use super::OriginalCircuitRetainedVersionPublicationV1;
use super::OriginalCircuitRetainedVersionReadbackV1;
use super::RetainedVersionOriginV1;
use super::context::OriginalVersionCut;
use super::now;
use super::wire;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

struct OriginalVersionChannel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    preparation_requested: bool,
}
struct OriginalVersionPin {
    intent: Digest32,
    installed: Option<OriginalVersionInstalledPin>,
}
#[derive(Eq, PartialEq)]
struct OriginalVersionInstalledPin {
    publication: Digest32,
    task: Digest32,
    selection: Digest32,
    bundle: Digest32,
    run: codex_hepta_types::StableId,
}
impl From<&OriginalCircuitRetainedVersionPublicationV1> for OriginalVersionInstalledPin {
    fn from(value: &OriginalCircuitRetainedVersionPublicationV1) -> Self {
        Self {
            publication: value.publication,
            task: value.task,
            selection: value.selection,
            bundle: value.bundle,
            run: value.run.clone(),
        }
    }
}
enum RequestMode {
    Prepare(Arc<AtomicBool>),
    Readback,
}

pub struct OriginalCircuitRetainedVersionClientV1 {
    channel: Mutex<Option<OriginalVersionChannel>>,
    cut: Arc<OriginalVersionCut>,
    retained: Mutex<Option<OriginalVersionPin>>,
}
impl OriginalCircuitRetainedVersionClientV1 {
    /// Only the concrete ordinary adapter can move its initial Version channel
    /// here after actual opaque D/T. This does not recreate a session deadline.
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Self, Error> {
        Self::bind(
            peer,
            material,
            dataset,
            training,
            RetainedVersionOriginV1::Fresh,
        )
    }

    pub(crate) fn recover_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Self, Error> {
        Self::bind(
            peer,
            material,
            dataset,
            training,
            RetainedVersionOriginV1::Recovered,
        )
    }

    fn bind(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        origin: RetainedVersionOriginV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        let cut =
            OriginalVersionCut::from_original(material.clone(), dataset.clone(), training, origin)?;
        peer.check_peer_lifetime()?;
        cut.require_fresh(started, PublicationAccess::Readback)?;
        Ok(Self {
            channel: Mutex::new(Some(OriginalVersionChannel {
                peer,
                next_request_id: 1,
                preparation_requested: origin == RetainedVersionOriginV1::Recovered,
            })),
            cut: Arc::new(cut),
            retained: Mutex::new(None),
        })
    }

    /// The one fresh resident future may request original preparation once.
    /// This never sends FinalUse or uploads an unsigned future receipt.
    pub async fn prepare_original_version(
        &self,
        original_cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        self.exchange(RequestMode::Prepare(original_cancellation))
            .await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        self.exchange(RequestMode::Readback).await
    }

    async fn exchange(
        &self,
        mode: RequestMode,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        let started = now()?;
        let access = match &mode {
            RequestMode::Prepare(_) => PublicationAccess::NewWork,
            RequestMode::Readback => PublicationAccess::Readback,
        };
        self.cut.require_fresh(started, access)?;
        let action = match &mode {
            RequestMode::Prepare(cancelled) => {
                if cancelled.load(Ordering::Acquire) {
                    return Err(Error::Cancelled);
                }
                wire::Action::Prepare
            }
            RequestMode::Readback => wire::Action::Readback,
        };
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Busy)?;
            let original = slot.as_mut().ok_or(Error::Unavailable)?;
            if action == wire::Action::Prepare && original.preparation_requested {
                return Err(Error::ReadbackRequired);
            }
            // Even an initial read permanently attenuates this client. Existing
            // or uncertain original state can never become a fresh dispatch.
            original.preparation_requested = true;
            slot.take().ok_or(Error::Unavailable)?
        };
        if !(1..=128).contains(&channel.next_request_id) {
            return Err(Error::Unavailable);
        }
        let request = wire::Request::new(&self.cut, channel.next_request_id, action);
        let encoded = serde_json::to_vec(&request)?;
        if encoded.is_empty() || encoded.len() > 16_384 {
            return Err(Error::Binding("bounded Version request"));
        }
        channel.next_request_id += 1;
        let queued = QueuedVersionRequestFence::new();
        let dropped = Arc::clone(&queued.cancelled);
        let cut = Arc::clone(&self.cut);
        let (channel, raw) = tokio::task::spawn_blocking(move || {
            if dropped.load(Ordering::Acquire) {
                return Err(Error::Cancelled);
            }
            if let RequestMode::Prepare(cancelled) = &mode
                && cancelled.load(Ordering::Acquire)
            {
                return Err(Error::Cancelled);
            }
            cut.require_fresh(started, access)?;
            // Dropping the awaiter cannot send a request that was still queued.
            if dropped.load(Ordering::Acquire) {
                return Err(Error::Cancelled);
            }
            if let RequestMode::Prepare(cancelled) = &mode
                && cancelled.load(Ordering::Acquire)
            {
                return Err(Error::Cancelled);
            }
            let raw = channel.peer.request(&encoded)?;
            Ok::<_, Error>((channel, raw))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        drop(queued);
        let response: wire::Response = serde_json::from_slice(&raw)?;
        if response.request != request {
            return Err(Error::Binding("exact original Version response"));
        }
        channel.peer.check_peer_lifetime()?;
        self.cut
            .require_fresh(started, access)
            .map_err(|_| Error::CommitUncertain)?;
        // Structured Pending/Busy/Uncertain may keep only this original read
        // channel. No bit is reset and no second preparation becomes possible.
        let structured_error = matches!(
            &response.result,
            wire::OriginalResult::Busy
                | wire::OriginalResult::ReadbackRequired
                | wire::OriginalResult::Uncertain
                | wire::OriginalResult::Unavailable
                | wire::OriginalResult::FinalUseDenied
        );
        let decoded = response.result.decode(&self.cut);
        match &decoded {
            Ok(value) => self.pin(value)?,
            Err(_) if structured_error => {}
            Err(_) => return decoded,
        }
        *self
            .channel
            .try_lock()
            .map_err(|_| Error::CommitUncertain)? = Some(channel);
        decoded
    }

    fn pin(&self, value: &OriginalCircuitRetainedVersionReadbackV1) -> Result<(), Error> {
        let mut saved = self.retained.try_lock().map_err(|_| Error::Busy)?;
        let installed = value
            .publication
            .as_ref()
            .map(OriginalVersionInstalledPin::from);
        if let Some(original) = saved.as_ref()
            && (original.intent != value.intent
                || original.installed.is_some() && original.installed != installed)
        {
            return Err(Error::Binding("original publication identity changed"));
        }
        *saved = Some(OriginalVersionPin {
            intent: value.intent,
            installed,
        });
        Ok(())
    }
}

struct QueuedVersionRequestFence {
    cancelled: Arc<AtomicBool>,
}
impl QueuedVersionRequestFence {
    fn new() -> Self {
        Self {
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }
}
impl Drop for QueuedVersionRequestFence {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::Release);
    }
}
