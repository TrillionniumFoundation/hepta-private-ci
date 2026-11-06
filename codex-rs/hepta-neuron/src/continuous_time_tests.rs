use super::*;
use pretty_assertions::assert_eq;

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn fixture() -> (
    HcsnTimeProfileV1,
    HcsnClockIdentityV1,
    HcsnClockCheckpointV1,
) {
    let profile = HcsnTimeProfileV1 {
        maximum_gap_micros: 1_000_000,
        forecast_horizon_micros: 250_000,
        integration: HcsnIntegrationV1::ValueKernel,
    };
    let identity = HcsnClockIdentityV1 {
        clock_epoch: Digest32::of_bytes(b"host/boot/clock"),
        scope_digest: Digest32::of_bytes(b"scope"),
        generation: checked(Generation::new(/*value*/ 1)),
        writer_epoch: 7,
        model_digest: Digest32::of_bytes(b"graph/parameters"),
    };
    let checkpoint = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        /*last_micros*/ 9_000_000_000_000_000_000,
        Digest32::of_bytes(b"full-backend-state"),
    ));
    (profile, identity, checkpoint)
}

#[test]
fn elapsed_time_is_computed_as_integer_before_conversion_to_seconds() {
    let (profile, identity, previous) = fixture();
    let start = previous.last_micros();
    let short = checked(plan_hcsn_interval_v1(
        &profile,
        identity,
        &previous,
        start + 1,
    ));
    let long = checked(plan_hcsn_interval_v1(
        &profile,
        identity,
        &previous,
        start + 1_000_000,
    ));
    assert_eq!(short.elapsed_micros, 1);
    assert_eq!(long.elapsed_micros, 1_000_000);
    assert_eq!(short.substep_micros as f64 / 1e6, 0.000_001);
    assert_eq!(long.substep_micros as f64 / 1e6, 1.0);
    let json = checked(serde_json::to_vec(&long));
    assert_eq!(
        checked(serde_json::from_slice::<HcsnIntervalPlanV1>(&json)),
        long
    );
    assert_eq!(previous, fixture().2);
}

#[test]
fn population_plan_preserves_the_fixed_refractory_grid_and_bounds_work() {
    let (mut profile, identity, _) = fixture();
    profile.integration = HcsnIntegrationV1::PopulationGrid {
        step_micros: 10_000,
        max_substeps: 4,
    };
    let previous = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        /*last_micros*/ 100,
        Digest32::of_bytes(b"population-and-refractory-queue"),
    ));
    let plan = checked(plan_hcsn_interval_v1(
        &profile, identity, &previous, /*end_micros*/ 40_100,
    ));
    assert_eq!(
        (plan.substeps, plan.substep_micros, plan.elapsed_micros),
        (4, 10_000, 40_000)
    );
    for (end, error) in [
        (41_100, HcsnTimeError::GridMisaligned),
        (50_100, HcsnTimeError::SubstepLimit),
    ] {
        assert_eq!(
            plan_hcsn_interval_v1(&profile, identity, &previous, end),
            Err(error)
        );
    }
}

#[test]
fn population_age_admits_non_grid_intervals_and_preserves_event_budget() {
    let (mut profile, identity, _) = fixture();
    profile.integration = HcsnIntegrationV1::PopulationAge {
        max_step_micros: 10_000,
        max_substeps: 4,
    };
    let previous = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        /*last_micros*/ 100,
        Digest32::of_bytes(b"complete-cohorts-and-integer-expiries"),
    ));
    for elapsed in [1, 9_999, 10_001, 39_999, 40_000] {
        let plan = checked(plan_hcsn_interval_v1(
            &profile,
            identity,
            &previous,
            previous.last_micros() + elapsed,
        ));
        assert_eq!(
            (plan.elapsed_micros, plan.substep_micros, plan.substeps),
            (elapsed, 10_000, 4)
        );
        let committed = checked(commit_hcsn_interval_v1(
            &profile,
            identity,
            &previous,
            &plan,
            Digest32::of_bytes(b"complete-successor-cohorts"),
        ));
        assert_eq!(
            checked(HcsnClockCheckpointV1::restore(
                &profile,
                identity,
                &checked(committed.encode()),
                committed.digest(),
            )),
            committed
        );
    }
    assert_eq!(
        plan_hcsn_interval_v1(&profile, identity, &previous, /*end_micros*/ 40_101),
        Err(HcsnTimeError::SubstepLimit)
    );
    let mut fixed = profile;
    fixed.integration = HcsnIntegrationV1::PopulationGrid {
        step_micros: 10_000,
        max_substeps: 4,
    };
    assert_eq!(
        HcsnClockCheckpointV1::restore(
            &fixed,
            identity,
            &checked(previous.encode()),
            previous.digest(),
        ),
        Err(HcsnTimeError::ProfileMismatch)
    );
}

#[test]
fn invalid_clock_intervals_never_advance_checkpoint() {
    let (profile, identity, previous) = fixture();
    let snapshot = previous.clone();
    for (end, error) in [
        (previous.last_micros(), HcsnTimeError::NonIncreasingTime),
        (previous.last_micros() - 1, HcsnTimeError::NonIncreasingTime),
        (
            previous.last_micros() + 1_000_001,
            HcsnTimeError::GapExceeded,
        ),
    ] {
        assert_eq!(
            plan_hcsn_interval_v1(&profile, identity, &previous, end),
            Err(error)
        );
    }
    let late = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        u64::MAX - 100,
        previous.state_digest(),
    ));
    assert_eq!(
        plan_hcsn_interval_v1(&profile, identity, &late, u64::MAX),
        Err(HcsnTimeError::Arithmetic)
    );
    assert_eq!(previous, snapshot);
}

#[test]
fn identities_and_prediction_horizon_cannot_silently_reuse_old_state() {
    let (profile, identity, previous) = fixture();
    let mut alternatives = [identity; 5];
    alternatives[0].clock_epoch = Digest32::of_bytes(b"new-boot");
    alternatives[1].scope_digest = Digest32::of_bytes(b"other-scope");
    alternatives[2].generation = checked(identity.generation.next());
    alternatives[3].writer_epoch += 1;
    alternatives[4].model_digest = Digest32::of_bytes(b"new-weights");
    let encoded = checked(previous.encode());
    for changed in alternatives {
        assert_eq!(
            plan_hcsn_interval_v1(&profile, changed, &previous, previous.last_micros() + 1),
            Err(HcsnTimeError::IdentityMismatch)
        );
        assert_eq!(
            HcsnClockCheckpointV1::restore(&profile, changed, &encoded, previous.digest()),
            Err(HcsnTimeError::IdentityMismatch)
        );
    }
    let mut changed = profile;
    changed.forecast_horizon_micros += 1;
    assert_eq!(
        plan_hcsn_interval_v1(&changed, identity, &previous, previous.last_micros() + 1),
        Err(HcsnTimeError::ProfileMismatch)
    );
}

#[test]
fn resumed_plan_matches_uninterrupted_plan_and_uses_last_committed_timestamp() {
    let (profile, identity, initial) = fixture();
    let first = checked(plan_hcsn_interval_v1(
        &profile,
        identity,
        &initial,
        initial.last_micros() + 123_456,
    ));
    let committed = checked(commit_hcsn_interval_v1(
        &profile,
        identity,
        &initial,
        &first,
        Digest32::of_bytes(b"computed-state"),
    ));
    let restored = checked(HcsnClockCheckpointV1::restore(
        &profile,
        identity,
        &checked(committed.encode()),
        committed.digest(),
    ));
    assert_eq!(restored, committed);
    let end = committed.last_micros() + 987_654;
    assert_eq!(
        plan_hcsn_interval_v1(&profile, identity, &restored, end),
        plan_hcsn_interval_v1(&profile, identity, &committed, end)
    );
    assert_eq!(
        HcsnClockCheckpointV1::restore(
            &profile,
            identity,
            &checked(initial.encode()),
            committed.digest()
        ),
        Err(HcsnTimeError::CheckpointMismatch)
    );
}

#[test]
fn tampered_plan_checkpoint_and_unsupported_schema_are_rejected() {
    let (profile, identity, previous) = fixture();
    let plan = checked(plan_hcsn_interval_v1(
        &profile,
        identity,
        &previous,
        previous.last_micros() + 25_000,
    ));
    let mut altered = plan.clone();
    altered.elapsed_micros += 1;
    assert_eq!(
        commit_hcsn_interval_v1(
            &profile,
            identity,
            &previous,
            &altered,
            Digest32::of_bytes(b"result")
        ),
        Err(HcsnTimeError::PlanMismatch)
    );
    let different_state = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        previous.last_micros(),
        Digest32::of_bytes(b"other-backend-state"),
    ));
    assert_eq!(
        commit_hcsn_interval_v1(
            &profile,
            identity,
            &different_state,
            &plan,
            Digest32::of_bytes(b"result")
        ),
        Err(HcsnTimeError::PlanMismatch)
    );
    let mut encoded: serde_json::Value =
        checked(serde_json::from_slice(&checked(previous.encode())));
    for field in ["last_micros", "schema_version"] {
        let old = encoded[field].clone();
        encoded[field] = serde_json::Value::from(2_u64);
        assert_eq!(
            HcsnClockCheckpointV1::restore(
                &profile,
                identity,
                &checked(serde_json::to_vec(&encoded)),
                previous.digest()
            ),
            Err(HcsnTimeError::CheckpointMismatch)
        );
        encoded[field] = old;
    }
    encoded["unregistered"] = serde_json::Value::Bool(true);
    assert_eq!(
        HcsnClockCheckpointV1::restore(
            &profile,
            identity,
            &checked(serde_json::to_vec(&encoded)),
            previous.digest()
        ),
        Err(HcsnTimeError::CheckpointFormat)
    );
}

#[test]
fn invalid_profile_and_empty_backend_state_are_not_admitted() {
    let (mut profile, identity, previous) = fixture();
    assert_eq!(
        HcsnClockCheckpointV1::initial(&profile, identity, previous.last_micros(), Digest32::ZERO),
        Err(HcsnTimeError::InvalidState)
    );
    for integration in [
        HcsnIntegrationV1::PopulationGrid {
            step_micros: 0,
            max_substeps: 1,
        },
        HcsnIntegrationV1::PopulationGrid {
            step_micros: 10_000,
            max_substeps: 0,
        },
    ] {
        profile.integration = integration;
        assert_eq!(
            HcsnClockCheckpointV1::initial(
                &profile,
                identity,
                previous.last_micros(),
                previous.state_digest()
            ),
            Err(HcsnTimeError::InvalidProfile)
        );
    }
}

#[test]
fn exhausted_sequence_is_rejected_before_backend_execution() {
    let (profile, identity, mut previous) = fixture();
    previous.sequence = u64::MAX;
    previous.predecessor_digest = Digest32::of_bytes(b"prior-clock-checkpoint");
    previous.digest = previous.calculate_digest();
    let restored = checked(HcsnClockCheckpointV1::restore(
        &profile,
        identity,
        &checked(previous.encode()),
        previous.digest(),
    ));
    assert_eq!(
        plan_hcsn_interval_v1(&profile, identity, &restored, restored.last_micros() + 1),
        Err(HcsnTimeError::Arithmetic)
    );
}

#[test]
fn coarse_batch_uses_one_real_anchor_and_commits_only_its_final_state() {
    let (profile, identity, initial) = fixture();
    let start = initial.last_micros();
    let ends = [start + 100_000, start + 300_000, start + 1_200_000];
    let plans = checked(plan_hcsn_batch_v1(&profile, identity, &initial, &ends));
    assert_eq!(
        plans
            .iter()
            .map(|plan| (
                plan.start_micros,
                plan.elapsed_micros,
                plan.checkpoint_before.clone()
            ))
            .collect::<Vec<_>>(),
        vec![
            (start, 100_000, initial.digest().to_string()),
            (ends[0], 200_000, initial.digest().to_string()),
            (ends[1], 900_000, initial.digest().to_string())
        ]
    );
    let final_state = Digest32::of_bytes(b"actual-worker-final-tensors");
    let next = checked(commit_hcsn_batch_v1(
        &profile,
        identity,
        &initial,
        &plans,
        final_state,
    ));
    assert_eq!(
        (next.sequence(), next.last_micros(), next.state_digest()),
        (1, ends[2], final_state)
    );
    let restored = checked(HcsnClockCheckpointV1::restore(
        &profile,
        identity,
        &checked(next.encode()),
        next.digest(),
    ));
    assert_eq!(restored, next);
    let mut forged = plans.clone();
    forged[1].checkpoint_before = Digest32::of_bytes(b"invented-middle-state").to_string();
    assert_eq!(
        commit_hcsn_batch_v1(&profile, identity, &initial, &forged, final_state),
        Err(HcsnTimeError::PlanMismatch)
    );
    assert_eq!(
        commit_hcsn_batch_v1(&profile, identity, &initial, &plans, Digest32::ZERO),
        Err(HcsnTimeError::InvalidState)
    );
    assert_eq!(
        plan_hcsn_batch_v1(&profile, identity, &initial, &[]),
        Err(HcsnTimeError::InvalidBatch)
    );
    assert_eq!(
        plan_hcsn_batch_v1(&profile, identity, &initial, &[start + 1; 257]),
        Err(HcsnTimeError::InvalidBatch)
    );
    assert_eq!(
        plan_hcsn_batch_v1(&profile, identity, &initial, &[ends[0], ends[0]]),
        Err(HcsnTimeError::NonIncreasingTime)
    );
    assert_eq!(initial, fixture().2);
}
