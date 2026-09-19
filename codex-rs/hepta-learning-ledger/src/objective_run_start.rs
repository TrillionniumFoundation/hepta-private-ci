use std::error::Error;
use std::fmt;

use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectivePublicationError;
use codex_hepta_objective::ObjectiveRunStartBindingsV1;
use codex_hepta_objective::ObjectiveRunStartPublicationV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::decode_objective_run_start_publication_v1;
use codex_hepta_objective::encode_objective_run_start_publication_v1;
use codex_hepta_objective::prepare_objective_run_start_v1;
use codex_hepta_types::Digest32;

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerEvent;
use crate::ObjectiveRunStartRecordV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunStartCommitV1 {
    pub publication: ObjectiveRunStartPublicationV1,
    pub append: AppendReceipt,
}

#[derive(Debug)]
pub enum ObjectiveRunStartCommitError {
    Objective(ObjectivePublicationError),
    Ledger(DurableLedgerError),
}

impl fmt::Display for ObjectiveRunStartCommitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Objective(error) => error.fmt(formatter),
            Self::Ledger(error) => error.fmt(formatter),
        }
    }
}

impl Error for ObjectiveRunStartCommitError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Objective(error) => Some(error),
            Self::Ledger(error) => Some(error),
        }
    }
}

impl From<ObjectivePublicationError> for ObjectiveRunStartCommitError {
    fn from(value: ObjectivePublicationError) -> Self {
        Self::Objective(value)
    }
}

impl From<DurableLedgerError> for ObjectiveRunStartCommitError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Ledger(value)
    }
}

/// Named product-composition boundary for objective compilation.
///
/// The independently authenticated context is admitted by objective.compiler;
/// the resulting immutable ObjectiveFunction/RunStartSnapshot bundle is encoded
/// canonically and appended as one fsync-bound learning-ledger frame. The
/// learning ledger remains the only durable writer. Retrying must use the
/// original predecessor and run identity.
pub fn append_objective_run_start_v1(
    ledger: &mut DurableLedger,
    expected_predecessor: Digest32,
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunStartBindingsV1,
) -> Result<ObjectiveRunStartCommitV1, ObjectiveRunStartCommitError> {
    let publication = prepare_objective_run_start_v1(envelope, profile, context, bindings)?;
    append_prepared_objective_run_start_v1(ledger, expected_predecessor, publication)
}

pub fn append_prepared_objective_run_start_v1(
    ledger: &mut DurableLedger,
    expected_predecessor: Digest32,
    publication: ObjectiveRunStartPublicationV1,
) -> Result<ObjectiveRunStartCommitV1, ObjectiveRunStartCommitError> {
    let publication_bytes = encode_objective_run_start_publication_v1(&publication)?;
    let run_start = publication.run_start();
    let event = LedgerEvent::RunStart(ObjectiveRunStartRecordV1 {
        record_id: run_start.run_id.clone(),
        run_id: run_start.run_id.clone(),
        objective_digest: run_start.objective_digest,
        hard_constraint_digest: run_start.hard_constraint_digest,
        publication_digest: publication.publication_digest(),
        publication_bytes,
    });
    let append = ledger.append(expected_predecessor, event)?;
    Ok(ObjectiveRunStartCommitV1 {
        publication,
        append,
    })
}

pub fn decode_objective_run_start_record_v1(
    record: &ObjectiveRunStartRecordV1,
) -> Result<ObjectiveRunStartPublicationV1, ObjectivePublicationError> {
    let publication = decode_objective_run_start_publication_v1(&record.publication_bytes)?;
    if publication.publication_digest() != record.publication_digest
        || publication.run_start().run_id != record.run_id
        || publication.run_start().objective_digest != record.objective_digest
        || publication.run_start().hard_constraint_digest != record.hard_constraint_digest
        || record.record_id != record.run_id
    {
        return Err(ObjectivePublicationError::PublicationDigestMismatch);
    }
    Ok(publication)
}

#[cfg(test)]
#[path = "objective_run_start_tests.rs"]
mod tests;
