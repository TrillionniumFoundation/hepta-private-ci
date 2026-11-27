use super::*;
use crate::differentiation_plan::freeze_differentiation_plan_v1;
use crate::differentiation_test_support::*;

#[test]
fn persistent_demand_is_order_independent_within_a_window_and_authority_free() {
    let plan = freeze_differentiation_plan_v1(request()).expect("plan");
    let mut observations = windows(&plan);
    let receipt = assess_differentiation_demand_v1(&plan, &observations).expect("demand");
    assert!(receipt.supports_isolated_study());
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    for window in &mut observations {
        window.cases.reverse();
    }
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &observations),
        Ok(receipt)
    );
}

#[test]
fn repeated_windows_tasks_or_source_observations_cannot_create_persistence() {
    let plan = freeze_differentiation_plan_v1(request()).expect("plan");
    let original = windows(&plan);
    let mut duplicate_window = original.clone();
    duplicate_window[1] = original[0].clone();
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &duplicate_window),
        Err(DifferentiationErrorV1::WindowSequence)
    );
    let mut duplicate_task = original.clone();
    duplicate_task[1].cases[0].task_id = original[0].cases[0].task_id.clone();
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &duplicate_task),
        Err(DifferentiationErrorV1::DuplicateIdentity)
    );
    let mut duplicate_source = original.clone();
    duplicate_source[1].cases[0].observation_digest = original[0].cases[0].observation_digest;
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &duplicate_source),
        Err(DifferentiationErrorV1::DuplicateIdentity)
    );
}

#[test]
fn a_transient_spike_or_underpowered_window_retains_the_parent() {
    let plan = freeze_differentiation_plan_v1(request()).expect("plan");
    let mut observations = windows(&plan);
    observations[1].cases[0].error_ppm = 0;
    assert!(
        !assess_differentiation_demand_v1(&plan, &observations)
            .expect("transient")
            .supports_isolated_study()
    );
    let mut observations = windows(&plan);
    observations[1].cases.pop();
    assert!(
        !assess_differentiation_demand_v1(&plan, &observations)
            .expect("few samples")
            .supports_isolated_study()
    );
}

#[test]
fn a_persistent_partition_can_justify_a_study_even_with_low_error() {
    let mut partition_request = request();
    partition_request.demand.trigger = DifferentiationTriggerV1::PersistentTaskPartition;
    partition_request.demand.minimum_error_ppm = 0;
    partition_request.demand.diagnosis = DifferentiationDiagnosisV1::CapacityShortfall;
    let partition_plan =
        freeze_differentiation_plan_v1(partition_request.clone()).expect("partition plan");
    let mut observations = windows(&partition_plan);
    for window in &mut observations {
        for case in &mut window.cases {
            case.error_ppm = 10;
        }
    }
    assert!(
        assess_differentiation_demand_v1(&partition_plan, &observations)
            .expect("partition demand")
            .supports_isolated_study()
    );
    partition_request.demand.trigger = DifferentiationTriggerV1::PersistentError;
    partition_request.demand.minimum_error_ppm = 500_000;
    let error_plan = freeze_differentiation_plan_v1(partition_request).expect("error plan");
    assert!(
        !assess_differentiation_demand_v1(&error_plan, &observations)
            .expect("low error")
            .supports_isolated_study()
    );
    assert_ne!(partition_plan.digest(), error_plan.digest());
}

#[test]
fn chronology_parent_partition_and_holdout_leakage_are_checked() {
    let plan = freeze_differentiation_plan_v1(request()).expect("plan");
    let mut observations = windows(&plan);
    observations[1].starts_at_ms += 1;
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &observations),
        Err(DifferentiationErrorV1::WindowSequence)
    );
    let mut observations = windows(&plan);
    observations[0].parent_artifact_digest = digest("other-parent");
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &observations),
        Err(DifferentiationErrorV1::ParentBinding)
    );
    let mut observations = windows(&plan);
    observations[0].partition_id = id("partition:other");
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &observations),
        Err(DifferentiationErrorV1::PlanBinding)
    );
    let mut observations = windows(&plan);
    observations[0].cases[0].task_id = id("new:1");
    assert_eq!(
        assess_differentiation_demand_v1(&plan, &observations),
        Err(DifferentiationErrorV1::DataLeakage)
    );
}

#[test]
fn freeze_rejects_posthoc_policy_duplicate_panels_and_time_overflow() {
    let mut r = request();
    r.frozen_at_ms = r.demand.starts_at_ms;
    assert_eq!(
        freeze_differentiation_plan_v1(r),
        Err(DifferentiationErrorV1::InvalidPlan)
    );
    let mut r = request();
    r.retention_panels[0].task_ids.push(id("new:1"));
    assert_eq!(
        freeze_differentiation_plan_v1(r),
        Err(DifferentiationErrorV1::DuplicateIdentity)
    );
    let mut r = request();
    r.demand.window_width_ms = u64::MAX;
    assert_eq!(
        freeze_differentiation_plan_v1(r),
        Err(DifferentiationErrorV1::Arithmetic)
    );
}

#[test]
fn distinct_labels_do_not_hide_shared_identity_key_credential_or_controller() {
    for pair in 0..3 {
        for field in 0..4 {
            let mut r = request();
            let (source, target) = match pair {
                0 => (&r.actors.generator, &mut r.actors.evaluator),
                1 => (&r.actors.generator, &mut r.actors.outcome_observer),
                _ => (&r.actors.evaluator, &mut r.actors.outcome_observer),
            };
            match field {
                0 => target.principal = source.principal.clone(),
                1 => target.signing_key_digest = source.signing_key_digest,
                2 => target.credential_chain_digest = source.credential_chain_digest,
                _ => target.controller_digest = source.controller_digest,
            }
            assert_eq!(
                freeze_differentiation_plan_v1(r),
                Err(DifferentiationErrorV1::SourceCollision)
            );
        }
    }
}
