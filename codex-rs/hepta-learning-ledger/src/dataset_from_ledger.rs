//! Strict dataset-freeze profile derived from an authoritative ledger snapshot.
//!
//! Unlike `DatasetFreezeRequestV1`, this API does not accept a caller-supplied
//! ledger head, source-record set, revocation cut or pending/censored counts.
//! Those facts are recomputed from a snapshot that is replayed through the same
//! causal invariants before the dataset receipt is created.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AuthenticatedPrincipalV1;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::LearningLedger;
use crate::OutcomeFinality;
use crate::freeze_dataset_receipt_v3;

const NO_CORRECTION_CUT_DOMAIN: &[u8] = b"hepta.learning-ledger.v1-correction-cut.none";
const REVOCATION_CUT_DOMAIN: &[u8] = b"hepta.learning-ledger.revocation-cut.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerDerivedDatasetPlanV1 {
    pub snapshot_id: StableId,
    pub producer: AuthenticatedPrincipalV1,
    pub objective_digest: Digest32,
    /// Externally authenticated observation-time watermark. V1 ledger records
    /// do not contain enough wall-clock evidence to derive this value locally.
    pub outcome_watermark: u64,
    pub inclusion_policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerDerivedDatasetError {
    Ledger(LedgerError),
    Receipt(DatasetReceiptError),
    EmptyLedger,
    EmptyObjective,
    InvalidOutcomeWatermark,
    EmptyInclusionPolicy,
    SequenceConversion,
}

impl fmt::Display for LedgerDerivedDatasetError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LedgerDerivedDatasetError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Ledger(error) => Some(error),
            Self::Receipt(error) => Some(error),
            Self::EmptyLedger
            | Self::EmptyObjective
            | Self::InvalidOutcomeWatermark
            | Self::EmptyInclusionPolicy
            | Self::SequenceConversion => None,
        }
    }
}

impl From<LedgerError> for LedgerDerivedDatasetError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

impl From<DatasetReceiptError> for LedgerDerivedDatasetError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Receipt(value)
    }
}

/// Freeze the current complete logical frontier for one objective.
///
/// The snapshot is replayed first. The exact ledger head and eligible frontier
/// come from the replayed state. Source membership contains every currently
/// active decision/outcome/credit fact for the objective plus revocation events
/// that explain exclusion of objective-related records. Pending outcome count is
/// derived from active intermediate V1 outcomes. V1 has no censored-outcome
/// representation, so this strict compatibility profile emits zero censored
/// outcomes rather than accepting a caller assertion.
pub fn freeze_dataset_from_ledger_v3(
    snapshot: &LedgerSnapshot,
    plan: LedgerDerivedDatasetPlanV1,
    now: u64,
) -> Result<DatasetSnapshotReceiptV3, LedgerDerivedDatasetError> {
    if plan.objective_digest.is_zero() {
        return Err(LedgerDerivedDatasetError::EmptyObjective);
    }
    if plan.outcome_watermark == 0 {
        return Err(LedgerDerivedDatasetError::InvalidOutcomeWatermark);
    }
    if plan.inclusion_policy_digest.is_zero() {
        return Err(LedgerDerivedDatasetError::EmptyInclusionPolicy);
    }

    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let head = ledger
        .records()
        .last()
        .ok_or(LedgerDerivedDatasetError::EmptyLedger)?;
    let eligible_frontier = head.sequence.get();
    let ledger_head_digest = head.chain_digest;

    let mut relevant_episodes = BTreeSet::new();
    let mut relevant_record_ids = BTreeSet::new();
    for record in ledger.records() {
        if let LedgerEvent::Decision(decision) = &record.event
            && decision.objective_digest == plan.objective_digest
        {
            relevant_episodes.insert(decision.episode_id.clone());
            relevant_record_ids.insert(decision.record_id.clone());
        }
    }
    for record in ledger.records() {
        match &record.event {
            LedgerEvent::Outcome(outcome) if relevant_episodes.contains(&outcome.episode_id) => {
                relevant_record_ids.insert(outcome.record_id.clone());
            }
            LedgerEvent::Credit(credit) if relevant_episodes.contains(&credit.episode_id) => {
                relevant_record_ids.insert(credit.record_id.clone());
            }
            _ => {}
        }
    }

    let active = ledger.active_records();
    let mut source_record_digests = Vec::new();
    let mut pending_outcomes = 0_u32;
    let mut revocation_event_digests = Vec::new();
    for record in active {
        match &record.event {
            LedgerEvent::Decision(decision)
                if decision.objective_digest == plan.objective_digest =>
            {
                source_record_digests.push(record.event_digest);
            }
            LedgerEvent::Outcome(outcome) if relevant_episodes.contains(&outcome.episode_id) => {
                source_record_digests.push(record.event_digest);
                if outcome.finality == OutcomeFinality::Intermediate {
                    pending_outcomes = pending_outcomes
                        .checked_add(1)
                        .ok_or(LedgerDerivedDatasetError::SequenceConversion)?;
                }
            }
            LedgerEvent::Credit(credit) if relevant_episodes.contains(&credit.episode_id) => {
                source_record_digests.push(record.event_digest);
            }
            LedgerEvent::Revocation(revocation)
                if relevant_record_ids.contains(&revocation.target_record_id) =>
            {
                source_record_digests.push(record.event_digest);
                revocation_event_digests.push(record.event_digest);
            }
            _ => {}
        }
    }

    revocation_event_digests.sort_unstable();
    let revocation_cut_digest = revocation_cut_digest(ledger_head_digest, &revocation_event_digests)?;
    let correction_cut_digest = Digest32::of_bytes(NO_CORRECTION_CUT_DOMAIN);

    freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: plan.snapshot_id,
            producer: plan.producer,
            ledger_head_digest,
            objective_digest: plan.objective_digest,
            eligible_frontier,
            outcome_watermark: plan.outcome_watermark,
            correction_cut_digest,
            revocation_cut_digest,
            inclusion_policy_digest: plan.inclusion_policy_digest,
            source_record_digests,
            pending_outcomes,
            censored_outcomes: 0,
        },
        now,
    )
    .map_err(Into::into)
}

fn revocation_cut_digest(
    ledger_head_digest: Digest32,
    revocations: &[Digest32],
) -> Result<Digest32, LedgerDerivedDatasetError> {
    let count = u64::try_from(revocations.len())
        .map_err(|_| LedgerDerivedDatasetError::SequenceConversion)?;
    let mut bytes = Vec::with_capacity(
        REVOCATION_CUT_DOMAIN.len() + 32 + 8 + revocations.len().saturating_mul(32),
    );
    bytes.extend_from_slice(REVOCATION_CUT_DOMAIN);
    bytes.extend_from_slice(ledger_head_digest.as_array());
    bytes.extend_from_slice(&count.to_be_bytes());
    for digest in revocations {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;

    use super::*;
    use crate::CandidateSetCompleteness;
    use crate::CreditAssignment;
    use crate::EpisodeDecision;
    use crate::OutcomeObservation;
    use crate::Revocation;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn producer() -> AuthenticatedPrincipalV1 {
        AuthenticatedPrincipalV1 {
            principal_id: id("dataset-producer"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            scope_digest: digest("scope"),
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 100,
        }
    }

    fn decision(record_id: &str, episode_id: &str, objective: Digest32) -> LedgerEvent {
        LedgerEvent::Decision(EpisodeDecision {
            record_id: id(record_id),
            episode_id: id(episode_id),
            objective_digest: objective,
            policy_id: id("policy"),
            candidate_ids: vec![id("abstain"), id("action")],
            selected_candidate_id: id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("decision-support"),
        })
    }

    #[test]
    fn dataset_membership_is_derived_from_active_objective_lineage() {
        let objective = digest("objective");
        let mut ledger = LearningLedger::new();
        ledger
            .append(decision("decision-record", "episode", objective))
            .expect("append decision");
        ledger
            .append(LedgerEvent::Outcome(OutcomeObservation {
                record_id: id("outcome-record"),
                outcome_id: id("outcome"),
                episode_id: id("episode"),
                observer_id: id("observer"),
                value: FixedQ32::ONE,
                finality: OutcomeFinality::Terminal,
                support_digest: digest("outcome-support"),
            }))
            .expect("append outcome");
        ledger
            .append(LedgerEvent::Credit(CreditAssignment {
                record_id: id("credit-record"),
                credit_id: id("credit"),
                episode_id: id("episode"),
                outcome_id: id("outcome"),
                target_artifact_id: id("artifact"),
                allocator_id: id("allocator"),
                credit: FixedQ32::ONE,
                support_digest: digest("credit-support"),
            }))
            .expect("append credit");
        ledger
            .append(LedgerEvent::Revocation(Revocation {
                record_id: id("revoke-record"),
                target_record_id: id("decision-record"),
                authority_id: id("authority"),
                reason_digest: digest("reason"),
            }))
            .expect("append revocation");

        let snapshot = ledger.snapshot();
        let head = snapshot.head_digest;
        let revocation_digest = snapshot
            .records()
            .last()
            .expect("revocation record")
            .event_digest;
        let receipt = freeze_dataset_from_ledger_v3(
            &snapshot,
            LedgerDerivedDatasetPlanV1 {
                snapshot_id: id("dataset"),
                producer: producer(),
                objective_digest: objective,
                outcome_watermark: 10,
                inclusion_policy_digest: digest("policy"),
            },
            20,
        )
        .expect("freeze derived dataset");

        assert_eq!(receipt.snapshot.ledger_head_digest, head);
        assert_eq!(receipt.snapshot.eligible_frontier, 4);
        assert_eq!(receipt.snapshot.source_record_digests, vec![revocation_digest]);
        assert_eq!(receipt.snapshot.pending_outcomes, 0);
        assert_eq!(receipt.snapshot.censored_outcomes, 0);
    }

    #[test]
    fn dataset_pending_count_is_derived_not_supplied() {
        let objective = digest("objective");
        let mut ledger = LearningLedger::new();
        ledger
            .append(decision("decision-record", "episode", objective))
            .expect("append decision");
        ledger
            .append(LedgerEvent::Outcome(OutcomeObservation {
                record_id: id("outcome-record"),
                outcome_id: id("outcome"),
                episode_id: id("episode"),
                observer_id: id("observer"),
                value: FixedQ32::ZERO,
                finality: OutcomeFinality::Intermediate,
                support_digest: digest("outcome-support"),
            }))
            .expect("append pending outcome");

        let receipt = freeze_dataset_from_ledger_v3(
            &ledger.snapshot(),
            LedgerDerivedDatasetPlanV1 {
                snapshot_id: id("dataset"),
                producer: producer(),
                objective_digest: objective,
                outcome_watermark: 10,
                inclusion_policy_digest: digest("policy"),
            },
            20,
        )
        .expect("freeze derived dataset");
        assert_eq!(receipt.snapshot.pending_outcomes, 1);
        assert_eq!(receipt.snapshot.source_record_digests.len(), 2);
    }
}
