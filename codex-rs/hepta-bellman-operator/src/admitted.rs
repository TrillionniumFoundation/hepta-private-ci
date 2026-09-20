//! Fail-closed public admission for learned operator fitting.
//!
//! The raw deterministic fitters remain crate-internal implementation details.
//! Public callers enter through these wrappers so relabelling a sample cannot
//! replay the same underlying evidence and the learned Bellman grid keeps the
//! same minimum action-domain contract as the deterministic reference path.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::learned::LearnedOperatorError;
use crate::learned::TabularOperatorArtifactV1;
use crate::learned::TabularOperatorPlanV1;
use crate::world_model::TabularWorldModelV1;
use crate::world_model::WorldModelError;
use crate::world_model::WorldModelSampleV1;

const MIN_ACTIONS: usize = 2;

/// Fit the simplest-sufficient tabular operator after replay-safe admission.
///
/// Evidence identity, not caller-controlled sample identity, is the replay
/// boundary. The underlying V1 artifact format is intentionally unchanged.
pub fn fit_tabular_operator(
    plan: TabularOperatorPlanV1,
) -> Result<TabularOperatorArtifactV1, LearnedOperatorError> {
    if plan.action_ids.len() < MIN_ACTIONS {
        return Err(LearnedOperatorError::InvalidGrid);
    }
    reject_duplicate_evidence(
        plan.samples.iter().map(|sample| sample.evidence_digest),
        || LearnedOperatorError::DuplicateIdentity("duplicate-evidence-digest".to_owned()),
    )?;
    crate::learned::fit_tabular_operator(plan)
}

/// Fit the deterministic action-conditioned world model after replay-safe
/// admission. Relabelling one observation with a different sample id does not
/// permit it to contribute twice to counts, probabilities, or mean outcomes.
pub fn fit_transition_model(
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
) -> Result<TabularWorldModelV1, WorldModelError> {
    reject_duplicate_evidence(samples.iter().map(|sample| sample.evidence_digest), || {
        WorldModelError::DuplicateSample("duplicate-evidence-digest".to_owned())
    })?;
    crate::world_model::fit_transition_model(model_id, dataset_digest, samples)
}

fn reject_duplicate_evidence<E, I, F>(digests: I, duplicate: F) -> Result<(), E>
where
    I: IntoIterator<Item = Digest32>,
    F: FnOnce() -> E + Copy,
{
    let mut seen = BTreeSet::new();
    for digest in digests {
        if !seen.insert(digest) {
            return Err(duplicate());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;

    use crate::learned::TabularOperatorSampleV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn tabular_sample(
        sample_id: &str,
        sensor_id: &str,
        action_id: &str,
        evidence: Digest32,
    ) -> TabularOperatorSampleV1 {
        TabularOperatorSampleV1 {
            sample_id: id(sample_id),
            sensor_id: id(sensor_id),
            action_id: id(action_id),
            target: FixedQ32::from_raw(1),
            evidence_digest: evidence,
        }
    }

    #[test]
    fn public_tabular_fit_rejects_relabelled_evidence() {
        let evidence = digest("same-observation");
        let plan = TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("producer"),
            generation: Generation::new(1).expect("generation"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            sensor_core_digest: digest("sensor-core"),
            training_profile_digest: digest("profile"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor-a")],
            action_ids: vec![id("action-a"), id("action-b")],
            samples: vec![
                tabular_sample("sample-a", "sensor-a", "action-a", evidence),
                tabular_sample("sample-b", "sensor-a", "action-b", evidence),
            ],
        };
        assert!(matches!(
            fit_tabular_operator(plan),
            Err(LearnedOperatorError::DuplicateIdentity(value))
                if value == "duplicate-evidence-digest"
        ));
    }

    #[test]
    fn public_world_model_fit_rejects_relabelled_evidence() {
        let evidence = digest("same-observation");
        let sample = |sample_id: &str| WorldModelSampleV1 {
            sample_id: id(sample_id),
            state_id: id("state-a"),
            action_id: id("action-a"),
            next_state_id: id("state-b"),
            outcome: FixedQ32::ZERO,
            evidence_digest: evidence,
        };
        assert!(matches!(
            fit_transition_model(
                id("model"),
                digest("dataset"),
                vec![sample("sample-a"), sample("sample-b")],
            ),
            Err(WorldModelError::DuplicateSample(value))
                if value == "duplicate-evidence-digest"
        ));
    }

    #[test]
    fn public_tabular_fit_matches_reference_action_domain_floor() {
        let plan = TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("producer"),
            generation: Generation::new(1).expect("generation"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            sensor_core_digest: digest("sensor-core"),
            training_profile_digest: digest("profile"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor-a")],
            action_ids: vec![id("action-a")],
            samples: vec![tabular_sample(
                "sample-a",
                "sensor-a",
                "action-a",
                digest("evidence-a"),
            )],
        };
        assert_eq!(
            fit_tabular_operator(plan),
            Err(LearnedOperatorError::InvalidGrid)
        );
    }
}
