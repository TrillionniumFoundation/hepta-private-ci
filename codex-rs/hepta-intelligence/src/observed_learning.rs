use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_types::Digest32;

#[derive(Debug)]
pub enum ObservedLearningErrorV1 {
    EmptyPredecessor,
    Ledger(DurableLedgerError),
}

impl fmt::Display for ObservedLearningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ObservedLearningErrorV1 {}

/// Append an externally supplied outcome observation after a durable Decision.
///
/// The facade does not derive or reinterpret the observation. The learning-ledger
/// owner validates episode existence, revocation state, observer independence,
/// record identity and idempotency before the append becomes durable.
pub fn record_observed_outcome_v1(
    ledger: &mut dyn DurableLearningJournal,
    expected_predecessor: Digest32,
    outcome: OutcomeObservation,
) -> Result<AppendReceipt, ObservedLearningErrorV1> {
    if expected_predecessor.is_zero() {
        return Err(ObservedLearningErrorV1::EmptyPredecessor);
    }
    ledger
        .append(expected_predecessor, LedgerEvent::Outcome(outcome))
        .map_err(ObservedLearningErrorV1::Ledger)
}

/// Append an externally supplied credit assignment after a terminal Outcome.
///
/// Credit is never synthesized from the decision or outcome by this facade. The
/// learning-ledger owner validates the outcome/episode binding, terminality,
/// revocation state and one-credit-per-target invariant.
pub fn record_observed_credit_v1(
    ledger: &mut dyn DurableLearningJournal,
    expected_predecessor: Digest32,
    credit: CreditAssignment,
) -> Result<AppendReceipt, ObservedLearningErrorV1> {
    if expected_predecessor.is_zero() {
        return Err(ObservedLearningErrorV1::EmptyPredecessor);
    }
    ledger
        .append(expected_predecessor, LedgerEvent::Credit(credit))
        .map_err(ObservedLearningErrorV1::Ledger)
}
