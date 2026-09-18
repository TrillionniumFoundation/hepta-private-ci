//! Runtime consumption of a durably published intelligence host envelope.
//!
//! Agentd owns only the ephemeral run handle. Objective and RunStart facts
//! remain owned by their producers and the durable learning-ledger journal.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::ProductionObjectiveDispositionV1;
use codex_hepta_intelligence::ProductionObjectiveError;
use codex_hepta_intelligence::ProductionObjectiveStartReceiptV1;
use codex_hepta_intelligence::ProductionRunBindingsV1;
use codex_hepta_intelligence::prepare_intelligence_run_v1;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_types::Digest32;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::RunReceipt;
use crate::RunSnapshot;

pub struct ObjectiveProductRunRequestV1<'a, J> {
    pub now_ms: u64,
    pub body_digest: Digest32,
    pub journal: &'a mut J,
    pub source: &'a ObjectiveSourceEnvelopeV1,
    pub profile: &'a ObjectiveAdmissionProfileV1,
    pub context: &'a ObjectiveAdmissionContextV1,
    pub bindings: ProductionRunBindingsV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveProductRunDispositionV1 {
    Started {
        publication: ProductionObjectiveStartReceiptV1,
        runtime: RunReceipt,
    },
    NotRunnable(ProductionObjectiveDispositionV1),
}

#[derive(Debug)]
pub enum ObjectiveProductRunError {
    Prepare(ProductionObjectiveError),
    Runtime {
        publication: Box<ProductionObjectiveStartReceiptV1>,
        error: ObjectiveHostError,
    },
}

impl ObjectiveProductRunError {
    #[must_use]
    pub fn durable_publication(&self) -> Option<&ProductionObjectiveStartReceiptV1> {
        match self {
            Self::Prepare(_) => None,
            Self::Runtime { publication, .. } => Some(publication),
        }
    }
}

impl fmt::Display for ObjectiveProductRunError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Prepare(error) => write!(formatter, "product objective preparation failed: {error}"),
            Self::Runtime { error, .. } => {
                write!(formatter, "durable objective could not enter runtime: {error}")
            }
        }
    }
}

impl StdError for ObjectiveProductRunError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Prepare(error) => Some(error),
            Self::Runtime { error, .. } => Some(error),
        }
    }
}

#[derive(Debug)]
pub enum ObjectiveHostError {
    Envelope(ProductionObjectiveError),
    DeadlineMissing,
    Runtime(AgentRunError),
}

impl fmt::Display for ObjectiveHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Envelope(error) => {
                write!(formatter, "invalid intelligence host envelope: {error}")
            }
            Self::DeadlineMissing => {
                formatter.write_str("production objective run requires an admitted deadline")
            }
            Self::Runtime(error) => write!(formatter, "agent run admission failed: {error:?}"),
        }
    }
}

impl StdError for ObjectiveHostError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Envelope(error) => Some(error),
            Self::DeadlineMissing | Self::Runtime(_) => None,
        }
    }
}

/// Authenticate, compile, durably publish and admit one objective run.
///
/// The durable owner append completes before Agentd creates ephemeral run state.
/// If runtime admission then fails, the error retains the exact durable
/// publication receipt so a reconciler can retry the same bounded inputs and
/// observe an idempotent ledger append before attempting runtime admission again.
pub fn prepare_and_start_intelligence_run_v1<J: DurableLearningJournal>(
    coordinator: &mut AgentRunCoordinator,
    request: ObjectiveProductRunRequestV1<'_, J>,
) -> Result<ObjectiveProductRunDispositionV1, ObjectiveProductRunError> {
    let disposition = prepare_intelligence_run_v1(
        request.journal,
        request.source,
        request.profile,
        request.context,
        request.bindings,
    )
    .map_err(ObjectiveProductRunError::Prepare)?;

    match disposition {
        ProductionObjectiveDispositionV1::Published(publication) => {
            match start_published_intelligence_run_v1(
                coordinator,
                request.now_ms,
                &publication,
                request.body_digest,
            ) {
                Ok(runtime) => Ok(ObjectiveProductRunDispositionV1::Started {
                    publication,
                    runtime,
                }),
                Err(error) => Err(ObjectiveProductRunError::Runtime {
                    publication: Box::new(publication),
                    error,
                }),
            }
        }
        other => Ok(ObjectiveProductRunDispositionV1::NotRunnable(other)),
    }
}

/// Consume one already-durable objective publication into Agentd's ephemeral
/// run coordinator.
///
/// The opaque publication receipt can only be produced after the sealed durable
/// journal has accepted the complete admission/objective/RunStart event. Agentd
/// therefore does not expose the raw digest envelope as a public start surface.
/// No durable objective bytes are copied into Agentd; only exact digest bindings
/// survive in the ephemeral run coordinator.
pub fn start_published_intelligence_run_v1(
    coordinator: &mut AgentRunCoordinator,
    now_ms: u64,
    publication: &ProductionObjectiveStartReceiptV1,
    body_digest: Digest32,
) -> Result<RunReceipt, ObjectiveHostError> {
    publication
        .validate()
        .map_err(ObjectiveHostError::Envelope)?;
    start_host_envelope_v1(
        coordinator,
        now_ms,
        publication.host_envelope(),
        body_digest,
    )
}

fn start_host_envelope_v1(
    coordinator: &mut AgentRunCoordinator,
    now_ms: u64,
    envelope: &IntelligenceHostEnvelopeV1,
    body_digest: Digest32,
) -> Result<RunReceipt, ObjectiveHostError> {
    envelope.validate().map_err(ObjectiveHostError::Envelope)?;
    let deadline_micros = envelope
        .deadline_unix_micros()
        .ok_or(ObjectiveHostError::DeadlineMissing)?;
    let deadline_ms = deadline_micros / 1_000;
    let run_start = envelope.run_start();

    coordinator
        .start_run(
            now_ms,
            RunSnapshot {
                run_id: run_start.run_id.to_string(),
                request_digest: envelope.admitted_source_digest().to_string(),
                objective_digest: run_start.objective_digest.to_string(),
                body_digest: body_digest.to_string(),
                artifact_set_digest: run_start.artifact_set_digest.to_string(),
                authority_epoch: run_start.authority_epoch,
                generation: run_start.generation,
                fence_digest: run_start.fence_digest.to_string(),
                deadline_ms,
            },
        )
        .map_err(ObjectiveHostError::Runtime)
}

#[cfg(test)]
#[path = "objective_host_tests.rs"]
mod tests;
