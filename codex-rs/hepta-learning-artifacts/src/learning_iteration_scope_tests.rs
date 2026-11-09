use pretty_assertions::assert_eq;

use super::*;
use crate::learning_iteration_test_support::digest;
use crate::learning_iteration_test_support::owners;
use crate::learning_iteration_test_support::receipt;
use crate::learning_iteration_test_support::request;
use crate::test_support::FixtureValue;

#[test]
fn cell_scope_rejects_every_frozen_component_before_evaluation() {
    let mut coordinator = LearningIterationCoordinatorV1::new(request(), owners()).fixture("owner");
    for _ in 0..2 {
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("prefix");
    }
    let scope = FrozenLearningScopeV2::freeze(
        &request(),
        &owners(),
        LearningUpdateScopeV2::Cell,
        digest("rule"),
    )
    .fixture("scope");
    let original = receipt(&coordinator);
    scope
        .validate_observation(&original.observation)
        .fixture("cell adapter");
    let changes: [fn(&mut CellBundleComponentsV1); 9] = [
        |c| c.base = digest("changed"),
        |c| c.organ_adapter = Some(digest("changed")),
        |c| c.encoder = digest("changed"),
        |c| c.tokenizer = digest("changed"),
        |c| c.normalizer = digest("changed"),
        |c| c.numeric_profile = digest("changed"),
        |c| c.output_schema = digest("changed"),
        |c| c.state_schema = digest("changed"),
        |c| c.state_semantics = digest("changed"),
    ];
    for change in changes {
        let mut bad = original.clone();
        if let LearningIterationObservationV1::Training { candidate, .. } = &mut bad.observation {
            change(&mut candidate.components);
        }
        // The original profile has no cadence restriction. This control makes
        // the new refusal distinct from its retained structural validation.
        let mut legacy = coordinator.clone();
        legacy
            .record(bad.clone(), 20)
            .fixture("legacy structurally valid");
        assert_eq!(
            scope.validate_observation(&bad.observation),
            Err(LearningIterationError::UpdateScopeMismatch)
        );
        assert_eq!(
            scope.validate_snapshot(legacy.snapshot()),
            Err(LearningIterationError::UpdateScopeMismatch)
        );
    }
}

#[test]
fn organ_scope_preserves_cell_and_both_scopes_freeze_original_training_rule() {
    let mut coordinator = LearningIterationCoordinatorV1::new(request(), owners()).fixture("owner");
    for _ in 0..2 {
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("prefix");
    }
    let mut training = receipt(&coordinator);
    let scope = FrozenLearningScopeV2::freeze(
        &request(),
        &owners(),
        LearningUpdateScopeV2::Organ,
        digest("rule"),
    )
    .fixture("scope");
    assert_eq!(
        scope.validate_observation(&training.observation),
        Err(LearningIterationError::UpdateScopeMismatch)
    );
    if let LearningIterationObservationV1::Training { candidate, .. } = &mut training.observation {
        candidate.components.cell_adapter = None;
        candidate.components.organ_adapter = Some(digest("new-organ"));
        candidate.components.heads = digest("new-heads");
        candidate.components.calibration = digest("new-calibration");
        candidate.components.composition = digest("new-composition");
    }
    scope
        .validate_observation(&training.observation)
        .fixture("organ update");
    if let LearningIterationObservationV1::Training { candidate, .. } = &mut training.observation {
        candidate
            .training_lineage
            .as_mut()
            .fixture("lineage")
            .update_rule = digest("post-hoc-rule");
    }
    assert_eq!(
        scope.validate_observation(&training.observation),
        Err(LearningIterationError::UpdateScopeMismatch)
    );
}

#[test]
fn scope_is_exactly_bound_and_base_release_requires_a_different_owner() {
    let request = request();
    let owners = owners();
    assert_eq!(
        FrozenLearningScopeV2::freeze(
            &request,
            &owners,
            LearningUpdateScopeV2::BaseRelease,
            digest("rule")
        ),
        Err(LearningIterationError::SlowReleaseRequired)
    );
    let scope = FrozenLearningScopeV2::freeze(
        &request,
        &owners,
        LearningUpdateScopeV2::Cell,
        digest("rule"),
    )
    .fixture("scope");
    let mut changed = request.clone();
    changed.budget.maximum_training_steps += 1;
    assert_eq!(
        scope.validate_request(&changed, &owners),
        Err(LearningIterationError::UpdateScopeMismatch)
    );
    let organ = FrozenLearningScopeV2::freeze(
        &request,
        &owners,
        LearningUpdateScopeV2::Organ,
        digest("rule"),
    )
    .fixture("organ");
    assert_ne!(scope.binding(), organ.binding());
}
