//! Durable post-dispatch Outcome -> Credit closure.
//!
//! This adapter never invents observations or credit. A host supplies already
//! authenticated owner records and the exact durable Decision predecessor.
//! Outcome and Credit are appended through the existing sealed learning journal.

use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureRequestV1 {
    pub expected_decision_head: Digest32,
    pub outcome: OutcomeObservation,
    pub credit: CreditAssignment,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureReceiptV1 {
    pub outcome: AppendReceipt,
    pub credit: AppendReceipt,
    pub closure_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum OutcomeCreditClosureErrorV1 {
    Binding(&'static str),
    Ledger(DurableLedgerError),
}

impl fmt::Display for OutcomeCreditClosureErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for OutcomeCreditClosureErrorV1 {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Ledger(error) => Some(error),
            Self::Binding(_) => None,
        }
    }
}

/// Append a terminal observed outcome and exactly one credit assignment.
///
/// The function deliberately performs no observation, scoring or allocation.
/// If the Credit append fails after Outcome sync, the Outcome remains durable;
/// retry with the same original Decision predecessor and identical records is
/// safe because the journal's exact-record replay is idempotent.
pub fn append_outcome_and_credit_v1(
    ledger: &mut dyn DurableLearningJournal,
    request: OutcomeCreditClosureRequestV1,
) -> Result<OutcomeCreditClosureReceiptV1, OutcomeCreditClosureErrorV1> {
    if request.expected_decision_head.is_zero() {
        return Err(OutcomeCreditClosureErrorV1::Binding(
            "empty decision predecessor",
        ));
    }
    if request.outcome.finality != OutcomeFinality::Terminal {
        return Err(OutcomeCreditClosureErrorV1::Binding(
            "outcome is not terminal",
        ));
    }
    if request.outcome.support_digest.is_zero() || request.credit.support_digest.is_zero() {
        return Err(OutcomeCreditClosureErrorV1::Binding("empty support"));
    }
    if request.outcome.episode_id != request.credit.episode_id {
        return Err(OutcomeCreditClosureErrorV1::Binding("episode mismatch"));
    }
    if request.outcome.outcome_id != request.credit.outcome_id {
        return Err(OutcomeCreditClosureErrorV1::Binding("outcome mismatch"));
    }
    if request.outcome.record_id == request.credit.record_id {
        return Err(OutcomeCreditClosureErrorV1::Binding("record identity reuse"));
    }

    let outcome = ledger
        .append(
            request.expected_decision_head,
            LedgerEvent::Outcome(request.outcome),
        )
        .map_err(OutcomeCreditClosureErrorV1::Ledger)?;
    let credit = ledger
        .append(
            outcome.chain_digest,
            LedgerEvent::Credit(request.credit),
        )
        .map_err(OutcomeCreditClosureErrorV1::Ledger)?;

    let mut bytes = b"hepta.intelligence.outcome-credit-closure.v1\0".to_vec();
    for digest in [
        request.expected_decision_head,
        outcome.event_digest,
        outcome.chain_digest,
        credit.event_digest,
        credit.chain_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(OutcomeCreditClosureReceiptV1 {
        outcome,
        credit,
        closure_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "learning_closure_tests.rs"]
mod tests;
