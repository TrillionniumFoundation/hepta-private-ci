//! One attenuated original Trainer channel, permanently read-only.
//! Original descriptor admission, peer identity and absolute lifetime survive
//! late binding. A complete read never combines pages from separate channels.

use std::sync::Arc;
use std::sync::Mutex;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_types::Digest32;

use super::Channel;
use super::OriginalCellQ24TrainingCommandClientV1;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::candidate_current;
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
    retained_heads: Mutex<Option<Vec<u8>>>,
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
            retained_heads: Mutex::new(None),
        })
    }

    /// Read complete pages once, then actual Current proofs on the same owner.
    /// Retained heads are model data only. No cached seal,
    /// successful prefix or late ACK is reused after an error or cancellation.
    /// Missing/Pending/NoUpdate never execute, initialize, recover or sign.
    pub async fn readback(&self) -> Result<OriginalCellQ24CandidateMaterialV1, Error> {
        let started_at = now()?;
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        if !channel.execution_requested {
            return Err(Error::Binding("permanently read-only Candidate connection"));
        }
        let context = self.context.clone();
        let material = self.material.clone();
        let dataset = self.dataset.clone();
        let expected = self.expected.clone();
        let baseline = Arc::clone(&self.baseline);
        let binding = self.binding;
        let completion = self.completion;
        let length = self.length;
        let retained_heads = self
            .retained_heads
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .clone();
        let (channel, candidate, last_at) = tokio::task::spawn_blocking(move || {
            let mut last_at =
                verify_original_context(&context, &material, &dataset, &expected, started_at)?;
            if signed_length(&context, &expected)? != length {
                return Err(Error::Binding("unchanged signed Candidate length"));
            }
            let heads = if let Some(heads) = retained_heads {
                if heads.len() != length {
                    return Err(Error::Binding("complete retained Candidate byte count"));
                }
                let request_id = channel.next_request_id;
                channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
                let request = candidate_current::Request::new(
                    &context, binding, completion, request_id, &heads,
                )?;
                let encoded = serde_json::to_vec(&request)
                    .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                let bytes = channel
                    .peer
                    .request(&encoded)
                    .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                let response: candidate_current::Response = serde_json::from_slice(&bytes)
                    .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                if response.request != request {
                    return Err(Error::Binding(
                        "exact Candidate Current purpose and full pin",
                    ));
                }
                match response.result {
                    candidate_wire::MaterialResult::Current {
                        completion,
                        heads,
                        total,
                    } if completion == request.completion
                        && heads == request.heads
                        && total == request.total => {}
                    candidate_wire::MaterialResult::Current { .. }
                    | candidate_wire::MaterialResult::Page { .. } => {
                        return Err(Error::Binding(
                            "same complete original Candidate Current proof",
                        ));
                    }
                    candidate_wire::MaterialResult::NoCandidate => return Err(Error::NoCandidate),
                    candidate_wire::MaterialResult::Missing => {
                        return Err(OriginalCellQ24TrainingCommandErrorV1::Missing.into());
                    }
                    candidate_wire::MaterialResult::Pending => {
                        return Err(OriginalCellQ24TrainingCommandErrorV1::Pending.into());
                    }
                    candidate_wire::MaterialResult::Busy => {
                        return Err(OriginalCellQ24TrainingCommandErrorV1::Busy.into());
                    }
                    candidate_wire::MaterialResult::ReadbackRequired => {
                        return Err(OriginalCellQ24TrainingCommandErrorV1::ReadbackRequired.into());
                    }
                    candidate_wire::MaterialResult::Uncertain => {
                        return Err(OriginalCellQ24TrainingCommandErrorV1::CommitUncertain.into());
                    }
                    candidate_wire::MaterialResult::Unavailable => return Err(Error::Unavailable),
                }
                channel
                    .peer
                    .check_peer_lifetime()
                    .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                last_at =
                    verify_original_context(&context, &material, &dataset, &expected, last_at)?;
                heads
            } else {
                let pages = length.div_ceil(candidate_wire::PAGE_BYTES);
                if pages == 0 || pages > candidate_wire::MAX_PAGES {
                    return Err(Error::Binding("bounded complete Candidate page count"));
                }
                let mut heads = Vec::with_capacity(length);
                for page in 0..pages {
                    let request_id = channel.next_request_id;
                    channel.next_request_id =
                        request_id.checked_add(1).ok_or(Error::Unavailable)?;
                    let request = candidate_wire::Request::new(
                        &context, binding, completion, request_id, page,
                    )?;
                    let encoded = serde_json::to_vec(&request)
                        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                    let bytes = channel
                        .peer
                        .request(&encoded)
                        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                    let response: candidate_wire::Response = serde_json::from_slice(&bytes)
                        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                    if response.request != request {
                        return Err(Error::Binding(
                            "exact Candidate purpose, page and full completion pin",
                        ));
                    }
                    let (offset, total, encoded_heads) = match response.result {
                        candidate_wire::MaterialResult::Page {
                            offset,
                            total,
                            heads,
                        } => (offset, total, heads),
                        candidate_wire::MaterialResult::Current { .. } => {
                            return Err(Error::Binding(
                                "Page response cannot be Candidate Current",
                            ));
                        }
                        candidate_wire::MaterialResult::NoCandidate => {
                            return Err(Error::NoCandidate);
                        }
                        candidate_wire::MaterialResult::Missing => {
                            return Err(OriginalCellQ24TrainingCommandErrorV1::Missing.into());
                        }
                        candidate_wire::MaterialResult::Pending => {
                            return Err(OriginalCellQ24TrainingCommandErrorV1::Pending.into());
                        }
                        candidate_wire::MaterialResult::Busy => {
                            return Err(OriginalCellQ24TrainingCommandErrorV1::Busy.into());
                        }
                        candidate_wire::MaterialResult::ReadbackRequired => {
                            return Err(
                                OriginalCellQ24TrainingCommandErrorV1::ReadbackRequired.into()
                            );
                        }
                        candidate_wire::MaterialResult::Uncertain => {
                            return Err(
                                OriginalCellQ24TrainingCommandErrorV1::CommitUncertain.into()
                            );
                        }
                        candidate_wire::MaterialResult::Unavailable => {
                            return Err(Error::Unavailable);
                        }
                    };
                    let expected_offset = page * candidate_wire::PAGE_BYTES;
                    let expected_page_length =
                        candidate_wire::PAGE_BYTES.min(length - expected_offset);
                    if offset as usize != expected_offset
                        || total as usize != length
                        || heads.len() != expected_offset
                        || encoded_heads.len() > candidate_wire::PAGE_BYTES.div_ceil(3) * 4
                    {
                        return Err(Error::Binding(
                            "signed Candidate length and consecutive page",
                        ));
                    }
                    let part = STANDARD_NO_PAD
                        .decode(&encoded_heads)
                        .map_err(|_| Error::Binding("Candidate page encoding"))?;
                    if part.len() != expected_page_length
                        || STANDARD_NO_PAD.encode(&part) != encoded_heads
                    {
                        return Err(Error::Binding("complete canonical Candidate page"));
                    }
                    // Peer liveness performs I/O. All original signature windows
                    // are checked only after that I/O and before retaining a page.
                    channel
                        .peer
                        .check_peer_lifetime()
                        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
                    last_at =
                        verify_original_context(&context, &material, &dataset, &expected, last_at)?;
                    heads.extend_from_slice(&part);
                }
                if heads.len() != length {
                    return Err(Error::Binding("complete original Candidate bytes"));
                }
                heads
            };
            // This verifies the final whole-head hash and exact rebuilt bundle,
            // then validates the actual changed row against the loaded baseline.
            let candidate = OriginalCellQ24CandidateMaterialV1::from_verified_readback(
                &baseline,
                &context.dataset,
                heads,
                expected.receipt().clone(),
                expected.attestation().clone(),
            )?;
            let last_at =
                verify_original_context(&context, &material, &dataset, &expected, last_at)?;
            Ok::<_, Error>((channel, candidate, last_at))
        })
        .await
        .map_err(|_| Error::Unavailable)??;
        // A cancelled future never restores the moved channel. The original
        // framer retains its first admission time throughout all pages/reads.
        channel
            .peer
            .check_peer_lifetime()
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        verify_original_context(
            &self.context,
            &self.material,
            &self.dataset,
            &self.expected,
            last_at,
        )?;
        {
            let mut retained = self
                .retained_heads
                .try_lock()
                .map_err(|_| Error::Unavailable)?;
            if retained
                .as_ref()
                .is_some_and(|heads| heads.as_slice() != candidate.heads())
            {
                return Err(Error::Binding("immutable complete Candidate heads"));
            }
            if retained.is_none() {
                *retained = Some(candidate.heads().to_vec());
            }
        }
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        Ok(candidate)
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
