//! Response-time calculation for one preemptive fixed-priority processor only.
//! Caller-supplied WCET/blocking bounds must include I/O, IRQ and kernel costs.
//! This does not measure those bounds or certify a host, jitter or multicore load.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FixedPriorityTaskV1 {
    pub period_ns: u64,
    pub deadline_ns: u64,
    pub execution_ns: u64,
    pub blocking_ns: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TimingError {
    InvalidProfile,
    DeadlineMiss { task: usize, response_ns: u128 },
    IterationLimit,
}

/// Tasks are ordered highest priority first, have zero release jitter and
/// constrained deadlines (`D <= T`). At most 64 tasks and 128 iterations/task.
pub fn fixed_priority_response_times(
    tasks: &[FixedPriorityTaskV1],
) -> Result<Vec<u64>, TimingError> {
    if tasks.is_empty()
        || tasks.len() > 64
        || tasks.iter().any(|t| {
            t.period_ns == 0
                || t.deadline_ns == 0
                || t.deadline_ns > t.period_ns
                || t.execution_ns == 0
        })
    {
        return Err(TimingError::InvalidProfile);
    }
    let mut result = Vec::with_capacity(tasks.len());
    for (index, task) in tasks.iter().enumerate() {
        let base = u128::from(task.execution_ns) + u128::from(task.blocking_ns);
        let mut response = base;
        let mut converged = false;
        for _ in 0..128 {
            if response > u128::from(task.deadline_ns) {
                return Err(TimingError::DeadlineMiss {
                    task: index,
                    response_ns: response,
                });
            }
            // Each previously checked higher-priority task has C <= D <= T,
            // so ceil(R/T)*C <= R+C <= 2*u64::MAX. At most 64 terms fit u128.
            let next = base
                + tasks[..index]
                    .iter()
                    .map(|higher| {
                        response.div_ceil(u128::from(higher.period_ns))
                            * u128::from(higher.execution_ns)
                    })
                    .sum::<u128>();
            if next == response {
                converged = true;
                break;
            }
            response = next;
        }
        if !converged {
            return Err(TimingError::IterationLimit);
        }
        result.push(response as u64);
    }
    Ok(result)
}

#[cfg(test)]
#[path = "timing_tests.rs"]
mod tests;
