//! One original delivery and one late Evaluator exchange under the existing
//! terminal owner. Channel possession is not signature or training authority.

use std::time::Duration;

use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::AgentdTerminalLearningOwnerV1;
use crate::PairedRecordPinsV1;
use crate::PairedTrainingPlanV1;
use crate::TerminalLearningErrorV1;
use crate::TerminalLearningReceiptV1;
use crate::TerminalLearningRequestV1;
use crate::paired_preparation::training::consumer::OriginalPairedTrainingDelivery;
use crate::terminal_learning::PairedTerminalBindingPlanV1;
use crate::terminal_learning::PairedTerminalEventPairV1;
use crate::terminal_learning::PairedTerminalLearningReceiptV1;

use super::TerminalLearningRuntimeBootstrapV1;
use super::require_ready;

/// Explicit composition metadata. These pins neither construct a Ledger owner
/// nor authorize Memory use, manufacture labels, or replace a late signature.
#[derive(Clone, Debug)]
pub struct PairedTerminalCompositionV1 {
    pub original: PairedTrainingPlanV1,
    pub records: PairedRecordPinsV1,
    pub training: TerminalLearningRequestV1,
    pub failure_decision: Digest32,
    pub failure_outcome: Digest32,
    pub correction_decision: Digest32,
    pub correction_outcome: Digest32,
}

/// The original Evaluator receives the exact late payload, then supplies its
/// real signed evidence. The terminal owner verifies the original trust table.
pub struct PairedTerminalEvaluatorRequestV1 {
    payload: Vec<u8>,
    prepared_at: u64,
    end: Instant,
    reply: oneshot::Sender<SignedLearningEvidenceV1>,
    completion: oneshot::Receiver<Result<TerminalLearningReceiptV1, TerminalLearningErrorV1>>,
}

impl PairedTerminalEvaluatorRequestV1 {
    pub fn signing_payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn prepared_at(&self) -> u64 {
        self.prepared_at
    }

    /// A successful reply is the existing native fit's receipt. Sending a
    /// signature alone never reports successful training.
    pub async fn submit_signed_evidence(
        self,
        evidence: SignedLearningEvidenceV1,
    ) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        if Instant::now() >= self.end {
            return Err(TerminalLearningErrorV1::DeadlineExceeded);
        }
        self.reply
            .send(evidence)
            .map_err(|_| TerminalLearningErrorV1::Unavailable)?;
        let result = tokio::time::timeout_at(self.end, self.completion)
            .await
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        // A ready completion cannot revive an expired original exchange.
        if Instant::now() >= self.end {
            return Err(TerminalLearningErrorV1::CommitUncertain);
        }
        result
    }
}

/// Single receiver retained by the explicit Evaluator integration. A missing
/// receiver is a refusal; the runtime never invents a local signing key.
pub struct PairedTerminalEvaluatorInboxV1 {
    receiver: mpsc::Receiver<PairedTerminalEvaluatorRequestV1>,
}

impl PairedTerminalEvaluatorInboxV1 {
    pub async fn receive(&mut self) -> Option<PairedTerminalEvaluatorRequestV1> {
        self.receiver.recv().await
    }
}

pub(crate) struct PairedTerminalEvaluatorPeerV1 {
    sender: mpsc::Sender<PairedTerminalEvaluatorRequestV1>,
}

pub(crate) fn paired_terminal_evaluator_channel_v1() -> (
    PairedTerminalEvaluatorPeerV1,
    PairedTerminalEvaluatorInboxV1,
) {
    let (sender, receiver) = mpsc::channel(1);
    (
        PairedTerminalEvaluatorPeerV1 { sender },
        PairedTerminalEvaluatorInboxV1 { receiver },
    )
}

pub(super) struct PairedTerminalRuntimeV1 {
    plan: PairedTerminalBindingPlanV1,
    evaluator: PairedTerminalEvaluatorPeerV1,
    delivery: Option<(oneshot::Receiver<OriginalPairedTrainingDelivery>, Instant)>,
}

impl TerminalLearningRuntimeBootstrapV1 {
    pub(crate) fn with_original_paired_composition(
        self,
        metadata: PairedTerminalCompositionV1,
    ) -> Result<(Self, PairedTerminalEvaluatorInboxV1), AgentdError> {
        if [
            metadata.records.failure_record_digest,
            metadata.records.correction_record_digest,
            metadata.failure_decision,
            metadata.failure_outcome,
            metadata.correction_decision,
            metadata.correction_outcome,
        ]
        .iter()
        .any(Digest32::is_zero)
        {
            return Err(refused(
                "paired composition requires nonzero independent pins",
            ));
        }
        let plan = PairedTerminalBindingPlanV1 {
            original: metadata.original,
            records: metadata.records,
            training: metadata.training,
            failure: PairedTerminalEventPairV1 {
                decision: metadata.failure_decision,
                outcome: metadata.failure_outcome,
            },
            correction: PairedTerminalEventPairV1 {
                decision: metadata.correction_decision,
                outcome: metadata.correction_outcome,
            },
        };
        let (evaluator, inbox) = paired_terminal_evaluator_channel_v1();
        Ok((self.with_original_paired_policy(plan, evaluator)?, inbox))
    }

    pub(crate) fn with_original_paired_policy(
        mut self,
        plan: PairedTerminalBindingPlanV1,
        evaluator: PairedTerminalEvaluatorPeerV1,
    ) -> Result<Self, AgentdError> {
        if self.paired.is_some() || evaluator.sender.is_closed() {
            return Err(refused("one live original paired Evaluator required"));
        }
        plan.original.validate()?;
        plan.training
            .job_digest(self.owner.agent_id(), self.owner.producer_id())
            .map_err(|error| refused(error.to_string()))?;
        self.paired = Some(PairedTerminalRuntimeV1 {
            plan,
            evaluator,
            delivery: None,
        });
        Ok(self)
    }

    pub(crate) fn require_original_paired_policy(
        &self,
        original: &PairedTrainingPlanV1,
        records: PairedRecordPinsV1,
    ) -> Result<(), AgentdError> {
        let paired = self
            .paired
            .as_ref()
            .ok_or_else(|| refused("original paired terminal policy missing"))?;
        if paired.plan.original != *original
            || paired.plan.records != records
            || paired.evaluator.sender.is_closed()
            || paired.delivery.is_some()
        {
            return Err(refused(
                "original paired terminal policy differs or is consumed",
            ));
        }
        Ok(())
    }

    pub(crate) fn install_original_paired_delivery(
        &mut self,
        delivery: oneshot::Receiver<OriginalPairedTrainingDelivery>,
        end: std::time::Instant,
    ) -> Result<(), AgentdError> {
        let paired = self
            .paired
            .as_mut()
            .ok_or_else(|| refused("original paired terminal owner missing"))?;
        if paired.delivery.is_some()
            || paired.evaluator.sender.is_closed()
            || end <= std::time::Instant::now()
        {
            return Err(refused("original paired delivery is duplicated or expired"));
        }
        paired.delivery = Some((delivery, Instant::from_std(end)));
        Ok(())
    }
}

impl PairedTerminalRuntimeV1 {
    pub(super) async fn run(
        self,
        owner: &AgentdTerminalLearningOwnerV1,
        state: &AgentdState,
        cancellation: &CancellationToken,
        clock: &(impl Fn() -> Result<u64, TerminalLearningErrorV1> + Send + Sync),
    ) -> Result<PairedTerminalLearningReceiptV1, AgentdError> {
        let (delivery, original_end) = self
            .delivery
            .ok_or_else(|| refused("paired terminal policy has no original delivery owner"))?;
        let delivery = tokio::select! {
            _ = cancellation.cancelled() => return Err(refused("paired intake owner cancelled")),
            result = tokio::time::timeout_at(original_end, delivery) => result
                .map_err(|_| refused("original paired session expired"))?
                .map_err(|_| refused("original paired material consumer disappeared"))?,
        };
        // This end is sampled once, before preparation. Neither the signature
        // request nor its response can restart the original work budget.
        let end = original_end.min(
            Instant::now()
                + Duration::from_millis(self.plan.training.budget.maximum_wall_milliseconds),
        );
        require_ready(state).map_err(|error| refused(error.to_string()))?;
        let prepared = tokio::select! {
            _ = cancellation.cancelled() => return Err(refused("paired intake owner cancelled")),
            result = owner.prepare_paired_original_v1(delivery, self.plan, clock()
                .map_err(|error| refused(error.to_string()))?, end) => result
                .map_err(|error| refused(error.to_string()))?,
        };
        let payload = prepared.signing_payload().to_vec();
        if payload.is_empty() || payload.len() > 65_536 {
            return Err(refused("paired Evaluator payload exceeds its bound"));
        }
        let (reply, signature) = oneshot::channel();
        let (completion, completed) = oneshot::channel();
        self.evaluator
            .sender
            .try_send(PairedTerminalEvaluatorRequestV1 {
                payload,
                prepared_at: prepared.prepared_at(),
                end,
                reply,
                completion: completed,
            })
            .map_err(|_| refused("original paired Evaluator unavailable"))?;
        let evidence = tokio::select! {
            _ = cancellation.cancelled() => return Err(refused("paired intake owner cancelled")),
            result = tokio::time::timeout_at(end, signature) => result
                .map_err(|_| refused("original paired signature deadline expired"))?
                .map_err(|_| refused("original paired Evaluator abandoned its request"))?,
        };
        if completion.is_closed() {
            return Err(refused("paired Evaluator abandoned training before fit"));
        }
        let result = tokio::select! {
            _ = cancellation.cancelled() => Err(TerminalLearningErrorV1::CommitUncertain),
            result = async {
                require_ready(state)?;
                owner.consume_paired_original_v1(prepared, evidence, clock()?).await
            } => result,
        };
        match result {
            Ok(receipt) => {
                let result = require_ready(state)
                    .map(|()| receipt.training.clone())
                    .map_err(|_| TerminalLearningErrorV1::CommitUncertain);
                let _ = completion.send(result);
                // The runtime retains the original bytes, association and
                // native result; only a native receipt clone crosses the reply.
                // An exact native job cache hit is an existing candidate, not
                // proof of newly performed training for this delivery.
                Ok(receipt)
            }
            Err(error) => {
                let _ = completion.send(Err(error.clone()));
                Err(refused(error.to_string()))
            }
        }
    }
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::Protocol(message.into())
}
