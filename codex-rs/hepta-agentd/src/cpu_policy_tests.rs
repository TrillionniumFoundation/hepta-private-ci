//! Deterministic proposal rules only; these inputs are not benchmark results.
use super::*;
use pretty_assertions::assert_eq;

const MAX: u64 = 50_000_000;

fn usage(tick: u64, cap: u64) -> AgentdHos2Usage {
    let sample = 10_000_000_000 + tick * CPU_POLICY_INTERVAL_NS;
    AgentdHos2Usage {
        boot_id: [1; 16],
        observer_space_id: [2; 16],
        revision: 1,
        sample_boottime_ns: sample,
        cumulative_cpu_ns: 2_000_000_000 + tick * 100_000_000,
        window_start_ns: sample,
        window_consumed_ns: 0,
        active_cap_ns: cap,
        active_period_ns: HOS2_CPU_PERIOD_NS,
        event_sequence: 1 + tick,
        dropped_events: 0,
    }
}

fn measurement(usage: &AgentdHos2Usage, demand: ObservedCpuDemand) -> CpuDemandSample {
    CpuDemandSample {
        boot_id: usage.boot_id,
        observer_space_id: usage.observer_space_id,
        sample_boottime_ns: usage.sample_boottime_ns,
        demand,
    }
}

fn next(
    policy: &mut CpuPolicy,
    tick: u64,
    cap: u64,
    demand: ObservedCpuDemand,
) -> Result<Option<CpuBudgetProposal>, CpuPolicyError> {
    let sample = usage(tick, cap);
    policy.propose(&sample, &measurement(&sample, demand), sample.sample_boottime_ns)
}

#[test]
fn fixed_target_obeys_slew_bound_and_does_not_refill_same_budget() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: MAX }, MAX, &usage(0, 25_000_000)).unwrap();
    let proposal = next(&mut policy, 0, 25_000_000, ObservedCpuDemand::UnknownWaitReason).unwrap().unwrap();
    assert_eq!(proposal.cap_ns(), 30_000_000);
    assert_eq!(proposal.expected_revision(), 1);
    let mut fixed = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: MAX }, MAX, &usage(0, MAX)).unwrap();
    assert!(next(&mut fixed, 0, MAX, ObservedCpuDemand::Stable).unwrap().is_none());
}

#[test]
fn feedback_requires_two_separated_same_direction_samples() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    assert!(next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
    let proposal = next(&mut policy, 1, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().unwrap();
    assert_eq!(proposal.cap_ns(), 30_000_000);
    assert!(next(&mut policy, 2, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
}

#[test]
fn reversed_pressure_does_not_reuse_the_old_streak() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    assert!(next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
    assert!(next(&mut policy, 1, 25_000_000, ObservedCpuDemand::ProvenSpareCapacity).unwrap().is_none());
    assert_eq!(next(&mut policy, 2, 25_000_000, ObservedCpuDemand::ProvenSpareCapacity).unwrap().unwrap().cap_ns(), 20_000_000);
}

#[test]
fn fast_polling_cannot_create_pressure_or_repeated_proposals() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap();
    let mut fast = usage(0, 25_000_000);
    fast.sample_boottime_ns += 1;
    assert_eq!(policy.propose(&fast, &measurement(&fast, ObservedCpuDemand::RunnableCpuPressure), fast.sample_boottime_ns).unwrap_err(), CpuPolicyError::RateLimited);
    assert!(next(&mut policy, 1, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
}

#[test]
fn old_future_and_replayed_measurements_are_refused() {
    for now in [usage(0, 25_000_000).sample_boottime_ns - 1,
                usage(0, 25_000_000).sample_boottime_ns + CPU_POLICY_MAX_AGE_NS + 1] {
        let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
        assert_eq!(policy.propose(&usage(0, 25_000_000), &measurement(&usage(0, 25_000_000), ObservedCpuDemand::RunnableCpuPressure), now).unwrap_err(), CpuPolicyError::Stale);
    }
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap();
    assert_eq!(policy.propose(&usage(0, 25_000_000), &measurement(&usage(0, 25_000_000), ObservedCpuDemand::RunnableCpuPressure), usage(1, 0).sample_boottime_ns).unwrap_err(), CpuPolicyError::Stale);
}

#[test]
fn event_loss_is_not_cleared_by_a_later_zero_count() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    let mut lost = usage(0, 25_000_000);
    lost.dropped_events = 1;
    assert_eq!(policy.propose(&lost, &measurement(&lost, ObservedCpuDemand::RunnableCpuPressure), lost.sample_boottime_ns).unwrap_err(), CpuPolicyError::EventLoss);
    assert_eq!(next(&mut policy, 1, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap_err(), CpuPolicyError::EventLoss);
}

#[test]
fn unknown_wait_reason_and_explicit_pause_do_not_raise_cap() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    assert_eq!(next(&mut policy, 0, 25_000_000, ObservedCpuDemand::UnknownWaitReason).unwrap_err(), CpuPolicyError::UnknownDemand);
    assert!(next(&mut policy, 1, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
    assert!(next(&mut policy, 2, 25_000_000, ObservedCpuDemand::UserPaused).unwrap().is_none());
    assert!(next(&mut policy, 3, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
    let mut fixed = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: MAX }, MAX, &usage(0, 0)).unwrap();
    assert!(next(&mut fixed, 0, 0, ObservedCpuDemand::UserPaused).unwrap().is_none());
}

#[test]
fn zero_budget_is_not_inferred_to_be_user_pause() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 0)).unwrap();
    assert!(next(&mut policy, 0, 0, ObservedCpuDemand::RunnableCpuPressure).unwrap().is_none());
    assert_eq!(next(&mut policy, 1, 0, ObservedCpuDemand::RunnableCpuPressure).unwrap().unwrap().cap_ns(), MAX / 10);
}

#[test]
fn both_bounds_saturate_without_generating_equal_cap_writes() {
    for (cap, demand) in [(0, ObservedCpuDemand::ProvenSpareCapacity), (MAX, ObservedCpuDemand::RunnableCpuPressure)] {
        let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, cap)).unwrap();
        assert!(next(&mut policy, 0, cap, demand).unwrap().is_none());
        assert!(next(&mut policy, 1, cap, demand).unwrap().is_none());
    }
    assert!(CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: MAX + 1 }, MAX, &usage(0, 0)).is_err());
    assert!(CpuPolicy::new(CpuPolicyKind::Feedback, HOS2_CPU_PERIOD_NS + 1, &usage(0, 0)).is_err());
}

#[test]
fn changed_lifetime_and_counter_regression_are_refused() {
    for mutation in 0..4 {
        let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
        next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap();
        let mut changed = usage(1, 25_000_000);
        match mutation {
            0 => changed.boot_id = [3; 16],
            1 => changed.observer_space_id = [3; 16],
            2 => changed.cumulative_cpu_ns = 1,
            _ => changed.event_sequence = 0,
        }
        assert!(policy.propose(&changed, &measurement(&changed, ObservedCpuDemand::RunnableCpuPressure), changed.sample_boottime_ns).is_err());
    }
}

#[test]
fn another_valid_revision_starts_a_new_pressure_streak() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &usage(0, 25_000_000)).unwrap();
    next(&mut policy, 0, 25_000_000, ObservedCpuDemand::RunnableCpuPressure).unwrap();
    let mut changed = usage(1, 20_000_000);
    changed.revision = 2;
    assert!(policy.propose(&changed, &measurement(&changed, ObservedCpuDemand::RunnableCpuPressure), changed.sample_boottime_ns).unwrap().is_none());
}

#[test]
fn proposal_revalidates_original_sample_age_even_with_a_fresh_read() {
    let mut policy = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: MAX }, MAX, &usage(0, 25_000_000)).unwrap();
    let proposal = next(&mut policy, 0, 25_000_000, ObservedCpuDemand::Stable).unwrap().unwrap();
    assert_eq!(proposal.revalidate(&usage(3, 25_000_000), usage(3, 0).sample_boottime_ns), Err(CpuPolicyError::Stale));
    let mut changed = usage(1, 25_000_000);
    changed.revision += 1;
    assert_eq!(proposal.revalidate(&changed, changed.sample_boottime_ns), Err(CpuPolicyError::Conflict));
    assert!(proposal.revalidate(&usage(1, 25_000_000), usage(1, 0).sample_boottime_ns).is_ok());
}

#[test]
fn retained_charge_above_a_lowered_cap_is_a_valid_observation() {
    let mut charged = usage(0, 1_000_000);
    charged.sample_boottime_ns += 30_000_000;
    charged.window_consumed_ns = 20_000_000;
    let mut policy = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: 1_000_000 }, MAX, &charged).unwrap();
    assert!(policy.propose(&charged, &measurement(&charged, ObservedCpuDemand::Stable), charged.sample_boottime_ns).unwrap().is_none());
}

#[test]
fn fresh_native_usage_cannot_refresh_old_or_foreign_demand_evidence() {
    let initial = usage(0, 25_000_000);
    let fresh = usage(3, 25_000_000);
    for mutation in 0..4 {
        let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &initial).unwrap();
        let mut observed = measurement(&fresh, ObservedCpuDemand::RunnableCpuPressure);
        match mutation {
            0 => observed.sample_boottime_ns = initial.sample_boottime_ns,
            1 => observed.sample_boottime_ns += 1,
            2 => observed.boot_id = [8; 16],
            _ => observed.observer_space_id = [8; 16],
        }
        assert!(policy.propose(&fresh, &observed, fresh.sample_boottime_ns).is_err());
    }
}

#[test]
fn two_native_reads_cannot_reuse_one_demand_sample() {
    let initial = usage(0, 25_000_000);
    let mut policy = CpuPolicy::new(CpuPolicyKind::Feedback, MAX, &initial).unwrap();
    let observed = measurement(&initial, ObservedCpuDemand::RunnableCpuPressure);
    assert!(policy.propose(&initial, &observed, initial.sample_boottime_ns).unwrap().is_none());
    let fresh = usage(1, 25_000_000);
    assert_eq!(policy.propose(&fresh, &observed, fresh.sample_boottime_ns).unwrap_err(), CpuPolicyError::Stale);
}
