use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::ObjectiveRunStartCommitError;
use codex_hepta_learning_ledger::append_prepared_objective_run_start_v1;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectivePublicationError;
use codex_hepta_objective::ObjectiveRunStartBindingsV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::prepare_objective_run_start_v1;
use codex_hepta_types::Digest32;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::ObjectiveRunStartRuntimeBindings;
use crate::RunReceipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRuntimeStartReceiptV1 {
    pub publication_digest: Digest32,
    pub ledger_sequence: u64,
    pub durable_replay: bool,
    pub run: RunReceipt,
}

#[derive(Debug)]
pub enum ObjectiveRuntimeStartError {
    Objective(ObjectivePublicationError),
    Durable(ObjectiveRunStartCommitError),
    Runtime(AgentRunError),
}

impl fmt::Display for ObjectiveRuntimeStartError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Objective(error) => error.fmt(formatter),
            Self::Durable(error) => error.fmt(formatter),
            Self::Runtime(error) => error.fmt(formatter),
        }
    }
}

impl Error for ObjectiveRuntimeStartError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Objective(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::Runtime(error) => Some(error),
        }
    }
}

/// Product composition for a bounded objective run.
///
/// Ordering is deliberate: objective admission/compilation is pure, Agentd
/// preflights the frozen snapshot without mutation, the learning-ledger owner
/// fsyncs the immutable publication, and only then does Agentd admit the
/// ephemeral run. A crash after fsync and before runtime admission is
/// recoverable by replaying the durable publication; no objective semantics
/// need to be re-derived.
pub fn publish_and_start_objective_run_v1(
    ledger: &mut DurableLedger,
    coordinator: &mut AgentRunCoordinator,
    expected_predecessor: Digest32,
    now_ms: u64,
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunStartBindingsV1,
    runtime_bindings: ObjectiveRunStartRuntimeBindings,
) -> Result<ObjectiveRuntimeStartReceiptV1, ObjectiveRuntimeStartError> {
    let publication = prepare_objective_run_start_v1(envelope, profile, context, bindings)
        .map_err(ObjectiveRuntimeStartError::Objective)?;
    coordinator
        .preflight_objective_run(now_ms, publication.run_start(), &runtime_bindings)
        .map_err(ObjectiveRuntimeStartError::Runtime)?;
    let durable =
        append_prepared_objective_run_start_v1(ledger, expected_predecessor, publication)
            .map_err(ObjectiveRuntimeStartError::Durable)?;
    let run = coordinator
        .start_objective_run(now_ms, durable.publication.run_start(), runtime_bindings)
        .map_err(ObjectiveRuntimeStartError::Runtime)?;
    Ok(ObjectiveRuntimeStartReceiptV1 {
        publication_digest: durable.publication.publication_digest(),
        ledger_sequence: durable.append.sequence.get(),
        durable_replay: durable.append.disposition == AppendDisposition::IdempotentReplay,
        run,
    })
}
