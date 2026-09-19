//! Durable post-execution Outcome/Credit closure for a V3 intelligence run.
//!
//! The learning ledger remains the fact owner. This adapter only binds an
//! already-observed terminal outcome and its credit assignment to one episode,
//! then delegates both appends to the sealed DurableLearningJournal. Outcome and
//! Credit are separate durable facts: if the second append fails, the error
//! carries the committed Outcome receipt so callers reconcile rather than retry
//! or report a false atomic success.

use std::error::Error as StdError;
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
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureRequestV1 {
    pub run_id: StableId,
    pub episode_id: StableId,
    pub expected_ledger_head: Digest32,
    pub outcome: OutcomeObservation,
    pub credit: CreditAssignment,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureReceiptV1 {
    pub run_id: StableId,
    pub episode_id: StableId,
    pub outcome: AppendReceipt,
    pub credit: AppendReceipt,
    pub closure_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug, Eq, PartialEq)]
pub enum OutcomeCreditClosureErrorV1 {
    Binding(&'static str),
    Outcome(DurableLedgerError),
    Credit {
        outcome: AppendReceipt,
        error: DurableLedgerError,
    },
}

impl fmt::Display for OutcomeCreditClosureErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OutcomeCreditClosureErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Binding(_) => None,
            Self::Outcome(error) => Some(error),
            Self::Credit { error, .. } => Some(error),
        }
    }
}

pub fn append_outcome_credit_v1(
    request: OutcomeCreditClosureRequestV1,
    ledger: &mut dyn DurableLearningJournal,
) -> Result<OutcomeCreditClosureReceiptV1, OutcomeCreditClosureErrorV1> {
    validate_request(&request)?;
    let OutcomeCreditClosureRequestV1 {
        run_id,
        episode_id,
        expected_ledger_head,
        outcome,
        credit,
    } = request;

    let outcome_receipt = ledger
        .append(expected_ledger_head, LedgerEvent::Outcome(outcome))
        .map_err(OutcomeCreditClosureErrorV1::Outcome)?;
    let credit_receipt = ledger
        .append(outcome_receipt.chain_digest, LedgerEvent::Credit(credit))
        .map_err(|error| OutcomeCreditClosureErrorV1::Credit {
            outcome: outcome_receipt.clone(),
            error,
        })?;

    let mut bytes = b"hepta.intelligence.outcome-credit-closure.v1\0".to_vec();
    push_id(&mut bytes, &run_id)?;
    push_id(&mut bytes, &episode_id)?;
    bytes.extend_from_slice(outcome_receipt.event_digest.as_array());
    bytes.extend_from_slice(outcome_receipt.chain_digest.as_array());
    bytes.extend_from_slice(credit_receipt.event_digest.as_array());
    bytes.extend_from_slice(credit_receipt.chain_digest.as_array());

    Ok(OutcomeCreditClosureReceiptV1 {
        run_id,
        episode_id,
        outcome: outcome_receipt,
        credit: credit_receipt,
        closure_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_request(
    request: &OutcomeCreditClosureRequestV1,
) -> Result<(), OutcomeCreditClosureErrorV1> {
    if request.expected_ledger_head.is_zero() {
        return Err(OutcomeCreditClosureErrorV1::Binding(
            "missing decision predecessor",
        ));
    }
    if request.outcome.episode_id != request.episode_id
        || request.credit.episode_id != request.episode_id
    {
        return Err(OutcomeCreditClosureErrorV1::Binding("episode"));
    }
    if request.credit.outcome_id != request.outcome.outcome_id {
        return Err(OutcomeCreditClosureErrorV1::Binding("outcome"));
    }
    if request.outcome.finality != OutcomeFinality::Terminal {
        return Err(OutcomeCreditClosureErrorV1::Binding("non-terminal outcome"));
    }
    if request.outcome.support_digest.is_zero() || request.credit.support_digest.is_zero() {
        return Err(OutcomeCreditClosureErrorV1::Binding("support"));
    }
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), OutcomeCreditClosureErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| OutcomeCreditClosureErrorV1::Binding("identifier length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AppendDisposition;
    use codex_hepta_learning_ledger::CandidateSetCompleteness;
    use codex_hepta_learning_ledger::DurableLedger;
    use codex_hepta_learning_ledger::EpisodeDecision;
    use codex_hepta_learning_ledger::LedgerAnchor;
    use codex_hepta_learning_ledger::LedgerRecovery;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;
    use std::fs::OpenOptions;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn request(head: Digest32) -> OutcomeCreditClosureRequestV1 {
        OutcomeCreditClosureRequestV1 {
            run_id: id("run:v3"),
            episode_id: id("episode:v3"),
            expected_ledger_head: head,
            outcome: OutcomeObservation {
                record_id: id("outcome-record:v3"),
                outcome_id: id("outcome:v3"),
                episode_id: id("episode:v3"),
                observer_id: id("independent-observer"),
                value: FixedQ32::ONE,
                finality: OutcomeFinality::Terminal,
                support_digest: digest("observed-terminal-outcome"),
            },
            credit: CreditAssignment {
                record_id: id("credit-record:v3"),
                credit_id: id("credit:v3"),
                episode_id: id("episode:v3"),
                outcome_id: id("outcome:v3"),
                target_artifact_id: id("policy:v3"),
                allocator_id: id("independent-credit-evaluator"),
                credit: FixedQ32::ONE,
                support_digest: digest("credit-support"),
            },
        }
    }

    fn decision() -> LedgerEvent {
        LedgerEvent::Decision(EpisodeDecision {
            record_id: id("run:v3"),
            episode_id: id("episode:v3"),
            objective_digest: digest("objective"),
            policy_id: id("policy-controller"),
            candidate_ids: vec![id("abstain"), id("policy:v3")],
            selected_candidate_id: id("policy:v3"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("decision-support"),
        })
    }

    #[test]
    fn durable_outcome_and_credit_close_and_replay_after_reopen() {
        let temp = tempfile::tempdir().expect("tempdir");
        let path = temp.path().join("ledger");
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("file");
        let binding = digest("ledger-binding");
        let mut ledger = DurableLedger::create(file, binding, 3).expect("ledger");
        let decision = ledger.append(Digest32::ZERO, decision()).expect("decision");
        let request = request(decision.chain_digest);
        let receipt =
            append_outcome_credit_v1(request.clone(), &mut ledger).expect("closure");
        assert_eq!(receipt.outcome.disposition, AppendDisposition::Appended);
        assert_eq!(receipt.credit.disposition, AppendDisposition::Appended);
        assert!(!receipt.closure_digest.is_zero());
        assert!(!receipt.authority.grants_any());
        drop(ledger);

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        let mut reopened = DurableLedger::recover(
            file,
            binding,
            3,
            LedgerRecovery::Acknowledged(LedgerAnchor {
                sequence: 3,
                chain_digest: receipt.credit.chain_digest,
            }),
        )
        .expect("recover");
        assert_eq!(reopened.records().expect("records").len(), 3);
        let replay = append_outcome_credit_v1(request, &mut reopened).expect("replay");
        assert_eq!(replay.outcome.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(replay.credit.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(replay.closure_digest, receipt.closure_digest);
    }

    #[test]
    fn invalid_credit_binding_is_rejected_before_outcome_append() {
        let temp = tempfile::tempdir().expect("tempdir");
        let path = temp.path().join("ledger");
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(path)
            .expect("file");
        let mut ledger = DurableLedger::create(file, digest("binding"), 3).expect("ledger");
        let decision = ledger.append(Digest32::ZERO, decision()).expect("decision");
        let mut request = request(decision.chain_digest);
        request.credit.outcome_id = id("different-outcome");
        assert_eq!(
            append_outcome_credit_v1(request, &mut ledger),
            Err(OutcomeCreditClosureErrorV1::Binding("outcome"))
        );
        assert_eq!(ledger.records().expect("records").len(), 1);
    }
}
