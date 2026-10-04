//! Bounded exact candidate/rollback pairs in the SAME original compiler owner.
use super::*;

/// Each pair uses the original independently selected artifact admission. It
/// cannot grant authority from a candidate ID or a copied runtime tuple.
pub struct CpuNeuronParameterRollbackPlanV2 {
    pub candidate_id: StableId,
    pub generation: CpuNeuronGenerationPlanV1,
    pub worker: crate::CpuNeuronControlConfigV2,
    pub admission: AgentdNeuronArtifactAdmissionV1,
}
pub(super) struct RetainedRollback {
    pub candidate_id: StableId,
    pub generation: CpuNeuronGenerationPlanV1,
    pub worker: Worker,
    pub admission: AgentdNeuronArtifactAdmissionV1,
}
fn validate_frontier(expected: &[StableId], actual: &[StableId]) -> Result<(), AgentdError> {
    let expected: std::collections::BTreeSet<_> = expected.iter().collect();
    let actual_set: std::collections::BTreeSet<_> = actual.iter().collect();
    if actual.len() != expected.len() || actual_set.len() != actual.len() || actual_set != expected
    {
        return Err(error(
            "rollback pairs differ from the complete original Update frontier",
        ));
    }
    Ok(())
}
// Compare the complete original material before moving the existing lease.
// A candidate ID or equal runtime digest alone cannot identify that lease.
pub(super) fn validate_first_rollback_binding(
    expected_id: &StableId,
    expected_material: &CpuNeuronGenerationPlanV1,
    first_id: &StableId,
    first_material: &CpuNeuronGenerationPlanV1,
) -> Result<(), AgentdError> {
    if first_id != expected_id
        || codex_hepta_neuron::encode_neuron_generation_material_v2(first_material)
            .map_err(|value| error(value.to_string()))?
            != codex_hepta_neuron::encode_neuron_generation_material_v2(expected_material)
                .map_err(|value| error(value.to_string()))?
    {
        return Err(error(
            "first rollback differs from the original held lease material",
        ));
    }
    Ok(())
}
impl CpuNeuronGovernedParameterCompilerV1 {
    /// Bind once, before the original Round/model/proposal/candidate owner work.
    /// Move the already held first admission once, after checking its whole
    /// material and every remaining pair. No second inspection of that lease
    /// is required; any rejection leaves the original admission untouched.
    pub fn bind_candidate_rollbacks_v2(
        &mut self,
        first_id: &StableId,
        first_material: &CpuNeuronGenerationPlanV1,
        remaining: Vec<CpuNeuronParameterRollbackPlanV2>,
    ) -> Result<(), AgentdError> {
        if self.policy.is_none()
            || self.round.is_some()
            || self.prepared.is_some()
            || self.admitted.is_some()
            || self.creation.is_some()
            || self.issuance.is_some()
            || self.materialized.is_some()
            || self.candidate_rollbacks.is_some()
        {
            return Err(error(
                "candidate rollback binding cannot replace original owner work",
            ));
        }
        let original_first = self
            .plan
            .candidates
            .first()
            .ok_or_else(|| error("original rollback has no Update candidate"))?;
        validate_first_rollback_binding(
            &original_first.candidate_id,
            &self.plan.rollback,
            first_id,
            first_material,
        )?;
        if self.plan.rollback_admission.is_none() {
            return Err(error("original rollback admission already consumed"));
        }
        let Worker::Current(first_worker) = &self.plan.rollback_worker else {
            return Err(error("original rollback requires the current worker owner"));
        };
        let policy = self
            .policy
            .as_ref()
            .ok_or_else(|| error("rollback policy absent"))?;
        let resources = self
            .owners
            .resources
            .as_ref()
            .ok_or_else(|| error("rollback resource owner absent"))?;
        policy.check_current(self.owners.clock.as_ref(), resources)?;
        let expected: Vec<_> = self
            .plan
            .candidates
            .iter()
            .map(|value| value.candidate_id.clone())
            .collect();
        let actual: Vec<_> = std::iter::once(first_id.clone())
            .chain(remaining.iter().map(|value| value.candidate_id.clone()))
            .collect();
        validate_frontier(&expected, &actual)?;
        let candidates: Vec<_> = self
            .plan
            .candidates
            .iter()
            .map(|value| CpuNeuronParameterMaterialCandidateV2 {
                candidate_id: &value.candidate_id,
                generation: &value.generation,
            })
            .collect();
        let rollbacks: Vec<_> = std::iter::once((first_id.clone(), &self.plan.rollback))
            .chain(
                remaining
                    .iter()
                    .map(|pair| (pair.candidate_id.clone(), &pair.generation)),
            )
            .collect();
        validate_cpu_neuron_parameter_rollback_pairs_v2(
            &CpuNeuronParameterMaterialPlanV2 {
                envelope: &self.plan.envelope,
                baseline_runtime: &self.plan.baseline_runtime,
                baseline_native: &self.plan.baseline_native,
                baseline_body: &self.plan.baseline_body,
                baseline_candidate_id: &self.plan.baseline_candidate_id,
                request: &self.plan.request,
                test_plan_digest: self.plan.test_plan_digest,
                candidates: &candidates,
                rollback: &self.plan.rollback,
            },
            &rollbacks,
        )?;
        policy.validate_worker(first_worker, resources)?;
        if first_worker.model_generation != self.plan.rollback.runtime.generation {
            return Err(error("original rollback worker generation differs"));
        }
        for pair in &remaining {
            policy.validate_worker(&pair.worker, resources)?;
            if pair.worker.model_generation != pair.generation.runtime.generation {
                return Err(error("exact rollback worker generation differs"));
            }
        }
        policy.check_current(self.owners.clock.as_ref(), resources)?;
        // All read-only checks have passed. The sole original first lease is
        // transferred rather than cloned, re-inspected, replaced or dropped.
        let first = RetainedRollback {
            candidate_id: first_id.clone(),
            generation: self.plan.rollback.clone(),
            worker: self.plan.rollback_worker.clone(),
            admission: self
                .plan
                .rollback_admission
                .take()
                .ok_or_else(|| error("original rollback admission already consumed"))?,
        };
        self.candidate_rollbacks = Some(
            std::iter::once(first)
                .chain(remaining.into_iter().map(|pair| RetainedRollback {
                    candidate_id: pair.candidate_id,
                    generation: pair.generation,
                    worker: Worker::Current(pair.worker),
                    admission: pair.admission,
                }))
                .collect(),
        );
        Ok(())
    }
    pub(super) fn take_original_rollback(
        &mut self,
        candidate: &StableId,
    ) -> Result<
        (
            CpuNeuronGenerationPlanV1,
            Worker,
            AgentdNeuronArtifactAdmissionV1,
        ),
        AgentdError,
    > {
        if let Some(pairs) = &mut self.candidate_rollbacks {
            let position = pairs
                .iter()
                .position(|value| &value.candidate_id == candidate)
                .ok_or_else(|| {
                    error("selected candidate's exact rollback requires owner recovery")
                })?;
            let pair = pairs.remove(position);
            return Ok((pair.generation, pair.worker, pair.admission));
        }
        Ok((
            self.plan.rollback.clone(),
            self.plan.rollback_worker.clone(),
            self.plan
                .rollback_admission
                .take()
                .ok_or_else(|| error("CPU compiler rollback requires original owner recovery"))?,
        ))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn original_rollback_pair_frontier_rejects_missing_duplicate_and_foreign_candidates() {
        let id = |value| StableId::new(value).unwrap();
        let full = vec![id("update-a"), id("update-b")];
        validate_frontier(&full, &full).unwrap();
        validate_frontier(&full, &[id("update-b"), id("update-a")]).unwrap();
        assert!(validate_frontier(&full, &[id("update-a")]).is_err());
        assert!(validate_frontier(&full, &[id("update-a"), id("update-a")]).is_err());
        assert!(validate_frontier(&full, &[id("update-a"), id("foreign")]).is_err());
    }
}
