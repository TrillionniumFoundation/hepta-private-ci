//! Frozen generation contracts and post-execution learning handoff.
//!
//! The contract declares immutable identities; it does not prove that a worker
//! used a sampler, authenticate a quality judgment, or grant execution authority.
//! Owner observations come only from the existing Cell journal. The existing
//! LedgerWriter authenticates and owns every Decision and Outcome mutation.

use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ObservedOutcomeRequestV2;
use crate::OutcomeCreditClosureErrorV2;
use crate::append_observed_outcome_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenGenerationEpisodeInputV1 {
    pub episode_id: StableId,
    /// The Cell scope's run identifier, distinct from the ledger record ID.
    pub run_id: StableId,
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub policy_digest: Digest32,
    /// The independent observer's frozen evaluation and unit profile.
    pub evaluation_profile_digest: Digest32,
    /// Configuration identity only; a backend-specific caller verifies its use.
    pub sampler_digest: Digest32,
    pub source_frontier: Digest32,
    /// Includes the model/encoder manifest, scope, generation and writer epoch.
    pub initial: CellRuntimeSnapshotV2,
}

/// A validated, immutable declaration made before opening the episode owner.
/// The derived task digest goes into CellGenerationConfigV2; it is deliberately
/// absent from this input so the binding is not self-referential.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenGenerationEpisodeV1 {
    input: FrozenGenerationEpisodeInputV1,
    initial_digest: [u8; 32],
    contract_digest: Digest32,
}

/// Sealed support for an independently signed observation. Incomplete metering
/// remains explicit and cannot be promoted to a complete net-benefit claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationEpisodeEvidenceV1 {
    support_digest: Digest32,
    complete_metrics: Option<CellCostMetricsV2>,
}

impl GenerationEpisodeEvidenceV1 {
    pub fn support_digest(&self) -> Digest32 {
        self.support_digest
    }

    /// Completeness is relative to the recorded meters and stages, not proof
    /// that every physical resource was measured or that quality improved.
    pub fn complete_metrics(&self) -> Option<CellCostMetricsV2> {
        self.complete_metrics
    }
}

#[derive(Debug)]
pub enum GenerationEpisodeErrorV1 {
    Binding(&'static str),
    Generation(CellGenerationErrorV2),
    Ledger(ProductionLedgerError),
    Outcome(OutcomeCreditClosureErrorV2),
}

impl fmt::Display for GenerationEpisodeErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for GenerationEpisodeErrorV1 {}

impl FrozenGenerationEpisodeV1 {
    pub fn new(input: FrozenGenerationEpisodeInputV1) -> Result<Self, GenerationEpisodeErrorV1> {
        let initial_digest = input
            .initial
            .digest()
            .map_err(GenerationEpisodeErrorV1::Generation)?;
        if input.initial.scope.run_id != input.run_id.as_str()
            || input.initial.revision != 0
            || !input.initial.prefix.is_empty()
            || input.initial.stopped
        {
            return Err(GenerationEpisodeErrorV1::Binding(
                "initial generation scope",
            ));
        }
        let identities = [
            input.objective_digest,
            input.policy_digest,
            input.evaluation_profile_digest,
            input.sampler_digest,
            input.source_frontier,
        ];
        if identities.iter().any(|value| value.is_zero()) {
            return Err(GenerationEpisodeErrorV1::Binding("missing frozen identity"));
        }
        let mut bytes = b"hepta.intelligence.generation-episode.v1\0".to_vec();
        for id in [&input.episode_id, &input.run_id, &input.decision_id] {
            let value = id.as_str().as_bytes();
            let length = u32::try_from(value.len())
                .map_err(|_| GenerationEpisodeErrorV1::Binding("identifier length"))?;
            bytes.extend_from_slice(&length.to_be_bytes());
            bytes.extend_from_slice(value);
        }
        for value in identities {
            bytes.extend_from_slice(value.as_array());
        }
        bytes.extend_from_slice(&initial_digest);
        Ok(Self {
            input,
            initial_digest,
            contract_digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn input(&self) -> &FrozenGenerationEpisodeInputV1 {
        &self.input
    }

    /// Use as the authenticated Decision's run_snapshot_digest.
    pub fn contract_digest(&self) -> Digest32 {
        self.contract_digest
    }

    pub fn task_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.intelligence.generation-task.v1\0",
            self.contract_digest.as_array(),
        ])
    }

    /// Use as the authenticated Decision's support_digest. The Decision still
    /// requires its actual generator signature and candidate-completeness proof.
    pub fn decision_support_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.intelligence.generation-decision-support.v1\0",
            self.contract_digest.as_array(),
            self.task_digest().as_array(),
        ])
    }

    pub fn validate_observation(
        &self,
        observation: &CellGenerationObservationV1,
    ) -> Result<(), GenerationEpisodeErrorV1> {
        let initial = &self.input.initial;
        let current = observation.snapshot();
        if observation.task_digest() != self.task_digest().into_array()
            || observation.source_frontier() != self.input.source_frontier.into_array()
            || observation.manifest_digest() != initial.manifest_digest
            || observation.initial_snapshot_digest() != self.initial_digest
            || current.scope != initial.scope
            || current.manifest_digest != initial.manifest_digest
            || current.generation != initial.generation
            || current.writer_epoch != initial.writer_epoch
        {
            return Err(GenerationEpisodeErrorV1::Binding(
                "generation owner contract",
            ));
        }
        Ok(())
    }

    pub fn outcome_evidence(
        &self,
        observation: &CellGenerationObservationV1,
    ) -> Result<GenerationEpisodeEvidenceV1, GenerationEpisodeErrorV1> {
        self.validate_observation(observation)?;
        if !observation.is_terminal() {
            return Err(GenerationEpisodeErrorV1::Binding(
                "generation not settled and delivered",
            ));
        }
        let observed = observation
            .digest()
            .map_err(GenerationEpisodeErrorV1::Generation)?;
        Ok(GenerationEpisodeEvidenceV1 {
            support_digest: Digest32::of_parts(&[
                b"hepta.intelligence.generation-outcome-support.v1\0",
                self.contract_digest.as_array(),
                &observed,
            ]),
            complete_metrics: observation.complete_metrics(),
        })
    }
}

/// Bind an externally observed, independently signed outcome to this exact
/// settled and delivered generation. Pending/censored quality observations are
/// still facts; the existing ledger enforces their terminality and correction
/// rules. No quality value, reward, credit, model update or signature is created.
pub fn append_generation_outcome_v1(
    ledger: &mut LedgerWriter,
    frozen: &FrozenGenerationEpisodeV1,
    observation: &CellGenerationObservationV1,
    request: ObservedOutcomeRequestV2,
    now: u64,
) -> Result<AppendReceipt, GenerationEpisodeErrorV1> {
    let support = frozen.outcome_evidence(observation)?;
    let input = frozen.input();
    if request.run_id != input.decision_id
        || request.outcome.episode_id != input.episode_id
        || request.outcome.support_digest != support.support_digest()
        || request.outcome.unit_profile_digest != input.evaluation_profile_digest
    {
        return Err(GenerationEpisodeErrorV1::Binding(
            "generation outcome identity",
        ));
    }
    ledger
        .verify_active_decision_binding(&input.decision_id, &input.episode_id)
        .map_err(GenerationEpisodeErrorV1::Ledger)?;
    let records = ledger.records().map_err(GenerationEpisodeErrorV1::Ledger)?;
    let bound = records.iter().any(|record| {
        matches!(
            &record.event,
            LedgerEvent::AuthenticatedDecisionV2(decision)
                if decision.record_id == input.decision_id
                    && decision.episode_id == input.episode_id
                    && decision.run_snapshot_digest == frozen.contract_digest()
                    && decision.objective_digest == input.objective_digest
                    && decision.policy_digest == input.policy_digest
                    && decision.support_digest == frozen.decision_support_digest()
        )
    });
    if !bound {
        return Err(GenerationEpisodeErrorV1::Binding(
            "generation decision contract",
        ));
    }
    append_observed_outcome_v2(ledger, request, now).map_err(GenerationEpisodeErrorV1::Outcome)
}

#[cfg(test)]
#[path = "generation_episode_tests.rs"]
mod tests;
