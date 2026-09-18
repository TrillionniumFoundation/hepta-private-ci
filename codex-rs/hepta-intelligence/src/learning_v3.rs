//! Durable V3 learning closure.
//!
//! Decision, Outcome and Credit remain learning.ledger facts. Intelligence.control
//! only offers bounded helpers that preserve caller-supplied observations and
//! credit assignments; it never synthesizes an Outcome from dispatch success.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionAppendRequestV3 {
    pub expected_ledger_head: Digest32,
    pub decision: EpisodeDecision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureRequestV3 {
    /// Original predecessor before Outcome. Exact retries keep this value.
    pub expected_ledger_head: Digest32,
    pub outcome: OutcomeObservation,
    pub credit: CreditAssignment,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureReceiptV3 {
    pub outcome: AppendReceipt,
    pub credit: AppendReceipt,
    pub closure_digest: Digest32,
}

#[derive(Debug)]
pub enum LearningClosureErrorV3 {
    Binding(&'static str),
    Ledger(DurableLedgerError),
}

impl fmt::Display for LearningClosureErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LearningClosureErrorV3 {}

pub fn append_decision_v3(
    ledger: &mut dyn DurableLearningJournal,
    request: DecisionAppendRequestV3,
) -> Result<AppendReceipt, LearningClosureErrorV3> {
    if request.decision.objective_digest.is_zero()
        || request.decision.support_digest.is_zero()
        || request.decision.selected_propensity.raw() == 0
        || request.decision.completeness != CandidateSetCompleteness::Complete
    {
        return Err(LearningClosureErrorV3::Binding("decision"));
    }
    ledger
        .append(
            request.expected_ledger_head,
            LedgerEvent::Decision(request.decision),
        )
        .map_err(LearningClosureErrorV3::Ledger)
}

pub fn append_outcome_and_credit_v3(
    ledger: &mut dyn DurableLearningJournal,
    request: OutcomeCreditClosureRequestV3,
) -> Result<OutcomeCreditClosureReceiptV3, LearningClosureErrorV3> {
    if request.outcome.finality != OutcomeFinality::Terminal {
        return Err(LearningClosureErrorV3::Binding("non-terminal outcome"));
    }
    if request.outcome.support_digest.is_zero() || request.credit.support_digest.is_zero() {
        return Err(LearningClosureErrorV3::Binding("support"));
    }
    if request.outcome.episode_id != request.credit.episode_id
        || request.outcome.outcome_id != request.credit.outcome_id
    {
        return Err(LearningClosureErrorV3::Binding("outcome-credit linkage"));
    }

    let outcome = ledger
        .append(
            request.expected_ledger_head,
            LedgerEvent::Outcome(request.outcome.clone()),
        )
        .map_err(LearningClosureErrorV3::Ledger)?;
    let credit = ledger
        .append(
            outcome.chain_digest,
            LedgerEvent::Credit(request.credit.clone()),
        )
        .map_err(LearningClosureErrorV3::Ledger)?;

    let mut bytes = b"hepta.intelligence.outcome-credit-closure.v3\0".to_vec();
    bytes.extend_from_slice(outcome.event_digest.as_array());
    bytes.extend_from_slice(outcome.chain_digest.as_array());
    bytes.extend_from_slice(credit.event_digest.as_array());
    bytes.extend_from_slice(credit.chain_digest.as_array());
    bytes.extend_from_slice(request.outcome.support_digest.as_array());
    bytes.extend_from_slice(request.credit.support_digest.as_array());

    Ok(OutcomeCreditClosureReceiptV3 {
        outcome,
        credit,
        closure_digest: Digest32::of_bytes(&bytes),
    })
}

#[cfg(test)]
#[path = "learning_v3_tests.rs"]
mod tests;
