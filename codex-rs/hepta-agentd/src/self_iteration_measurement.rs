//! Bounded physical qualification measurements. Runs are real guarded V2 ticks
//! in separately constructed baseline/candidate shadow owners. These raw facts
//! are not an eligibility decision and cannot replace the independent Eval gate.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::neuron::NeuronAdmissionError;
use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronCommitDispositionV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeCommitV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeConfigV1;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::StableId;
use tokio_util::sync::CancellationToken;

use super::*;

pub struct AgentdSelfIterationQualificationCaseV1 {
    pub case_id: StableId,
    pub baseline_tick: NeuronTickInputV1,
    pub candidate_tick: NeuronTickInputV1,
    pub baseline_port: CanonicalPortInputV1,
    pub candidate_port: CanonicalPortInputV1,
}

pub struct AgentdSelfIterationPhysicalMeasurementV1 {
    pub case_id: StableId,
    pub baseline: NeuronRuntimeCommitV2,
    pub candidate: NeuronRuntimeCommitV2,
    pub baseline_ready: bool,
    pub candidate_ready: bool,
    /// Original provider latency from durable receipt; replay lookup latency is
    /// never counted as a new inference observation.
    pub baseline_model_latency_micros: u64,
    pub candidate_model_latency_micros: u64,
    pub baseline_model_resident_bytes: u64,
    pub candidate_model_resident_bytes: u64,
    pub baseline_replayed: bool,
    pub candidate_replayed: bool,
    pub guarded_retention_verified: bool,
    pub authority: AuthorityPosture,
}

/// The shadow handles must own actual selected artifacts/control ports and have
/// independent state files. Installing these handles as production generations
/// is outside this measurement function; it grants no activation authority.
pub fn measure_self_iteration_qualification_v1(
    baseline: &crate::AgentdNeuronHandleV2,
    candidate: &crate::AgentdNeuronHandleV2,
    cases: &[AgentdSelfIterationQualificationCaseV1],
    objective: Digest32,
    budget: Duration,
    cancellation: &CancellationToken,
) -> Result<Vec<AgentdSelfIterationPhysicalMeasurementV1>, AgentdError> {
    if cases.is_empty()
        || cases.len() > 128
        || objective.is_zero()
        || budget.is_zero()
        || budget > Duration::from_secs(300)
        || baseline.generation().map_err(control_error)?
            == candidate.generation().map_err(control_error)?
    {
        return Err(invalid("qualification measurement budget or generations"));
    }
    let baseline_body = baseline
        .body_bundle_digest()
        .ok_or_else(|| invalid("baseline durable body"))?;
    let candidate_body = candidate
        .body_bundle_digest()
        .ok_or_else(|| invalid("candidate durable body"))?;
    let deadline = Instant::now()
        .checked_add(budget)
        .ok_or_else(|| invalid("measurement deadline"))?;
    let mut output = Vec::with_capacity(cases.len());
    let mut ids = std::collections::BTreeSet::new();
    for case in cases {
        if !ids.insert(case.case_id.clone())
            || case.baseline_tick.objective_digest != objective
            || case.candidate_tick.objective_digest != objective
            || case.baseline_tick.feature_vector_q24 != case.candidate_tick.feature_vector_q24
            || case.baseline_tick.input_feature_digest != case.candidate_tick.input_feature_digest
            || case.baseline_port.objective_digest != objective
            || case.candidate_port.objective_digest != objective
            || case.baseline_port.budget_micros == 0
            || case.candidate_port.budget_micros == 0
            || case.baseline_port.budget_micros > 10_000_000
            || case.candidate_port.budget_micros > 10_000_000
        {
            return Err(invalid("qualification case binding"));
        }
        let mut baseline_guard = MeasurementGuard {
            objective,
            generation: baseline.generation().map_err(control_error)?,
            deadline: deadline.min(
                Instant::now()
                    .checked_add(Duration::from_micros(case.baseline_port.budget_micros))
                    .ok_or_else(|| invalid("baseline measurement deadline"))?,
            ),
            cancellation,
        };
        let mut candidate_guard = MeasurementGuard {
            objective,
            generation: candidate.generation().map_err(control_error)?,
            deadline: deadline.min(
                Instant::now()
                    .checked_add(Duration::from_micros(case.candidate_port.budget_micros))
                    .ok_or_else(|| invalid("candidate measurement deadline"))?,
            ),
            cancellation,
        };
        let baseline_previous = baseline
            .query_result_guarded(&case.baseline_tick, &mut baseline_guard)
            .map_err(|error| invalid(format!("baseline current use: {error}")))?;
        let candidate_previous = candidate
            .query_result_guarded(&case.candidate_tick, &mut candidate_guard)
            .map_err(|error| invalid(format!("candidate current use: {error}")))?;
        let before = baseline
            .prepare(
                case.baseline_tick.tick_id.clone(),
                baseline_body,
                case.baseline_tick.clone(),
            )
            .map_err(|error| invalid(error.to_string()))?
            .execute(&case.baseline_port, &mut baseline_guard)
            .map_err(|error| invalid(error.to_string()))?;
        let after = candidate
            .prepare(
                case.candidate_tick.tick_id.clone(),
                candidate_body,
                case.candidate_tick.clone(),
            )
            .map_err(|error| invalid(error.to_string()))?
            .execute(&case.candidate_port, &mut candidate_guard)
            .map_err(|error| invalid(error.to_string()))?;
        // Re-read through the same current-use guards. Equality covers the full
        // durable result, not merely an acknowledged flag or digest projection.
        let retained = baseline
            .query_result_guarded(&case.baseline_tick, &mut baseline_guard)
            .map_err(|error| invalid(error.to_string()))?
            == Some(before.clone())
            && candidate
                .query_result_guarded(&case.candidate_tick, &mut candidate_guard)
                .map_err(|error| invalid(error.to_string()))?
                == Some(after.clone());
        if !retained {
            return Err(invalid("qualification result retention changed"));
        }
        output.push(AgentdSelfIterationPhysicalMeasurementV1 {
            case_id: case.case_id.clone(),
            baseline_ready: before.disposition == NeuronCommitDispositionV1::CommittedReady,
            candidate_ready: after.disposition == NeuronCommitDispositionV1::CommittedReady,
            baseline_model_latency_micros: before.output.model_runtime.latency_micros,
            candidate_model_latency_micros: after.output.model_runtime.latency_micros,
            baseline_model_resident_bytes: before.output.model_runtime.resident_bytes,
            candidate_model_resident_bytes: after.output.model_runtime.resident_bytes,
            baseline_replayed: baseline_previous.is_some(),
            candidate_replayed: candidate_previous.is_some(),
            baseline: before,
            candidate: after,
            guarded_retention_verified: retained,
            authority: AuthorityPosture::DENY_ALL,
        });
    }
    Ok(output)
}

struct MeasurementGuard<'a> {
    objective: Digest32,
    generation: u64,
    deadline: Instant,
    cancellation: &'a CancellationToken,
}
impl NeuronAdmissionGuard for MeasurementGuard<'_> {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        if input.objective_digest != self.objective
            || input.body_generation != Some(self.generation)
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        Ok(())
    }
}
