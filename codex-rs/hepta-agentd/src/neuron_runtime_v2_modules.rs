fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn signed_delta_u64(current: u64, previous: u64) -> i64 {
    let value = i128::from(current) - i128::from(previous);
    value.clamp(i128::from(i64::MIN), i128::from(i64::MAX)) as i64
}

fn signed_delta_usize(current: usize, previous: usize) -> i64 {
    let current = i128::try_from(current).unwrap_or(i128::MAX);
    let previous = i128::try_from(previous).unwrap_or(i128::MAX);
    (current - previous).clamp(i128::from(i64::MIN), i128::from(i64::MAX)) as i64
}

#[path = "neuron_artifact_admission_v2.rs"]
mod artifact_admission;

#[cfg(test)]
#[path = "neuron_runtime_v2_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "neuron_runtime_v2_control_tests.rs"]
mod control_tests;

#[cfg(test)]
#[path = "neuron_runtime_v2_durable_state_tests.rs"]
mod durable_state_tests;

#[cfg(test)]
#[path = "neuron_runtime_v2_decision_cell_fixture.rs"]
mod decision_cell_tests;

#[cfg(test)]
#[path = "neuron_runtime_v2_lock_metrics_tests.rs"]
mod lock_metrics_tests;
