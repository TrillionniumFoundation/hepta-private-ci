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
use super::OriginalCircuitEvaluatedVersionProgressV1;
use super::OriginalCircuitRetainedVersionPublicationV1;
use super::OriginalCircuitRetainedVersionReadbackV1;
use super::RetainedVersionOriginV1;
use super::context::OriginalVersionCut;
use super::evaluated_context::OriginalEvaluatedVersionCut;
use super::evaluated_wire::EvaluatedProgressResult;
use super::evaluated_wire::VersionRequest;
use super::evaluated_wire::decode_result;
use super::now;
use super::profile::VersionCut;
use super::wire;
use crate::OriginalCellEvaluationCommandReceiptV1;
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
    PublicationProgress,
}

enum OriginalVersionResponse {
    Readback(wire::OriginalResult),
    Progress(EvaluatedProgressResult),
}

enum OriginalVersionValue {
    Readback(OriginalCircuitRetainedVersionReadbackV1),
    Progress(OriginalCircuitEvaluatedVersionProgressV1),
}

pub struct OriginalCircuitRetainedVersionClientV1 {
    channel: Mutex<Option<OriginalVersionChannel>>,
    cut: Arc<VersionCut>,
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

    /// Consume the initial Version channel after actual opaque D/T/B. This
    /// purpose never reinterprets a legacy TrainingNoUpdate wire request.
    pub(crate) fn bind_original_evaluated_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        Self::bind_evaluated(
            peer,
            material,
            dataset,
            training,
            evaluation,
            RetainedVersionOriginV1::Fresh,
        )
    }

    pub(crate) fn recover_original_evaluated_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        Self::bind_evaluated(
            peer,
            material,
            dataset,
            training,
            evaluation,
            RetainedVersionOriginV1::Recovered,
        )
    }

    fn bind_evaluated(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
        origin: RetainedVersionOriginV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        let cut = VersionCut::Evaluated(OriginalEvaluatedVersionCut::from_original(
            material.clone(),
            dataset.clone(),
            training,
            evaluation,
            origin,
        )?);
        Self::from_original_cut(peer, cut, origin, started)
    }

    fn bind(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        origin: RetainedVersionOriginV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        let cut = VersionCut::TrainingNoUpdate(OriginalVersionCut::from_original(
            material.clone(),
            dataset.clone(),
            training,
            origin,
        )?);
        Self::from_original_cut(peer, cut, origin, started)
    }

    fn from_original_cut(
        peer: HostAuthorityPeerChannel,
        cut: VersionCut,
        origin: RetainedVersionOriginV1,
        started: u64,
    ) -> Result<Self, Error> {
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

    /// Wait only for this session's publication worker. A successful hint is
    /// never CURRENT, a FinalUse result, or an executable Fresh capability.
    /// The caller must obtain full original readback before it advances S/C.
    pub(crate) async fn publication_progress(
        &self,
    ) -> Result<OriginalCircuitEvaluatedVersionProgressV1, Error> {
        if !matches!(self.cut.as_ref(), VersionCut::Evaluated(_)) {
            return Err(Error::Binding("evaluated-only Version progress purpose"));
        }
        match self
            .exchange_original(RequestMode::PublicationProgress)
            .await?
        {
            OriginalVersionValue::Progress(value) => Ok(value),
            OriginalVersionValue::Readback(_) => {
                Err(Error::Binding("original Version progress response type"))
            }
        }
    }

    async fn exchange(
        &self,
        mode: RequestMode,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        match self.exchange_original(mode).await? {
            OriginalVersionValue::Readback(value) => Ok(value),
            OriginalVersionValue::Progress(_) => {
                Err(Error::Binding("original Version readback response type"))
            }
        }
    }

    async fn exchange_original(&self, mode: RequestMode) -> Result<OriginalVersionValue, Error> {
        let started = now()?;
        let access = match &mode {
            RequestMode::Prepare(_) => PublicationAccess::NewWork,
            RequestMode::Readback | RequestMode::PublicationProgress => PublicationAccess::Readback,
        };
        self.cut.require_fresh(started, access)?;
        let action = match &mode {
            RequestMode::Prepare(cancelled) => {
                if cancelled.load(Ordering::Acquire) {
                    return Err(Error::Cancelled);
                }
                Some(wire::Action::Prepare)
            }
            RequestMode::Readback => Some(wire::Action::Readback),
            RequestMode::PublicationProgress => None,
        };
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Busy)?;
            let original = slot.as_mut().ok_or(Error::Unavailable)?;
            if action == Some(wire::Action::Prepare) && original.preparation_requested {
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
        let request = match action {
            Some(action) => VersionRequest::new(&self.cut, channel.next_request_id, action),
            None => VersionRequest::publication_progress(&self.cut, channel.next_request_id)?,
        };
        let encoded = request.encode()?;
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
        let response = if request.is_publication_progress() {
            OriginalVersionResponse::Progress(request.decode_progress_response(&raw)?)
        } else {
            OriginalVersionResponse::Readback(request.decode_response(&raw)?)
        };
        channel.peer.check_peer_lifetime()?;
        self.cut
            .require_fresh(started, access)
            .map_err(|_| Error::CommitUncertain)?;
        let decoded = match response {
            OriginalVersionResponse::Progress(response) => match response.decode() {
                Ok(value) => Ok(OriginalVersionValue::Progress(value)),
                Err(Error::Busy) => Err(Error::Busy),
                // A progress hint never repairs denial, missing custody or
                // uncertainty. Those results consume this original channel.
                Err(error) => return Err(error),
            },
            OriginalVersionResponse::Readback(response) => {
                // Keep the original full-readback contract unchanged. No bit
                // is reset and no second preparation becomes possible.
                let structured_error = matches!(
                    &response,
                    wire::OriginalResult::Busy
                        | wire::OriginalResult::ReadbackRequired
                        | wire::OriginalResult::Uncertain
                        | wire::OriginalResult::Unavailable
                        | wire::OriginalResult::FinalUseDenied
                );
                let decoded = decode_result(response, &self.cut);
                match &decoded {
                    Ok(value) => self.pin(value)?,
                    Err(_) if structured_error => {}
                    Err(_) => return decoded.map(OriginalVersionValue::Readback),
                }
                decoded.map(OriginalVersionValue::Readback)
            }
        };
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
