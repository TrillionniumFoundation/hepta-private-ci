//! Hold the embedding's existing Ledger until the original launch has recovered
//! its Memory host, then transfer the actual Evaluator inbox once. No owner,
//! trust distribution, signature, trajectory or authorization is synthesized.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::StableId;
use tokio::sync::oneshot;

use super::AgentdProductionLaunch;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdRootPairedTrainingInputsV1;
use crate::PairedRecordPinsV1;
use crate::PairedTerminalCompositionV1;
use crate::PairedTerminalEvaluatorInboxV1;
use crate::TerminalLearningHandleV1;

type OriginalEvaluatorHandoff = (PairedTerminalEvaluatorInboxV1, TerminalLearningHandleV1);

pub(super) struct RetainedPairedLearningOwnersV1 {
    ledger: Arc<Mutex<LedgerWriter>>,
    producer: StableId,
    parameter_scope: String,
    maximum_jobs: usize,
    capacity: usize,
    composition: PairedTerminalCompositionV1,
    evaluator: oneshot::Sender<OriginalEvaluatorHandoff>,
}

/// Received only after the same launch installs its original production host,
/// fixed paired policy and original delivery. The handle permits only the
/// paired runtime's exact job readback; that profile rejects every new Train.
pub struct OriginalPairedEvaluatorInboxReceiverV1 {
    receiver: oneshot::Receiver<OriginalEvaluatorHandoff>,
    end: tokio::time::Instant,
}

impl OriginalPairedEvaluatorInboxReceiverV1 {
    pub async fn receive(
        self,
    ) -> Result<(PairedTerminalEvaluatorInboxV1, TerminalLearningHandleV1), AgentdError> {
        receive_before_original_end(self.receiver, self.end).await
    }
}

impl AgentdProductionLaunch {
    /// The embedding transfers only already-held owners after the original
    /// process handoff. Default CLI launch has no such Ledger and fails closed.
    /// The returned receiver must be retained by the actual late Evaluator.
    #[allow(clippy::too_many_arguments)]
    pub fn retain_original_paired_learning_owners_v1(
        mut self,
        ledger: Arc<Mutex<LedgerWriter>>,
        producer: StableId,
        parameter_scope: String,
        maximum_jobs: usize,
        capacity: usize,
        composition: PairedTerminalCompositionV1,
    ) -> Result<(Self, OriginalPairedEvaluatorInboxReceiverV1), AgentdError> {
        let (original, records) = self
            .paired_training
            .as_ref()
            .ok_or_else(|| refused("original paired launch handoff required"))?;
        if self.terminal_learning.is_some()
            || *records != composition.records
            || self.session_end <= Instant::now()
            || !(1..=16).contains(&maximum_jobs)
            || !(1..=64).contains(&capacity)
        {
            return Err(refused(
                "original paired launch owners are duplicated, mismatched or expired",
            ));
        }
        original.require_original_training_binding(
            &self.root.bootstrap.registered_identity.identity()?,
            &composition.original,
        )?;
        composition.original.validate()?;
        let (evaluator, receiver) = oneshot::channel();
        let end = tokio::time::Instant::from_std(self.session_end);
        self.terminal_learning = Some(RetainedPairedLearningOwnersV1 {
            ledger,
            producer,
            parameter_scope,
            maximum_jobs,
            capacity,
            composition,
            evaluator,
        });
        Ok((
            self,
            OriginalPairedEvaluatorInboxReceiverV1 { receiver, end },
        ))
    }
}

/// Called only after the original Notes host and original thread route exist.
/// Missing real embedding owners is a refusal, never a fixture fallback.
pub(super) async fn attach_original_paired_learning(
    config: AgentdConfig,
    owners: Option<RetainedPairedLearningOwnersV1>,
    original: AgentdRootPairedTrainingInputsV1,
    records: PairedRecordPinsV1,
    session_end: Instant,
) -> Result<AgentdConfig, AgentdError> {
    let owners =
        owners.ok_or_else(|| refused("original paired Ledger and Evaluator owners missing"))?;
    if owners.evaluator.is_closed() || session_end <= Instant::now() {
        return Err(refused(
            "original paired Evaluator disappeared or session expired",
        ));
    }
    original.require_original_training_binding(config.identity(), &owners.composition.original)?;
    let assembly_end = tokio::time::Instant::from_std(session_end)
        .min(tokio::time::Instant::now() + Duration::from_secs(/*secs*/ 30));
    let (config, handle, inbox) = config
        .with_original_terminal_learning_owners_v1(
            owners.ledger,
            owners.producer,
            owners.parameter_scope,
            owners.maximum_jobs,
            owners.capacity,
            owners.composition,
            assembly_end,
        )
        .await?;
    let config = original.install_original_terminal_consumer(config, records, session_end)?;
    if session_end <= Instant::now() {
        return Err(refused(
            "original paired session expired before Evaluator handoff",
        ));
    }
    owners
        .evaluator
        .send((inbox, handle))
        .map_err(|_| refused("original paired Evaluator disappeared during handoff"))?;
    Ok(config)
}

async fn receive_before_original_end<T>(
    receiver: oneshot::Receiver<T>,
    end: tokio::time::Instant,
) -> Result<T, AgentdError> {
    // timeout_at can observe an already-ready value. Explicit checks prevent
    // a queued response from reviving an expired original session.
    if tokio::time::Instant::now() >= end {
        return Err(refused(
            "original paired Evaluator handoff deadline expired",
        ));
    }
    let value = tokio::time::timeout_at(end, receiver)
        .await
        .map_err(|_| refused("original paired Evaluator handoff deadline expired"))?
        .map_err(|_| refused("original paired production launch disappeared"))?;
    if tokio::time::Instant::now() >= end {
        return Err(refused(
            "original paired Evaluator handoff deadline expired",
        ));
    }
    Ok(value)
}

fn refused(message: &str) -> AgentdError {
    AgentdError::Protocol(message.into())
}

#[cfg(test)]
#[path = "production_terminal_launch_tests.rs"]
mod tests;
