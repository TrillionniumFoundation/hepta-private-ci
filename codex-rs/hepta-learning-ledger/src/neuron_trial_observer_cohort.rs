//! Read-only independent Observer signature over a complete bounded Neuron
//! trial cohort. Each tick can account for at most one distinct Episode.
//!
//! This only validates already committed, frozen Ledger sources. It does not
//! record tick execution, issue Observer keys, grant source access, make an
//! NDU decision or prove production route/physical-weight selection.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DatasetFreezePlanV2;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningEvidenceRoleV1;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::LedgerWriter;
use crate::NeuronTrialLedgerSourceV1;
use crate::NeuronTrialSourceError;
use crate::SignedLearningEvidenceV1;

const MAX_BATCH: usize = 256;
const SIGN_DOMAIN: &[u8] = b"hepta.learning-ledger.neuron.observer-cohort.v1\0";
const RECEIPT_DOMAIN: &[u8] = b"hepta.learning-ledger.neuron.observer-cohort-receipt.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTrialCohortTickV1 {
    pub episode_id: StableId,
    /// Digest of a separately retained ACTUAL Agentd tick observation.
    pub tick_observation_digest: Digest32,
    pub tick_generation: Generation,
}

/// Immutable data-free diagnostic; rehashing it cannot authenticate its signer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTrialObservedCohortV1 {
    pub frozen_dataset_digest: Digest32,
    pub ledger_source_digest: Digest32,
    pub observer_principal_id: StableId,
    pub observer_controller_id: StableId,
    /// Exact verified independent Observer trust distribution at read time.
    pub observer_trust_digest: Digest32,
    pub observer_signature_digest: Digest32,
    pub observer_signed_at: u64,
    /// Canonical ascending Episode order.
    pub ticks: Vec<NeuronTrialCohortTickV1>,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronTrialObservedCohortV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = RECEIPT_DOMAIN.to_vec();
        bytes.extend_from_slice(self.frozen_dataset_digest.as_array());
        bytes.extend_from_slice(self.ledger_source_digest.as_array());
        push_id(&mut bytes, &self.observer_principal_id);
        push_id(&mut bytes, &self.observer_controller_id);
        bytes.extend_from_slice(self.observer_trust_digest.as_array());
        bytes.extend_from_slice(self.observer_signature_digest.as_array());
        bytes.extend_from_slice(&self.observer_signed_at.to_be_bytes());
        bytes.extend_from_slice(&(self.ticks.len() as u64).to_be_bytes());
        for row in &self.ticks {
            push_id(&mut bytes, &row.episode_id);
            bytes.extend_from_slice(row.tick_observation_digest.as_array());
            bytes.extend_from_slice(&row.tick_generation.get().to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }

    /// Only structural uniqueness and self-consistency, never final-use.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        if self.authority != AuthorityPosture::DENY_ALL
            || self.frozen_dataset_digest.is_zero()
            || self.ledger_source_digest.is_zero()
            || self.observer_trust_digest.is_zero()
            || self.observer_signature_digest.is_zero()
            || self.observer_signed_at == 0
            || self.ticks.is_empty()
            || self.ticks.len() > MAX_BATCH
            || self.diagnostic_digest != self.computed_digest()
        {
            return false;
        }
        let mut tick_ids = BTreeSet::new();
        let frozen_generation = self.ticks[0].tick_generation;
        for (index, row) in self.ticks.iter().enumerate() {
            if row.tick_generation != frozen_generation
                || row.tick_observation_digest.is_zero()
                || !tick_ids.insert(*row.tick_observation_digest.as_array())
                || (index > 0 && self.ticks[index - 1].episode_id >= row.episode_id)
            {
                return false;
            }
        }
        true
    }
}

/// Canonically sign every native terminal Episode exactly once. No extra,
/// missing or duplicate Episode or tick is allowed, including repeated ticks
/// assigned to distinct episodes. This is not an Observer verification step.
pub fn neuron_trial_observer_cohort_payload_v1(
    source: &NeuronTrialLedgerSourceV1,
    objective_digest: Digest32,
    ticks: &[NeuronTrialCohortTickV1],
) -> Result<Vec<u8>, NeuronTrialSourceError> {
    if !source.validate_integrity()
        || source.pending_episodes != 0
        || source.censored_episodes != 0
        || source.terminal_joins.is_empty()
        || source.terminal_joins.len() > MAX_BATCH
        || source.terminal_joins.len() != ticks.len()
        || objective_digest.is_zero()
    {
        return Err(NeuronTrialSourceError::Invalid(
            "incomplete or oversized frozen Neuron cohort",
        ));
    }
    let mut mapped = BTreeMap::new();
    let mut unique_ticks = BTreeSet::new();
    let frozen_generation = ticks[0].tick_generation;
    for tick in ticks {
        if tick.tick_generation != frozen_generation
            || tick.tick_observation_digest.is_zero()
            || mapped.insert(tick.episode_id.clone(), tick).is_some()
            || !unique_ticks.insert(*tick.tick_observation_digest.as_array())
        {
            return Err(NeuronTrialSourceError::Invalid(
                "duplicate Episode or reused Neuron Tick",
            ));
        }
    }
    let mut pairs = source.terminal_joins.iter().collect::<Vec<_>>();
    pairs.sort_by(|left, right| left.episode_id.cmp(&right.episode_id));
    let mut bytes = SIGN_DOMAIN.to_vec();
    bytes.extend_from_slice(source.frozen_dataset_digest.as_array());
    bytes.extend_from_slice(source.diagnostic_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(&(pairs.len() as u64).to_be_bytes());
    for pair in pairs {
        let row = mapped
            .get(&pair.episode_id)
            .ok_or(NeuronTrialSourceError::Invalid("unmatched native Episode"))?;
        push_id(&mut bytes, &pair.episode_id);
        for digest in [
            pair.decision_event_digest,
            pair.outcome_event_digest,
            pair.run_snapshot_digest,
            pair.policy_digest,
            pair.decision_support_digest,
            pair.outcome_support_digest,
            row.tick_observation_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &pair.selected_candidate_id);
        bytes.extend_from_slice(&row.tick_generation.get().to_be_bytes());
    }
    Ok(bytes)
}

impl LedgerWriter {
    /// One independent signature over a complete eligible Ledger cohort. The
    /// current durable Ledger owner verifies signer role and chronology. The
    /// actual Tick producer and CNS/Artifact/Final-use owners are independent
    /// prerequisites, not authenticated by this method.
    #[allow(clippy::too_many_arguments)]
    pub fn read_observer_linked_neuron_cohort_v1(
        &self,
        frozen_ledger: &LedgerSnapshot,
        plan: &DatasetFreezePlanV2,
        signed_freeze: &SignedLearningEvidenceV1,
        dataset: &DatasetSnapshotReceiptV3,
        ticks: &[NeuronTrialCohortTickV1],
        observer_signed_batch: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<NeuronTrialObservedCohortV1, NeuronTrialSourceError> {
        let source =
            self.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?;
        let payload =
            neuron_trial_observer_cohort_payload_v1(&source, plan.objective_digest, ticks)?;
        let verified = self.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            observer_signed_batch,
            &payload,
            now,
        )?;

        // Resolve the exact frozen records (not a JSON description) and
        // ensure the independent Observer cannot sign before ANY terminal
        // outcome was finalized or reuse the Generator authority of ANY row.
        let mut decisions = BTreeMap::new();
        let mut outcomes = BTreeMap::new();
        for record in frozen_ledger.records() {
            match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value) => {
                    if source.terminal_joins.iter().any(|join| {
                        join.episode_id == value.episode_id
                            && join.decision_event_digest == record.event_digest
                    }) && decisions.insert(value.episode_id.clone(), value).is_some()
                    {
                        return Err(NeuronTrialSourceError::Invalid(
                            "ambiguous frozen Neuron Decision",
                        ));
                    }
                }
                LedgerEvent::AuthenticatedOutcomeV2(value) => {
                    if source.terminal_joins.iter().any(|join| {
                        join.episode_id == value.episode_id
                            && join.outcome_event_digest == record.event_digest
                    }) && outcomes.insert(value.episode_id.clone(), value).is_some()
                    {
                        return Err(NeuronTrialSourceError::Invalid(
                            "ambiguous frozen Neuron Outcome",
                        ));
                    }
                }
                _ => {}
            }
        }
        for pair in &source.terminal_joins {
            let decision = decisions
                .get(&pair.episode_id)
                .ok_or(NeuronTrialSourceError::Invalid("missing frozen Decision"))?;
            let outcome = outcomes
                .get(&pair.episode_id)
                .ok_or(NeuronTrialSourceError::Invalid("missing frozen Outcome"))?;
            let finalized_at = outcome.finalized_at.ok_or(NeuronTrialSourceError::Invalid(
                "missing terminal finalization",
            ))?;
            if observer_signed_batch.issued_at < finalized_at
                || verified.principal().principal_id == decision.generator_id
                || verified.controller_id() == &decision.generator_controller_id
                || verified.principal().credential_chain_digest
                    == decision.generator_credential_chain_digest
                || verified.principal().signing_key_digest == decision.generator_signing_key_digest
            {
                return Err(NeuronTrialSourceError::Invalid(
                    "Observer signed before finalization or shares Generator authority",
                ));
            }
        }
        if self.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?
            != source
        {
            return Err(NeuronTrialSourceError::Invalid(
                "native cohort changed during Observer signature validation",
            ));
        }
        let mut signed_bytes = observer_signed_batch.signing_bytes();
        signed_bytes.extend_from_slice(&observer_signed_batch.signature);
        let mut ordered = ticks.to_vec();
        ordered.sort_by(|left, right| left.episode_id.cmp(&right.episode_id));
        let mut receipt = NeuronTrialObservedCohortV1 {
            frozen_dataset_digest: source.frozen_dataset_digest,
            ledger_source_digest: source.diagnostic_digest,
            observer_principal_id: verified.principal().principal_id.clone(),
            observer_controller_id: verified.controller_id().clone(),
            observer_trust_digest: verified.trust_digest(),
            observer_signature_digest: Digest32::of_bytes(&signed_bytes),
            observer_signed_at: observer_signed_batch.issued_at,
            ticks: ordered,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.diagnostic_digest = receipt.computed_digest();
        if !receipt.validate_integrity() {
            return Err(NeuronTrialSourceError::Invalid(
                "invalid signed Neuron cohort diagnostic",
            ));
        }
        Ok(receipt)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
