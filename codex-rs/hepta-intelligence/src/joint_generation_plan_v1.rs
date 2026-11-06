//! Request-scoped Joint composition: NDU recommends explicit worker actions.
//! This value owns no state, budget, model process, output or learning writer.
//! Callers retain the returned planning charge through the existing Cell owner
//! before dispatch. Observed costs and predicted utilities remain distinct.

use std::collections::BTreeSet;
use std::time::Instant;

use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduError;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::canonical_evaluation_policy_digest;
use codex_hepta_ndu::canonical_scalarization_digest;
use codex_hepta_ndu::canonical_utility_profile_digest;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::JointGenerationActionV1;
use codex_hepta_neuron::JointGenerationCommandV1;
use codex_hepta_neuron::JointGenerationInputV1;
use codex_hepta_neuron::JointGenerationSamplerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FrozenGenerationEpisodeV1;
use crate::GenerationEpisodeErrorV1;

const CANDIDATES: [&str; 8] = [
    "abstain", "audio", "image", "shared", "stop", "text", "verify", "video",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JointGenerationPlanningProfileV1 {
    pub utility: UtilityProfile,
    pub policy: EvaluationPolicyV1,
    pub scalarization: Option<ScalarizationProfile>,
}

impl JointGenerationPlanningProfileV1 {
    /// Binds all aggregation, unit, risk/resource ceiling and scoring settings.
    pub fn digest(&self) -> Result<Digest32, NduError> {
        if self.utility.dimensions.len() > 8
            || self.utility.risk_ceilings.len() > 32
            || self.utility.resource_ceilings.len() > 32
            || self.policy.utility_rules.len() > 8
            || self.policy.uncertainty_rules.len() > 8
            || self.policy.pareto_absolute_tolerances.len() > 8
            || self.policy.risk_rules.len() > 32
            || self.policy.resource_rules.len() > 32
        {
            return Err(NduError::DimensionLimitExceeded);
        }
        if self.utility.required_organs.organ_ids.len() > 32 {
            return Err(NduError::RequiredOrganLimitExceeded);
        }
        if let Some(scalarization) = &self.scalarization
            && (scalarization.weights.len() > 8
                || scalarization.weights.len() != self.utility.dimensions.len())
        {
            return Err(NduError::IncompleteScalarization);
        }
        let utility = canonical_utility_profile_digest(&self.utility)?;
        let policy = canonical_evaluation_policy_digest(&self.utility, &self.policy)?;
        let mut bytes = b"hepta.intelligence.joint-planning-profile.v1\0".to_vec();
        bytes.extend_from_slice(utility.as_array());
        bytes.extend_from_slice(policy.as_array());
        match &self.scalarization {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(canonical_scalarization_digest(value)?.as_array());
            }
            None => bytes.push(0),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JointGenerationStepV1 {
    pub operation_id: StableId,
    /// Unique for each actual planning attempt, independent of worker retries.
    pub planning_attempt_id: StableId,
    pub admitted_at_micros: u64,
    pub deadline_micros: u64,
}

/// An evaluated recommendation. A missing request
/// means abstention or a non-unique recommendation, never an implicit STOP.
pub struct JointGenerationPlannedStepV1 {
    pub request: Option<CellGenerationRequestV2>,
    pub evaluation: NduEvaluationReceiptV2,
}

/// Record the measured attempt through the existing owner even when evaluation
/// failed. The host serializes planning and retains this return value on retry;
/// this pure composer is not a durable execution owner. A lost process/return
/// still has unknown costs and cannot be treated as a complete measurement.
pub struct JointGenerationPlanningAttemptV1 {
    pub result: Result<JointGenerationPlannedStepV1, JointGenerationPlanErrorV1>,
    pub planning_cost: CellCostEntryV2,
}

#[derive(Debug)]
pub enum JointGenerationPlanErrorV1 {
    Binding(&'static str),
    Generation(CellGenerationErrorV2),
    Episode(GenerationEpisodeErrorV1),
    Ndu(NduError),
}

impl std::fmt::Display for JointGenerationPlanErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for JointGenerationPlanErrorV1 {}

pub fn joint_generation_sampler_digest_v1(
    public_digest: [u8; 32],
    seed: u64,
    sampler: JointGenerationSamplerV1,
) -> Result<Digest32, CellGenerationErrorV2> {
    let input = JointGenerationInputV1 {
        public_digest,
        command: JointGenerationCommandV1::Init { seed, sampler },
    }
    .encode()?;
    Ok(Digest32::of_parts(&[
        b"hepta.intelligence.joint-init.v1\0",
        &input,
    ]))
}

/// Claims from owner meters still require their ordinary authenticated host.
/// This digest prevents accidentally carrying predictions across owner cuts.
pub fn joint_generation_contribution_support_v1(
    observation: &CellGenerationObservationV1,
    candidate: &StableId,
    organ: &StableId,
) -> Result<Digest32, CellGenerationErrorV2> {
    Ok(contribution_support(
        observation.digest()?,
        candidate,
        organ,
    ))
}

fn contribution_support(cut: [u8; 32], candidate: &StableId, organ: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.intelligence.joint-contribution.v1\0",
        &cut,
        Digest32::of_bytes(candidate.as_str().as_bytes()).as_array(),
        Digest32::of_bytes(organ.as_str().as_bytes()).as_array(),
    ])
}

/// Opt-in composition for an already admitted backend. The generic V2 API and
/// historical worker Auto profile remain unchanged; this route never emits Auto.
pub struct JointGenerationEpisodePlanV1 {
    episode: FrozenGenerationEpisodeV1,
    public_digest: [u8; 32],
    initialization: JointGenerationCommandV1,
    profile: JointGenerationPlanningProfileV1,
}

impl JointGenerationEpisodePlanV1 {
    pub fn new(
        episode: FrozenGenerationEpisodeV1,
        public_digest: [u8; 32],
        seed: u64,
        sampler: JointGenerationSamplerV1,
        profile: JointGenerationPlanningProfileV1,
    ) -> Result<Self, JointGenerationPlanErrorV1> {
        use JointGenerationPlanErrorV1 as E;
        if !episode.input().initial.state.is_empty()
            || episode.input().sampler_digest
                != joint_generation_sampler_digest_v1(public_digest, seed, sampler)
                    .map_err(E::Generation)?
            || episode.input().policy_digest != profile.digest().map_err(E::Ndu)?
        {
            return Err(E::Binding("Joint initialization or planning profile"));
        }
        Ok(Self {
            episode,
            public_digest,
            initialization: JointGenerationCommandV1::Init { seed, sampler },
            profile,
        })
    }

    pub fn initialize(
        &self,
        observation: &CellGenerationObservationV1,
        step: JointGenerationStepV1,
    ) -> Result<CellGenerationRequestV2, JointGenerationPlanErrorV1> {
        self.require_ready(observation)?;
        if observation.snapshot() != &self.episode.input().initial {
            return Err(JointGenerationPlanErrorV1::Binding("initial snapshot"));
        }
        self.request(observation, self.initialization.clone(), step)
    }

    pub fn plan_advance(
        &self,
        observation: &CellGenerationObservationV1,
        contributions: ContributionSet,
        step: JointGenerationStepV1,
    ) -> Result<JointGenerationPlanningAttemptV1, JointGenerationPlanErrorV1> {
        use JointGenerationPlanErrorV1 as E;
        self.require_ready(observation)?;
        let event_id = Digest32::of_parts(&[
            b"hepta.intelligence.joint-planning-attempt.v1\0",
            &observation.task_digest(),
            step.planning_attempt_id.as_str().as_bytes(),
        ])
        .into_array();
        if observation
            .cost()
            .entries()
            .iter()
            .any(|entry| entry.event_id == event_id)
        {
            return Err(E::Binding("planning attempt already recorded"));
        }
        let started = Instant::now();
        let result = self.evaluate(observation, contributions, step);
        let planning_cost = CellCostEntryV2 {
            event_id,
            identity: observation.cost().identity(),
            stage: CellCostStageV2::Planning,
            outcome: if result.is_ok() {
                CellCostOutcomeV2::Succeeded
            } else {
                CellCostOutcomeV2::Failed
            },
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: u64::try_from(started.elapsed().as_micros()).ok(),
                ..CellCostMetricsV2::default()
            },
        };
        Ok(JointGenerationPlanningAttemptV1 {
            result,
            planning_cost,
        })
    }

    fn evaluate(
        &self,
        observation: &CellGenerationObservationV1,
        contributions: ContributionSet,
        step: JointGenerationStepV1,
    ) -> Result<JointGenerationPlannedStepV1, JointGenerationPlanErrorV1> {
        use JointGenerationPlanErrorV1 as E;
        if step.admitted_at_micros >= step.deadline_micros {
            return Err(E::Generation(CellGenerationErrorV2::Deadline));
        }
        if observation.snapshot().revision == 0 || observation.snapshot().state.is_empty() {
            return Err(E::Binding("Joint state not initialized"));
        }
        let initial_input = JointGenerationInputV1 {
            public_digest: self.public_digest,
            command: self.initialization.clone(),
        }
        .encode()
        .map_err(E::Generation)?;
        if observation.first_advance_input_digest()
            != Some(Digest32::of_bytes(&initial_input).into_array())
        {
            return Err(E::Binding(
                "actual Joint initialization differs from frozen sampler",
            ));
        }
        if contributions.objective_digest != self.episode.input().objective_digest
            || contributions.generation.get() != observation.snapshot().generation
        {
            return Err(E::Binding("NDU objective or generation"));
        }
        if contributions.contributions.len() > 4096 {
            return Err(E::Ndu(NduError::ContributionLimitExceeded));
        }
        let candidates: BTreeSet<_> = contributions
            .contributions
            .iter()
            .map(|contribution| contribution.candidate_id.as_str())
            .collect();
        if candidates != CANDIDATES.into_iter().collect() {
            return Err(E::Binding(
                "complete Joint candidate set including STOP and abstain",
            ));
        }
        let cut = observation.digest().map_err(E::Generation)?;
        for contribution in &contributions.contributions {
            if contribution.support_digest
                != contribution_support(cut, &contribution.candidate_id, &contribution.organ_id)
            {
                return Err(E::Binding("contribution owner cut"));
            }
        }
        let evaluation = evaluate_candidates_with_policy(
            contributions,
            self.profile.utility.clone(),
            self.profile.scalarization.clone(),
            self.profile.policy.clone(),
        )
        .map_err(E::Ndu)?;
        let action = match evaluation
            .base
            .advisory_recommendation
            .as_ref()
            .map(StableId::as_str)
        {
            Some("shared") => Some(JointGenerationActionV1::Shared),
            Some("image") => Some(JointGenerationActionV1::Image),
            Some("audio") => Some(JointGenerationActionV1::Audio),
            Some("video") => Some(JointGenerationActionV1::Video),
            Some("text") => Some(JointGenerationActionV1::Text),
            Some("verify") => Some(JointGenerationActionV1::Verify),
            Some("stop") => Some(JointGenerationActionV1::Stop),
            Some("abstain") | None => None,
            Some(_) => return Err(E::Binding("unmapped NDU candidate")),
        };
        let request = action
            .map(|action| {
                self.request(
                    observation,
                    JointGenerationCommandV1::Advance { action },
                    step,
                )
            })
            .transpose()?;
        Ok(JointGenerationPlannedStepV1 {
            request,
            evaluation,
        })
    }

    fn require_ready(
        &self,
        observation: &CellGenerationObservationV1,
    ) -> Result<(), JointGenerationPlanErrorV1> {
        use JointGenerationPlanErrorV1 as E;
        self.episode
            .validate_observation(observation)
            .map_err(E::Episode)?;
        if observation.pending_request_digest().is_some() || observation.pending_output().is_some()
        {
            return Err(E::Generation(CellGenerationErrorV2::Pending));
        }
        if observation.snapshot().stopped {
            return Err(E::Generation(CellGenerationErrorV2::Stopped));
        }
        Ok(())
    }

    fn request(
        &self,
        observation: &CellGenerationObservationV1,
        command: JointGenerationCommandV1,
        step: JointGenerationStepV1,
    ) -> Result<CellGenerationRequestV2, JointGenerationPlanErrorV1> {
        use JointGenerationPlanErrorV1 as E;
        let request = CellGenerationRequestV2 {
            operation_id: step.operation_id.to_string(),
            task_digest: self.episode.task_digest().into_array(),
            source_frontier: self.episode.input().source_frontier.into_array(),
            predecessor: observation.snapshot().clone(),
            input: JointGenerationInputV1 {
                public_digest: self.public_digest,
                command,
            }
            .encode()
            .map_err(E::Generation)?,
            admitted_at_micros: step.admitted_at_micros,
            deadline_micros: step.deadline_micros,
        };
        request.digest().map_err(E::Generation)?;
        Ok(request)
    }
}

#[cfg(test)]
#[path = "joint_generation_plan_v1_tests.rs"]
mod tests;
