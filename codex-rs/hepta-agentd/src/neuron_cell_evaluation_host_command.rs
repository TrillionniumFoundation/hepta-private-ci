//! A keyless Evaluation command connection, bound before future Training.
//! Late binding consumes the same original channel and never restarts its
//! monotonic lifetime or restores a spent execution request.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::Receipt;
use super::contract::Context;
use super::now;
use super::require_clock;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Origin {
    Fresh,
    ReadbackOnly,
}

pub struct OriginalCellEvaluationCommandConnectionV1 {
    channel: HostAuthorityPeerChannel,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    verifier: LearningEvidenceVerifierV1,
    origin: Origin,
    observed_at: u64,
}

impl OriginalCellEvaluationCommandConnectionV1 {
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
        Self::bind_initial(
            stream,
            peer,
            original_owner_pidfd,
            initial,
            scope,
            registration,
            verifier,
            timeout,
            lifetime,
            Origin::Fresh,
        )
    }

    pub fn recover_from_original_stream(
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
        Self::bind_initial(
            stream,
            peer,
            original_owner_pidfd,
            initial,
            scope,
            registration,
            verifier,
            timeout,
            lifetime,
            Origin::ReadbackOnly,
        )
    }

    fn bind_initial(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        verifier: LearningEvidenceVerifierV1,
        timeout: Duration,
        lifetime: Duration,
        origin: Origin,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let expected =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())?;
        scope.validate_snapshot(&initial)?;
        if &initial != expected.snapshot()
            || peer.actor_id != initial.owners.evaluator
            || initial.request.evaluation_profile != registration.evaluation_profile()
            || initial.owners.evidence_trust_digest != verifier.trust_digest()
            || initial.request.envelope.objective_digest != verifier.objective_digest()
        {
            return Err(Error::Binding(
                "original empty Root cut and fixed Evaluator process",
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
            origin,
            observed_at,
        })
    }

    /// The actual opaque SourceBound Trainer result supplies the future cut.
    /// No caller can set an execution flag or substitute future B material.
    pub fn bind_original_training(
        self,
        dataset: LearningIterationSnapshotV1,
        original: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<OriginalCellEvaluationCommandClientV1, Error> {
        let context = Context::from_original_training(
            dataset,
            self.scope.clone(),
            self.registration.clone(),
            self.verifier.clone(),
            original,
        )?;
        let origin = self.origin;
        self.finish_binding(context, origin, /*retained*/ None)
    }

    /// Restore only reads of the exact original protected checkpoint. A cold
    /// connection, or this explicit attenuation, can never issue Execute.
    pub fn bind_recovered_training(
        self,
        training: LearningIterationSnapshotV1,
        training_evidence: SignedLearningEvidenceV1,
        expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
    ) -> Result<OriginalCellEvaluationCommandClientV1, Error> {
        let context = Context::from_checkpoint(
            training,
            self.scope.clone(),
            self.registration.clone(),
            training_evidence,
            self.verifier.clone(),
        )?;
        let retained = expected
            .map(|(snapshot, signed)| {
                wire::authenticate_completed(&context, snapshot, signed, now()?)
            })
            .transpose()?;
        self.finish_binding(context, Origin::ReadbackOnly, retained)
    }

    fn finish_binding(
        self,
        context: Context,
        origin: Origin,
        retained: Option<Receipt>,
    ) -> Result<OriginalCellEvaluationCommandClientV1, Error> {
        if context.initial()? != self.initial
            || context.scope != self.scope
            || context.registration != self.registration
            || context.verifier.trust_digest() != self.verifier.trust_digest()
            || context.verifier.scope_digest() != self.verifier.scope_digest()
            || context.verifier.objective_digest() != self.verifier.objective_digest()
            || (self.origin == Origin::ReadbackOnly && origin != Origin::ReadbackOnly)
        {
            return Err(Error::Binding(
                "same original Evaluation connection and readonly origin",
            ));
        }
        self.channel.check_peer_lifetime()?;
        let current = now()?;
        require_clock(self.observed_at, current)?;
        let binding = context.binding(current)?;
        if let Some(expected) = &retained
            && wire::authenticate_completed(
                &context,
                expected.snapshot.clone(),
                expected.attestation.clone(),
                current,
            )? != *expected
        {
            return Err(Error::Binding("same original recovered Evaluation"));
        }
        Ok(OriginalCellEvaluationCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: self.channel,
                next_request_id: 1,
                execution_requested: origin == Origin::ReadbackOnly,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
        })
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}
pub struct OriginalCellEvaluationCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: Context,
    binding: Digest32,
    retained: Mutex<Option<Receipt>>,
}

struct QueuedCancellation(Arc<AtomicBool>);
impl Drop for QueuedCancellation {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

impl OriginalCellEvaluationCommandClientV1 {
    pub async fn execute_evaluation(&self) -> Result<Receipt, Error> {
        if now()? >= self.context.training.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<Receipt, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCellEvaluationCommandClientV1::readback(self).await?;
        if &original.receipt != expected {
            return Err(Error::Binding("exact original Evaluation receipt"));
        }
        Ok(original.attestation)
    }

    async fn exchange(&self, action: wire::Action) -> Result<Receipt, Error> {
        let started_at = now()?;
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
        let cancellation = QueuedCancellation(Arc::new(AtomicBool::new(false)));
        let queued = Arc::clone(&cancellation.0);
        self.context.authenticate(started_at)?;
        let request_id = channel.next_request_id;
        if !(1..=128).contains(&request_id) {
            return Err(Error::Unavailable);
        }
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request = wire::Request::new(&self.context, self.binding, request_id, action);
        let encoded = serde_json::to_vec(&request)?;
        if encoded.len() > 16_384 {
            return Err(Error::Binding("bounded Evaluation request"));
        }
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            // Dropping the outer future before actual dispatch permanently
            // consumes this original channel, including while queued.
            if action == wire::Action::Execute && queued.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            let bytes = channel
                .peer
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        channel.peer.check_peer_lifetime()?;
        let current = now()?;
        require_clock(started_at, current)?;
        self.context.authenticate(current)?;
        let result = match response.outcome {
            wire::Outcome::Completed {
                snapshot,
                original_evidence,
            } => {
                let original =
                    wire::decode_completed(&self.context, snapshot, original_evidence, current)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained.as_ref().is_some_and(|saved| saved != &original) {
                    return Err(Error::Binding(
                        "unchanged full original Evaluation signature",
                    ));
                }
                *retained = Some(original.clone());
                Ok(original)
            }
            wire::Outcome::Missing | wire::Outcome::Pending
                if self
                    .retained
                    .try_lock()
                    .map_err(|_| Error::Unavailable)?
                    .is_some() =>
            {
                // An observed original Completed cannot regress to absence or
                // Pending, including a full expected signature supplied at cold
                // binding. Do not return this channel to its original slot.
                return Err(Error::CommitUncertain);
            }
            wire::Outcome::Missing => Err(Error::Missing),
            wire::Outcome::Pending => Err(Error::Pending),
            wire::Outcome::Busy => Err(Error::Busy),
            wire::Outcome::Expired => Err(Error::DeadlineExceeded),
            wire::Outcome::ReadbackRequired => Err(Error::ReadbackRequired),
            wire::Outcome::PredecessorUnavailable => return Err(Error::PredecessorUnavailable),
            wire::Outcome::Uncertain => return Err(Error::CommitUncertain),
        };
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        drop(cancellation);
        result
    }
}

#[cfg(test)]
#[path = "neuron_cell_evaluation_host_support_tests.rs"]
mod test_access;
