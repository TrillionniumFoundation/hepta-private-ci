//! One attenuated original Trainer channel, permanently read-only.
//! Original descriptor admission, peer identity and absolute lifetime survive
//! late binding. A complete read never combines pages from separate channels.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_types::Digest32;

use super::Channel;
use super::OriginalCellQ24TrainingCommandClientV1;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::candidate_wire;
use super::now;
use super::wire;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24CandidateMaterialErrorV1;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24MaterialCommandErrorV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24CandidateReadbackErrorV1 {
    #[error("original Candidate readback binding: {0}")]
    Binding(&'static str),
    #[error("original Training completion has no candidate")]
    NoCandidate,
    #[error("original Candidate channel is unavailable")]
    Unavailable,
    #[error("original Trainer command: {0}")]
    Command(#[from] OriginalCellQ24TrainingCommandErrorV1),
    #[error("original Material context: {0}")]
    Context(#[from] OriginalCellQ24MaterialCommandErrorV1),
    #[error("original Candidate bytes: {0}")]
    Material(#[from] OriginalCellQ24CandidateMaterialErrorV1),
}

type Error = OriginalCellQ24CandidateReadbackErrorV1;

pub struct OriginalCellQ24CandidateReadbackClientV1 {
    channel: Mutex<Option<Channel>>,
    context: OriginalCellQ24TrainingCommandContextV1,
    binding: Digest32,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    expected: OriginalCellQ24TrainingCommandReceiptV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
    completion: Digest32,
    length: usize,
}

impl OriginalCellQ24CandidateReadbackClientV1 {
    /// Only the consuming initial-connection binding calls this seam. Its
    /// original live channel is moved, never reconstructed or given new time.
    pub(super) fn from_original_connection(
        original: OriginalCellQ24TrainingCommandClientV1,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        expected: OriginalCellQ24TrainingCommandReceiptV1,
        baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let OriginalCellQ24TrainingCommandClientV1 {
            channel,
            context,
            binding,
            retained,
        } = original;
        let mut channel = channel
            .into_inner()
            .map_err(|_| Error::Unavailable)?
            .ok_or(Error::Unavailable)?;
        // Even an originally Fresh connection is irreversibly attenuated.
        channel.execution_requested = true;
        if retained
            .into_inner()
            .map_err(|_| Error::Unavailable)?
            .as_ref()
            .is_some_and(|pin| pin != &expected)
            || context.dataset != *dataset.snapshot()
            || context.validate()? != material.initial
            || context.scope != material.scope
            || context.verifier.trust_digest() != material.verifier.trust_digest()
            || baseline.components() != &material.initial.request.selected_bundle.components
        {
            return Err(Error::Binding(
                "same original Candidate predecessor and baseline",
            ));
        }
        let length = signed_length(&context, &expected)?;
        let completion =
            candidate_wire::completion_digest(expected.receipt(), expected.attestation())?;
        channel
            .peer
            .check_peer_lifetime()
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        verify_original_context(&context, &material, &dataset, &expected, started_at)?;
        Ok(Self {
            channel: Mutex::new(Some(channel)),
            context,
            binding,
            material,
            dataset,
            expected,
            baseline,
            completion,
            length,
        })
    }

    /// Read one bounded Begin/Pages/Finish on the same original channel.
    /// Only Finish can release a Candidate; cancellation never restores a
    /// partial transfer or sends a later queued page as a new operation.
    pub async fn readback(&self) -> Result<OriginalCellQ24CandidateMaterialV1, Error> {
        let started_at = now()?;
        let mut channel = self.channel.try_lock().map_err(|_| Error::Unavailable)?
            .take().ok_or(Error::Unavailable)?;
        if !channel.execution_requested {
            return Err(Error::Binding("permanently read-only Candidate connection"));
        }
        let cancelled = CancelledCandidateRead(Arc::new(AtomicBool::new(false)));
        let cancellation = Arc::clone(&cancelled.0);
        let context = self.context.clone();
        let material = self.material.clone();
        let dataset = self.dataset.clone();
        let expected = self.expected.clone();
        let baseline = Arc::clone(&self.baseline);
        let binding = self.binding;
        let completion = self.completion;
        let length = self.length;
        let (channel, candidate, last_at) = tokio::task::spawn_blocking(move || {
            let mut last_at = verify_original_context(
                &context, &material, &dataset, &expected, started_at,
            )?;
            if signed_length(&context, &expected)? != length {
                return Err(Error::Binding("unchanged signed Candidate length"));
            }
            let pages = length.div_ceil(candidate_wire::PAGE_BYTES);
            let transfer = channel.next_request_id;
            if pages == 0 || pages > candidate_wire::MAX_PAGES
                || transfer == 0
                || transfer.checked_add(pages as u64).is_none_or(|last| last > 128)
            {
                return Err(Error::Binding("bounded complete Candidate transfer"));
            }
            let LearningIterationObservationV1::Training { candidate, .. } =
                &expected.receipt().observation else { return Err(Error::NoCandidate); };
            let heads_digest = candidate.components.heads;
            if heads_digest.is_zero() {
                return Err(Error::Binding("signed original Candidate heads digest"));
            }
            let mut heads = Vec::with_capacity(length);
            for page in 0..pages {
                let request = candidate_wire::Request::new(
                    &context, binding, completion, channel.next_request_id, page,
                )?;
                let result = exchange(&mut channel, &request, &cancellation)?;
                let (offset, total, encoded_heads, digest) = match result {
                    candidate_wire::MaterialResult::Page {
                        offset, total, heads, heads_digest,
                    } => (offset, total, heads, heads_digest),
                    other => return Err(response_error(other)),
                };
                let offset_expected = page * candidate_wire::PAGE_BYTES;
                let page_expected = candidate_wire::PAGE_BYTES.min(length - offset_expected);
                if offset as usize != offset_expected || total as usize != length
                    || heads.len() != offset_expected || digest != heads_digest.to_string()
                    || encoded_heads.len() > candidate_wire::PAGE_BYTES.div_ceil(3) * 4
                {
                    return Err(Error::Binding("signed Candidate length and consecutive page"));
                }
                let part = STANDARD_NO_PAD.decode(&encoded_heads)
                    .map_err(|_| Error::Binding("Candidate page encoding"))?;
                if part.len() != page_expected || STANDARD_NO_PAD.encode(&part) != encoded_heads {
                    return Err(Error::Binding("complete canonical Candidate page"));
                }
                last_at = verify_original_context(
                    &context, &material, &dataset, &expected, last_at,
                )?;
                heads.extend_from_slice(&part);
            }
            if heads.len() != length || Digest32::of_bytes(&heads) != heads_digest {
                return Err(Error::Binding("complete signed original Candidate body"));
            }
            let finish = candidate_wire::Request::finish(
                &context, binding, completion, channel.next_request_id, transfer,
            )?;
            match exchange(&mut channel, &finish, &cancellation)? {
                candidate_wire::MaterialResult::Finished { total, heads_digest: digest }
                    if total as usize == length && digest == heads_digest.to_string() => {}
                other => return Err(response_error(other)),
            }
            // Actual source/native/T Finish occurred above. This pure decoder
            // is the first point at which the staged bytes become a Candidate.
            last_at = verify_original_context(
                &context, &material, &dataset, &expected, last_at,
            )?;
            if cancellation.load(Ordering::Acquire) {
                return Err(OriginalCellQ24TrainingCommandErrorV1::Cancelled.into());
            }
            let candidate = OriginalCellQ24CandidateMaterialV1::from_verified_readback(
                &baseline, &context.dataset, heads,
                expected.receipt().clone(), expected.attestation().clone(),
            )?;
            let last_at = verify_original_context(
                &context, &material, &dataset, &expected, last_at,
            )?;
            Ok::<_, Error>((channel, candidate, last_at))
        }).await.map_err(|_| Error::Unavailable)??;
        channel.peer.check_peer_lifetime()
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        verify_original_context(
            &self.context, &self.material, &self.dataset, &self.expected, last_at,
        )?;
        let mut retained_channel = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
        if retained_channel.is_some() { return Err(Error::Unavailable); }
        *retained_channel = Some(channel);
        drop(retained_channel);
        drop(cancelled);
        Ok(candidate)
    }
}

struct CancelledCandidateRead(Arc<AtomicBool>);
impl Drop for CancelledCandidateRead {
    fn drop(&mut self) { self.0.store(true, Ordering::Release); }
}

fn exchange(
    channel: &mut Channel,
    request: &candidate_wire::Request,
    cancelled: &AtomicBool,
) -> Result<candidate_wire::MaterialResult, Error> {
    if !(1..=128).contains(&channel.next_request_id)
        || request.request_id != channel.next_request_id
    {
        return Err(Error::Binding("bounded original Candidate nonce"));
    }
    channel.peer.check_peer_lifetime()
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
    if cancelled.load(Ordering::Acquire) {
        return Err(OriginalCellQ24TrainingCommandErrorV1::Cancelled.into());
    }
    let encoded = serde_json::to_vec(request).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
    if encoded.len() > 16_384 {
        return Err(Error::Binding("bounded original Candidate request"));
    }
    let bytes = channel.peer.request(&encoded)
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
    if bytes.len() > 16_384 {
        return Err(Error::Binding("bounded original Candidate response"));
    }
    let response: candidate_wire::Response = serde_json::from_slice(&bytes)
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
    if &response.request != request {
        return Err(Error::Binding("exact Candidate purpose, page and full completion pin"));
    }
    channel.peer.check_peer_lifetime()
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
    if cancelled.load(Ordering::Acquire) {
        return Err(OriginalCellQ24TrainingCommandErrorV1::Cancelled.into());
    }
    channel.next_request_id += 1;
    Ok(response.result)
}

fn response_error(result: candidate_wire::MaterialResult) -> Error {
    use candidate_wire::MaterialResult as R;
    match result {
        R::NoCandidate => Error::NoCandidate,
        R::Missing => OriginalCellQ24TrainingCommandErrorV1::Missing.into(),
        R::Pending => OriginalCellQ24TrainingCommandErrorV1::Pending.into(),
        R::Busy => OriginalCellQ24TrainingCommandErrorV1::Busy.into(),
        R::ReadbackRequired => OriginalCellQ24TrainingCommandErrorV1::ReadbackRequired.into(),
        R::Uncertain | R::Finished { .. } => OriginalCellQ24TrainingCommandErrorV1::CommitUncertain.into(),
        R::Unavailable => Error::Unavailable,
        R::Page { .. } => Error::Binding("original Candidate response phase"),
    }
}

fn signed_length(
    context: &OriginalCellQ24TrainingCommandContextV1,
    expected: &OriginalCellQ24TrainingCommandReceiptV1,
) -> Result<usize, Error> {
    let LearningIterationObservationV1::Training { artifact_bytes, .. } =
        &expected.receipt().observation
    else {
        return Err(Error::NoCandidate);
    };
    let length = usize::try_from(*artifact_bytes)
        .map_err(|_| Error::Binding("signed Candidate byte count"))?;
    if !(12..=32_780).contains(&length)
        || *artifact_bytes > context.dataset.request.budget.maximum_artifact_bytes
    {
        return Err(Error::Binding(
            "existing Candidate asset and request bounds",
        ));
    }
    Ok(length)
}

fn verify_original_context(
    context: &OriginalCellQ24TrainingCommandContextV1,
    material: &OriginalCellQ24MaterialReceiptConfigV1,
    dataset: &OriginalCellQ24MaterialCommandReceiptV1,
    expected: &OriginalCellQ24TrainingCommandReceiptV1,
    minimum_now: u64,
) -> Result<u64, Error> {
    let checked_at = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
        dataset, material,
    )?;
    let fresh_now = now()?;
    if checked_at < minimum_now || fresh_now < checked_at {
        return Err(Error::Binding("Candidate readback clock moved backwards"));
    }
    let verified = wire::authenticate_receipt(
        context,
        expected.receipt().clone(),
        expected.attestation().clone(),
        fresh_now,
    )?;
    if &verified != expected {
        return Err(Error::Binding(
            "unchanged full original Generator signature",
        ));
    }
    Ok(fresh_now)
}
