//! Original initial connection, consumed into one readonly T/E-bound client.
//! Lifetime and process identity begin at delivery, not at late binding.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;

use super::super::contract::Context;
use super::super::now;
use super::super::require_clock;
use super::Error;
use super::MAX_BYTES;
use super::MAX_PAGES;
use super::OriginalCellEvaluationModelMaterialV1;
use super::PAGE_BYTES;
use super::Receipt;
use super::verify;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

pub struct OriginalCellEvaluationModelMaterialConnectionV1 {
    channel: HostAuthorityPeerChannel,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    verifier: LearningEvidenceVerifierV1,
    observed_at: u64,
}

impl OriginalCellEvaluationModelMaterialConnectionV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        verifier: LearningEvidenceVerifierV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let empty =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())?;
        scope.validate_snapshot(&initial)?;
        if &initial != empty.snapshot()
            || peer.actor_id != initial.owners.evaluator
            || initial.request.evaluation_profile != registration.evaluation_profile()
            || initial.owners.evidence_trust_digest != verifier.trust_digest()
            || initial.request.envelope.objective_digest != verifier.objective_digest()
        {
            return Err(Error::Binding(
                "original empty Root binding and fixed Evaluator material process",
            ));
        }
        let channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_owner_pidfd,
            timeout,
            lifetime,
        )?;
        let observed_at = now()?;
        require_clock(started_at, observed_at)?;
        Ok(Self {
            channel,
            initial,
            scope,
            registration,
            verifier,
            observed_at,
        })
    }

    pub fn bind_original_training(
        self,
        dataset: LearningIterationSnapshotV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<OriginalCellEvaluationModelMaterialClientV1, Error> {
        self.finish_binding(dataset, training, /*expected*/ None)
    }

    pub fn bind_original_evaluation(
        self,
        dataset: LearningIterationSnapshotV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &Receipt,
    ) -> Result<OriginalCellEvaluationModelMaterialClientV1, Error> {
        self.finish_binding(dataset, training, Some(evaluation.clone()))
    }

    /// Exact initial delivery identity only; no peer I/O, time reset, or new
    /// authority is produced by this check. The original Model host checks it
    /// before retaining this connection alongside its original custody.
    pub(crate) fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        registration: &OriginalCellEvaluationPanelRegistrationV1,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        if &self.initial != initial
            || &self.scope != scope
            || &self.registration != registration
            || self.verifier.trust_digest() != verifier.trust_digest()
            || self.verifier.scope_digest() != verifier.scope_digest()
            || self.verifier.objective_digest() != verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original Model material initial delivery",
            ));
        }
        Ok(())
    }

    fn finish_binding(
        self,
        dataset: LearningIterationSnapshotV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        expected: Option<Receipt>,
    ) -> Result<OriginalCellEvaluationModelMaterialClientV1, Error> {
        let context = Context::from_original_training(
            dataset,
            self.scope,
            self.registration,
            self.verifier,
            training,
        )?;
        if context.initial()? != self.initial {
            return Err(Error::Binding("same original initial material connection"));
        }
        self.channel.check_peer_lifetime()?;
        let current = now()?;
        require_clock(self.observed_at, current)?;
        let binding = wire::context_binding(&context, current)?;
        if let Some(original) = &expected {
            wire::binding(&context, original, current)?;
        }
        Ok(OriginalCellEvaluationModelMaterialClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: self.channel,
                next: 1,
            })),
            context,
            expected: Mutex::new(expected),
            binding,
            observed_at: current,
            retained: Mutex::new(None),
        })
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next: u64,
}
pub struct OriginalCellEvaluationModelMaterialClientV1 {
    channel: Mutex<Option<Channel>>,
    context: Context,
    expected: Mutex<Option<Receipt>>,
    binding: Digest32,
    observed_at: u64,
    retained: Mutex<Option<Digest32>>,
}

struct Cancelled(Arc<AtomicBool>);
impl Drop for Cancelled {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

impl OriginalCellEvaluationModelMaterialClientV1 {
    /// Call outside the Trainer lane: the actual Evaluator reads its original
    /// Trainer evidence while checking the complete current B/retention panel.
    pub async fn read_current(&self) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        self.read_current_with_clock(now).await
    }

    async fn read_current_with_clock(
        &self,
        mut clock: impl FnMut() -> Result<u64, Error> + Send,
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started_at = clock()?;
        require_clock(self.observed_at, started_at)?;
        if wire::context_binding(&self.context, started_at)? != self.binding {
            return Err(Error::CommitUncertain);
        }
        let expected = self
            .expected
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .clone();
        if let Some(original) = &expected {
            wire::binding(&self.context, original, started_at)?;
        }
        let cancellation = Cancelled(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&cancellation.0);
        let binding = self.binding;
        let result = tokio::task::spawn_blocking(move || {
            let bytes = transfer(&mut channel, binding, &cancelled)?;
            channel.peer.check_peer_lifetime()?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        let (channel, bytes) = match result {
            Err(Error::Missing | Error::Pending) if expected.is_some() => {
                return Err(Error::CommitUncertain);
            }
            result => result?,
        };
        // The final peer/pidfd I/O has completed. All original windows and
        // signed commitments are checked at this fresh common time.
        let current = clock()?;
        require_clock(started_at, current)?;
        let body = super::codec::Body::decode(&bytes)?;
        let snapshot = crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1(
            &body.snapshot,
        )?;
        let (_, signed) = crate::learning_owner_evidence::decode(&body.evaluation)?;
        let evaluation =
            super::super::wire::authenticate_completed(&self.context, snapshot, signed, current)?;
        if expected
            .as_ref()
            .is_some_and(|original| original != &evaluation)
        {
            return Err(Error::Binding(
                "unchanged full original Evaluation in material",
            ));
        }
        verify::material(&self.context, &evaluation, &bytes, current)?;
        let digest = Digest32::of_bytes(&bytes);
        let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
        if retained.is_some_and(|old| old != digest) {
            return Err(Error::CommitUncertain);
        }
        *retained = Some(digest);
        let material = OriginalCellEvaluationModelMaterialV1 {
            context: self.context.clone(),
            evaluation: evaluation.clone(),
            bytes,
            binding: digest,
            observed_at: current,
        };
        *self.expected.try_lock().map_err(|_| Error::Unavailable)? = Some(evaluation);
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        drop(cancellation);
        Ok(material)
    }
}

fn request(
    channel: &mut Channel,
    binding: Digest32,
    read: wire::Read,
    cancelled: &AtomicBool,
) -> Result<wire::Outcome, Error> {
    if !(1..=128).contains(&channel.next) {
        return Err(Error::Unavailable);
    }
    let request = wire::Request::new(channel.next, binding, read);
    let bytes = serde_json::to_vec(&request)?;
    if bytes.len() > 16_384 {
        return Err(Error::Binding("bounded original material request"));
    }
    channel.peer.check_peer_lifetime()?;
    // Dropping a queued future prevents an as-yet unsent readonly request.
    // Already sent work remains an uncertain read; the connection is not saved.
    if cancelled.load(Ordering::Acquire) {
        return Err(Error::Unavailable);
    }
    let response = channel.peer.request(&bytes)?;
    if response.len() > 16_384 {
        return Err(Error::Binding("bounded original material frame"));
    }
    let response: wire::Response = serde_json::from_slice(&response)?;
    if response.request != request {
        return Err(Error::Binding(
            "same original material request and response",
        ));
    }
    channel.next += 1;
    Ok(response.outcome)
}

fn transfer(
    channel: &mut Channel,
    binding: Digest32,
    cancelled: &AtomicBool,
) -> Result<Vec<u8>, Error> {
    let transfer = channel.next;
    let first = request(channel, binding, wire::Read::Begin, cancelled)?;
    let mut result = Vec::new();
    let mut total = None;
    let mut digest = None;
    let mut outcome = first;
    for index in 0..MAX_PAGES {
        let (original, received, offset, complete, commitment, bytes) = match outcome {
            wire::Outcome::Page {
                transfer,
                index,
                offset,
                total,
                digest,
                bytes,
            } => (transfer, index, offset, total, digest, bytes),
            wire::Outcome::Missing if index == 0 => return Err(Error::Missing),
            wire::Outcome::Pending if index == 0 => return Err(Error::Pending),
            wire::Outcome::Busy if index == 0 => return Err(Error::Busy),
            _ => return Err(Error::CommitUncertain),
        };
        if original != transfer
            || received as usize != index
            || offset != result.len()
            || offset != index * PAGE_BYTES
            || complete == 0
            || complete > MAX_BYTES
            || total.is_some_and(|saved| saved != complete)
            || digest.as_ref().is_some_and(|saved| saved != &commitment)
            || bytes.len() > PAGE_BYTES.div_ceil(3) * 4
        {
            return Err(Error::Binding(
                "one exact original bounded material transfer",
            ));
        }
        let decoded = STANDARD_NO_PAD
            .decode(&bytes)
            .map_err(|_| Error::Binding("original material page encoding"))?;
        if offset >= complete
            || STANDARD_NO_PAD.encode(&decoded) != bytes
            || decoded.len() != PAGE_BYTES.min(complete - offset)
        {
            return Err(Error::Binding("canonical full original material page"));
        }
        result.extend_from_slice(&decoded);
        total = Some(complete);
        digest = Some(commitment.clone());
        if result.len() == complete {
            if Digest32::of_bytes(&result).to_string() != commitment {
                return Err(Error::CommitUncertain);
            }
            let final_read = request(
                channel,
                binding,
                wire::Read::Finish {
                    transfer,
                    digest: commitment.clone(),
                },
                cancelled,
            )?;
            match final_read {
                wire::Outcome::Completed {
                    transfer: original,
                    total,
                    digest,
                } if original == transfer && total == complete && digest == commitment => {
                    return Ok(result);
                }
                _ => return Err(Error::CommitUncertain),
            }
        }
        if index + 1 == MAX_PAGES {
            return Err(Error::Binding("original material page limit"));
        }
        outcome = request(
            channel,
            binding,
            wire::Read::Page {
                transfer,
                index: (index + 1) as u32,
            },
            cancelled,
        )?;
    }
    Err(Error::CommitUncertain)
}

#[cfg(test)]
#[path = "neuron_cell_evaluation_model_material_connection_support_tests.rs"]
mod tests;
