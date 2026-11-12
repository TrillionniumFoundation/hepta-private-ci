//! One original Model channel holds a bounded read across an owner operation.
//! Provisional Model and full E material are borrowed only inside that operation.
//! Finish performs the original E/native tail reads before releasing a result.
use super::Error;
use super::OriginalCellQ24ModelCommandClientV1;
use super::OriginalCellQ24ModelCommandReceiptV1;
use super::client::Channel;
use super::now;
use super::require_clock;
use super::wire;
use crate::OriginalCellEvaluationModelMaterialV1;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

struct Cancelled(Arc<AtomicBool>);
impl Drop for Cancelled {
    fn drop(&mut self) { self.0.store(true, Ordering::Release); }
}

/// This cannot be cloned, deserialized or retained by the Model client.
pub(crate) struct OriginalCellQ24ModelReadV1<'a> {
    client: &'a OriginalCellQ24ModelCommandClientV1,
    channel: Option<Channel>,
    model: OriginalCellQ24ModelCommandReceiptV1,
    material: OriginalCellEvaluationModelMaterialV1,
    transfer: u64,
    total: usize,
    digest: Digest32,
    started: u64,
    cancellation: Cancelled,
    effect_cancellation: Option<Arc<AtomicBool>>,
}

/// A completed observation from one actual Begin/Finish, never a new authority.
pub(crate) struct OriginalCellQ24ModelReadCompletionV1 {
    model: OriginalCellQ24ModelCommandReceiptV1,
    material: OriginalCellEvaluationModelMaterialV1,
}
impl OriginalCellQ24ModelReadCompletionV1 {
    pub(crate) fn model(&self) -> &OriginalCellQ24ModelCommandReceiptV1 { &self.model }
    pub(crate) fn material(&self) -> &OriginalCellEvaluationModelMaterialV1 { &self.material }
}

impl OriginalCellQ24ModelCommandClientV1 {
    pub(crate) async fn begin_original_model_read(
        &self,
    ) -> Result<OriginalCellQ24ModelReadV1<'_>, Error> {
        self.begin_original_operation(wire::Action::BeginOriginalRead, None).await
    }

    /// The existing original Execute capability is consumed at most once.
    /// Its result remains provisional until the same operation's native tail.
    pub(crate) async fn begin_original_model_commit(
        &self,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24ModelReadV1<'_>, Error> {
        if cancellation.load(Ordering::Acquire) { return Err(Error::Cancelled); }
        if now()? >= self.context.material.initial.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.begin_original_operation(
            wire::Action::BeginOriginalExecute, Some(cancellation),
        ).await
    }

    async fn begin_original_operation(
        &self,
        action: wire::Action,
        effect_cancellation: Option<Arc<AtomicBool>>,
    ) -> Result<OriginalCellQ24ModelReadV1<'_>, Error> {
        let started = now()?;
        require_clock(self.observed_at, started)?;
        let channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            if action == wire::Action::BeginOriginalExecute
                && slot.as_ref().is_some_and(|channel| channel.execution_requested)
            {
                return Err(Error::ReadbackRequired);
            }
            let mut channel = slot.take().ok_or(Error::Unavailable)?;
            if action == wire::Action::BeginOriginalExecute {
                channel.execution_requested = true;
            }
            channel
        };
        let transfer = channel.next;
        let cancellation = Cancelled(Arc::new(AtomicBool::new(false)));
        let (mut channel, outcome) = exchange(
            self, channel, action,
            Arc::clone(&cancellation.0), effect_cancellation.clone(), started,
        ).await?;
        let (record, total, digest) = match outcome {
            wire::Outcome::OriginalReadStarted {
                transfer: actual, record, total, digest,
            } if actual == transfer => (record, total, digest),
            wire::Outcome::Missing | wire::Outcome::Pending
                if self.retained.try_lock().map_err(|_| Error::Unavailable)?.is_some() =>
            {
                return Err(Error::CommitUncertain);
            }
            other => return Err(outcome_error(other)),
        };
        if total == 0 || total > wire::MATERIAL_MAX_BYTES {
            return Err(Error::Binding("bounded complete original Model E body"));
        }
        let pages = total.div_ceil(wire::MATERIAL_PAGE_BYTES);
        if channel.next.checked_add(pages as u64).is_none_or(|finish| finish > 128) {
            return Err(Error::Unavailable);
        }
        let digest = canonical_digest(&digest)?;
        let model = wire::decode_completed(&self.context, &record, self.context.authenticate(started)?)?;
        if self.retained.try_lock().map_err(|_| Error::Unavailable)?
            .as_ref().is_some_and(|previous| previous != &model)
        {
            return Err(Error::CommitUncertain);
        }
        let mut body = Vec::with_capacity(total);
        for index in 0..pages {
            let (returned, outcome) = exchange(
                self, channel,
                wire::Action::ReadOriginalPage { transfer, index: index as u32 },
                Arc::clone(&cancellation.0), effect_cancellation.clone(), started,
            ).await?;
            channel = returned;
            let wire::Outcome::OriginalReadPage {
                transfer: actual, index: page, offset, total: size, digest: hash, bytes,
            } = outcome else { return Err(outcome_error(outcome)); };
            let expected = (total - body.len()).min(wire::MATERIAL_PAGE_BYTES);
            if actual != transfer || page != index as u32 || offset != body.len()
                || size != total || canonical_digest(&hash)? != digest
                || bytes.len() > 10_924
            {
                return Err(Error::Binding("same bounded original Model material page"));
            }
            let decoded = STANDARD_NO_PAD.decode(&bytes)
                .map_err(|_| Error::Binding("canonical original Model material page"))?;
            if decoded.len() != expected || STANDARD_NO_PAD.encode(&decoded) != bytes {
                return Err(Error::Binding("complete canonical original Model material page"));
            }
            body.extend_from_slice(&decoded);
        }
        if body.len() != total || Digest32::of_bytes(&body) != digest {
            return Err(Error::Binding("complete original Model material body"));
        }
        let fresh = self.context.authenticate(started)?;
        let material = OriginalCellEvaluationModelMaterialV1::from_original_model_response(
            &self.context.material, &self.context.registration, &self.context.dataset,
            &self.context.training, &self.context.evaluation, body, fresh,
        )?;
        let operation = OriginalCellQ24ModelReadV1 {
            client: self, channel: Some(channel), model, material, transfer, total,
            digest, started, cancellation, effect_cancellation,
        };
        operation.require_current(fresh)?;
        Ok(operation)
    }
}

impl OriginalCellQ24ModelReadV1<'_> {
    pub(crate) fn model(&self) -> &OriginalCellQ24ModelCommandReceiptV1 { &self.model }
    pub(crate) fn material(&self) -> &OriginalCellEvaluationModelMaterialV1 { &self.material }

    /// Same original peer/pidfd and absolute lifetime, followed by all full
    /// windows at the current OS clock. This performs no Finish or new read.
    pub(crate) fn require_current(&self, lower: u64) -> Result<u64, Error> {
        self.channel.as_ref().ok_or(Error::Unavailable)?.peer.check_peer_lifetime()?;
        if self.effect_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire)) {
            return Err(Error::Cancelled);
        }
        let fresh = self.client.context.authenticate(self.started.max(lower))?;
        self.material.authenticate_current(fresh)?;
        let input = self.material.require_original_model_input(
            &self.client.context.training_cut,
            self.client.context.training.attestation(),
            fresh,
        )?;
        if self.material.original_evaluation() != &self.client.context.evaluation
            || input.material_digest() != self.model.material_digest()
        {
            return Err(Error::Binding("same original Model record and full E material"));
        }
        Ok(fresh)
    }

    pub(crate) async fn finish(mut self) -> Result<OriginalCellQ24ModelReadCompletionV1, Error> {
        let lower = self.require_current(self.started)?;
        let channel = self.channel.take().ok_or(Error::Unavailable)?;
        let (channel, outcome) = exchange(
            self.client, channel,
            wire::Action::FinishOriginalRead { transfer: self.transfer },
            Arc::clone(&self.cancellation.0), self.effect_cancellation.clone(), lower,
        ).await?;
        let wire::Outcome::OriginalReadFinished {
            transfer, record, total, digest,
        } = outcome else { return Err(outcome_error(outcome)); };
        if transfer != self.transfer || total != self.total
            || canonical_digest(&digest)? != self.digest
        {
            return Err(Error::CommitUncertain);
        }
        let current = wire::decode_completed(
            &self.client.context, &record, self.client.context.authenticate(lower)?,
        )?;
        if current != self.model {
            return Err(Error::CommitUncertain);
        }
        self.channel = Some(channel);
        self.require_current(lower)?;
        {
            let mut retained = self.client.retained.try_lock().map_err(|_| Error::Unavailable)?;
            if retained.as_ref().is_some_and(|previous| previous != &current) {
                return Err(Error::CommitUncertain);
            }
            *retained = Some(current);
        }
        let channel = self.channel.take().ok_or(Error::Unavailable)?;
        let mut slot = self.client.channel.try_lock().map_err(|_| Error::Unavailable)?;
        if slot.is_some() { return Err(Error::CommitUncertain); }
        *slot = Some(channel);
        drop(slot);
        drop(self.cancellation);
        Ok(OriginalCellQ24ModelReadCompletionV1 { model: self.model, material: self.material })
    }
}

async fn exchange(
    client: &OriginalCellQ24ModelCommandClientV1,
    mut channel: Channel,
    action: wire::Action,
    cancellation: Arc<AtomicBool>,
    effect_cancellation: Option<Arc<AtomicBool>>,
    lower: u64,
) -> Result<(Channel, wire::Outcome), Error> {
    if !(1..=128).contains(&channel.next) || client.context.binding()? != client.binding {
        return Err(Error::Unavailable);
    }
    client.context.authenticate(lower)?;
    let request = wire::Request::new(&client.context, channel.next, action)?;
    let encoded = serde_json::to_vec(&request)?;
    if encoded.len() > 16_384 {
        return Err(Error::Binding("bounded original Model read request"));
    }
    let (mut channel, response) = tokio::task::spawn_blocking(move || {
        channel.peer.check_peer_lifetime()?;
        if cancellation.load(Ordering::Acquire)
            || effect_cancellation.as_ref().is_some_and(|flag| flag.load(Ordering::Acquire))
        { return Err(Error::Cancelled); }
        let response = channel.peer.request(&encoded).map_err(|_| Error::CommitUncertain)?;
        channel.peer.check_peer_lifetime()?;
        Ok::<_, Error>((channel, response))
    }).await.map_err(|_| Error::CommitUncertain)??;
    if response.len() > 16_384 {
        return Err(Error::Binding("bounded original Model read response"));
    }
    let response: wire::Response = serde_json::from_slice(&response)?;
    if response.request != request {
        return Err(Error::Binding("same original Model read request and response"));
    }
    client.context.authenticate(lower)?;
    channel.next += 1;
    Ok((channel, response.outcome))
}

fn canonical_digest(encoded: &str) -> Result<Digest32, Error> {
    let digest: Digest32 = encoded.parse().map_err(|_| Error::Binding("canonical Model material digest"))?;
    if digest.is_zero() || digest.to_string() != encoded {
        return Err(Error::Binding("canonical Model material digest"));
    }
    Ok(digest)
}

fn outcome_error(outcome: wire::Outcome) -> Error {
    match outcome {
        wire::Outcome::Missing => Error::Missing,
        wire::Outcome::Pending => Error::Pending,
        wire::Outcome::Busy => Error::Busy,
        wire::Outcome::Expired => Error::DeadlineExceeded,
        wire::Outcome::ReadbackRequired => Error::ReadbackRequired,
        wire::Outcome::Ineligible => Error::Ineligible,
        wire::Outcome::Unavailable => Error::Unavailable,
        _ => Error::CommitUncertain,
    }
}
