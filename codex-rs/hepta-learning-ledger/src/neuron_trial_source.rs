//! Read-only, current-ledger-backed source joins for external Neuron trials.
//!
//! Unlike a signed JSON claim, this API consumes the actual production
//! `LedgerWriter`, the original frozen ledger prefix, and its independently
//! signed Evaluator freeze request. It derives Decision/terminal Outcome event
//! identities from the currently active source set, not caller-provided rows.
//!
//! No raw observation, answer label, reward, selected Cell artifact, runtime
//! routing authority, or NDU evaluation is exported here. A separate approved
//! observation owner and independent evaluator must perform those joins.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::DatasetFreezePlanV2;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningEvidenceRoleV1;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::LedgerWriter;
use crate::ProductionLedgerError;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::dataset_freeze_signing_payload_v2;
use crate::freeze_dataset_from_ledger;
use crate::verify_dataset_snapshot_receipt_against_ledger_v3;

const MAX_SOURCE_ROWS: usize = 4_096;
const DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.neuron-trial-source.diagnostic.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTrialTerminalJoinV1 {
    pub episode_id: StableId,
    pub decision_record_id: StableId,
    pub decision_event_digest: Digest32,
    pub outcome_record_id: StableId,
    pub outcome_event_digest: Digest32,
    pub run_snapshot_digest: Digest32,
    pub policy_digest: Digest32,
    pub selected_candidate_id: StableId,
    pub decision_support_digest: Digest32,
    pub outcome_support_digest: Digest32,
    pub outcome_unit_profile_digest: Digest32,
}

/// An owner-local diagnostic, *not* an authenticated export or an efficacy claim.
/// Raw terminal values remain under the independently authorized Evaluator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTrialLedgerSourceV1 {
    pub frozen_dataset_digest: Digest32,
    pub frozen_ledger_head_digest: Digest32,
    pub current_ledger_head_digest: Digest32,
    pub current_witness_digest: Digest32,
    pub trust_distribution_digest: Digest32,
    pub terminal_joins: Vec<NeuronTrialTerminalJoinV1>,
    pub pending_episodes: u32,
    pub censored_episodes: u32,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronTrialLedgerSourceV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut b = DIGEST_DOMAIN.to_vec();
        for digest in [
            self.frozen_dataset_digest,
            self.frozen_ledger_head_digest,
            self.current_ledger_head_digest,
            self.current_witness_digest,
            self.trust_distribution_digest,
        ] {
            b.extend_from_slice(digest.as_array());
        }
        b.extend_from_slice(&(self.terminal_joins.len() as u64).to_be_bytes());
        b.extend_from_slice(&self.pending_episodes.to_be_bytes());
        b.extend_from_slice(&self.censored_episodes.to_be_bytes());
        for pair in &self.terminal_joins {
            for id in [
                &pair.episode_id,
                &pair.decision_record_id,
                &pair.outcome_record_id,
                &pair.selected_candidate_id,
            ] {
                let raw = id.as_str().as_bytes();
                b.extend_from_slice(&(raw.len() as u64).to_be_bytes());
                b.extend_from_slice(raw);
            }
            for digest in [
                pair.decision_event_digest,
                pair.outcome_event_digest,
                pair.run_snapshot_digest,
                pair.policy_digest,
                pair.decision_support_digest,
                pair.outcome_support_digest,
                pair.outcome_unit_profile_digest,
            ] {
                b.extend_from_slice(digest.as_array());
            }
        }
        Digest32::of_bytes(&b)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Debug)]
pub enum NeuronTrialSourceError {
    Ledger(ProductionLedgerError),
    Dataset(DatasetReceiptError),
    Evidence(SignedEvidenceError),
    Invalid(&'static str),
}

impl fmt::Display for NeuronTrialSourceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for NeuronTrialSourceError {}

impl From<ProductionLedgerError> for NeuronTrialSourceError {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}
impl From<DatasetReceiptError> for NeuronTrialSourceError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<SignedEvidenceError> for NeuronTrialSourceError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl LedgerWriter {
    /// Read one bounded terminal source frontier from the *live* ledger owner.
    ///
    /// The frozen prefix must be the prefix of this owner's current durable
    /// chain, and the original Evaluator freeze signature must still verify
    /// against the owner's pinned trust distribution. Corrections/revocations
    /// invalidate the frozen source, and a witness-lagged ledger fails closed.
    /// Pending/censored outcomes are counted, never treated as zero rewards.
    /// No source observations or outcome values are delivered to the runner.
    pub fn read_neuron_trial_source_v1(
        &self,
        frozen_ledger: &LedgerSnapshot,
        plan: &DatasetFreezePlanV2,
        signed_freeze: &SignedLearningEvidenceV1,
        dataset: &DatasetSnapshotReceiptV3,
        now: u64,
    ) -> Result<NeuronTrialLedgerSourceV1, NeuronTrialSourceError> {
        if dataset.snapshot.source_record_digests.len() > MAX_SOURCE_ROWS {
            return Err(NeuronTrialSourceError::Invalid(
                "source materialization limit",
            ));
        }
        let current = self.snapshot()?;
        let frozen_len = frozen_ledger.records().len();
        let Some(frozen_last) = frozen_ledger.records().last() else {
            return Err(NeuronTrialSourceError::Invalid("empty frozen ledger"));
        };
        let Some(prefix_last) = current.records().get(frozen_len - 1) else {
            return Err(NeuronTrialSourceError::Invalid("frozen prefix missing"));
        };
        if frozen_ledger.head_digest != frozen_last.chain_digest
            || frozen_last.chain_digest != prefix_last.chain_digest
            || frozen_last.sequence != prefix_last.sequence
        {
            return Err(NeuronTrialSourceError::Invalid(
                "frozen ledger is not live prefix",
            ));
        }
        let Some(current_last) = current.records().last() else {
            return Err(NeuronTrialSourceError::Invalid("empty live ledger"));
        };
        let witness = self.witness_frontier()?;
        if current.head_digest != current_last.chain_digest
            || witness.anchor.sequence != current_last.sequence.get()
            || witness.anchor.chain_digest != current.head_digest
        {
            return Err(NeuronTrialSourceError::Invalid(
                "unacknowledged ledger frontier",
            ));
        }

        // Verify exactly the native bytes signed at freeze, not a signature
        // fabricated over the caller's JSON dataset description.
        let freeze_payload = dataset_freeze_signing_payload_v2(frozen_ledger, plan)?;
        let verified = self.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            signed_freeze,
            &freeze_payload,
            now,
        )?;
        let expected = freeze_dataset_from_ledger(
            frozen_ledger,
            plan.clone(),
            verified.principal().clone(),
            now,
        )?;
        if &expected != dataset {
            return Err(NeuronTrialSourceError::Invalid(
                "freeze receipt/evaluator mismatch",
            ));
        }
        verify_dataset_snapshot_receipt_against_ledger_v3(dataset, frozen_ledger, now)?;
        let records = self.read_dataset_records(dataset, now)?;
        let (joins, pending, censored) = pair_current_events(&records, dataset)?;
        let mut result = NeuronTrialLedgerSourceV1 {
            frozen_dataset_digest: dataset.snapshot.dataset_digest,
            frozen_ledger_head_digest: frozen_ledger.head_digest,
            current_ledger_head_digest: current.head_digest,
            current_witness_digest: witness.anchor.chain_digest,
            trust_distribution_digest: self.trust_distribution_digest(),
            terminal_joins: joins,
            pending_episodes: pending,
            censored_episodes: censored,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.diagnostic_digest = result.computed_digest();
        Ok(result)
    }
}

fn pair_current_events(
    records: &[&LedgerRecord],
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<(Vec<NeuronTrialTerminalJoinV1>, u32, u32), NeuronTrialSourceError> {
    let mut decisions =
        BTreeMap::<StableId, (&LedgerRecord, &AuthenticatedDecisionRecordV2)>::new();
    let mut outcomes = BTreeMap::<StableId, (&LedgerRecord, &AuthenticatedOutcomeRecordV2)>::new();
    for record in records {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                if value.objective_digest != dataset.snapshot.objective_digest
                    || value.authentication_digest.is_zero()
                    || value.run_snapshot_digest.is_zero()
                    || value.policy_digest.is_zero()
                    || value.support_digest.is_zero()
                    || !value.candidate_ids.contains(&value.selected_candidate_id)
                    || decisions
                        .insert(value.episode_id.clone(), (*record, value))
                        .is_some()
                {
                    return Err(NeuronTrialSourceError::Invalid("invalid active decision"));
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if value.authentication_digest.is_zero()
                    || value.support_digest.is_zero()
                    || value.unit_profile_digest.is_zero()
                    || outcomes
                        .insert(value.episode_id.clone(), (*record, value))
                        .is_some()
                {
                    return Err(NeuronTrialSourceError::Invalid("ambiguous active outcome"));
                }
            }
            _ => {}
        }
    }
    let mut joins = Vec::new();
    let mut pending = 0_u32;
    let mut censored = 0_u32;
    for (episode, (decision_record, decision)) in decisions {
        match outcomes.remove(&episode) {
            None => pending += 1,
            Some((_, outcome))
                if outcome.terminality == AuthenticatedOutcomeTerminality::Pending =>
            {
                pending += 1;
            }
            Some((_, outcome))
                if outcome.terminality == AuthenticatedOutcomeTerminality::Censored =>
            {
                censored += 1;
            }
            Some((outcome_record, outcome)) => {
                if outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
                    || outcome.value.is_none()
                    || outcome.observed_at.is_none()
                    || outcome.finalized_at.is_none()
                    || outcome.observed_at > outcome.finalized_at
                    || outcome.observer_id == decision.generator_id
                    || outcome.observer_controller_id == decision.generator_controller_id
                    || outcome.observer_credential_chain_digest
                        == decision.generator_credential_chain_digest
                    || outcome.observer_signing_key_digest == decision.generator_signing_key_digest
                {
                    return Err(NeuronTrialSourceError::Invalid(
                        "unqualified terminal outcome",
                    ));
                }
                joins.push(NeuronTrialTerminalJoinV1 {
                    episode_id: episode,
                    decision_record_id: decision.record_id.clone(),
                    decision_event_digest: decision_record.event_digest,
                    outcome_record_id: outcome.record_id.clone(),
                    outcome_event_digest: outcome_record.event_digest,
                    run_snapshot_digest: decision.run_snapshot_digest,
                    policy_digest: decision.policy_digest,
                    selected_candidate_id: decision.selected_candidate_id.clone(),
                    decision_support_digest: decision.support_digest,
                    outcome_support_digest: outcome.support_digest,
                    outcome_unit_profile_digest: outcome.unit_profile_digest,
                });
            }
        }
    }
    if !outcomes.is_empty() {
        return Err(NeuronTrialSourceError::Invalid("orphan active outcome"));
    }
    Ok((joins, pending, censored))
}

#[cfg(test)]
#[path = "neuron_trial_source_tests.rs"]
mod tests;
