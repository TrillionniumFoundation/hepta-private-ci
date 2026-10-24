//! Bounded experimental CPU proposals over the original HOS2 observation.
//! Neither policy owns authority, a delivery sequence, an outbox or an effect.

use crate::AgentdHos2Device;
use crate::AgentdHos2Usage;
use codex_hepta_memory::HOS2_CPU_PERIOD_NS;
use codex_hepta_memory::Hos2InstallBudgetV1;

pub const CPU_POLICY_INTERVAL_NS: u64 = 1_000_000_000;
pub const CPU_POLICY_MAX_AGE_NS: u64 = 2_000_000_000;

/// Both arms use a static envelope. Fixed means a fixed target, not bypassing
/// the same ten-percent slew bound when approaching that target.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CpuPolicyKind {
    Fixed { cap_ns: u64 },
    Feedback,
}

/// An observation from the trusted workload collector, never a model claim.
/// HOS2 ReadUsage alone does not expose runnable queues or blocking causes.
/// Unknown IO/lock/ancestor throttling cannot be classified as CPU pressure.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObservedCpuDemand {
    RunnableCpuPressure,
    ProvenSpareCapacity,
    Stable,
    UnknownWaitReason,
    UserPaused,
}

/// A real collector sample in the native boot/space and CLOCK_BOOTTIME domain.
/// The collector must establish the wait cause independently of ReadUsage.
/// Merely constructing this value does not prove that a collector exists.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CpuDemandSample {
    pub boot_id: [u8; 16],
    pub observer_space_id: [u8; 16],
    pub sample_boottime_ns: u64,
    pub demand: ObservedCpuDemand,
}

#[derive(Debug, Eq, PartialEq, thiserror::Error)]
pub enum CpuPolicyError {
    #[error("invalid CPU policy envelope or native observation")]
    Invalid,
    #[error("CPU observation is stale, future-dated or regressed")]
    Stale,
    #[error("CPU observation belongs to a different native lifetime")]
    IdentityChanged,
    #[error("CPU event loss requires independent reconciliation")]
    EventLoss,
    #[error("CPU policy tick is inside the one-second sampling interval")]
    RateLimited,
    #[error("the actual wait reason is unavailable")]
    UnknownDemand,
    #[error("the native revision or proposed budget changed")]
    Conflict,
    #[error("original native observation or request refused: {0}")]
    Native(String),
}

/// Non-serializable proposal. It is not a grant, delivery or durable receipt.
/// Keep it only until the original owner prepares its immutable K/D request.
#[derive(Debug)]
pub struct CpuBudgetProposal {
    observed: AgentdHos2Usage,
    demand_sample_boottime_ns: u64,
    proposed_at_ns: u64,
    cap_ns: u64,
    maximum_cap_ns: u64,
}

impl CpuBudgetProposal {
    pub fn cap_ns(&self) -> u64 {
        self.cap_ns
    }

    pub fn expected_revision(&self) -> u64 {
        self.observed.revision
    }

    /// Check an actual fresh native sample at submission preparation. This
    /// does not authorize a later queued/awaited dispatch: the embedding must
    /// preserve freshness at its original synchronous consumer boundary too.
    pub fn revalidate(
        &self,
        current: &AgentdHos2Usage,
        now_boottime_ns: u64,
    ) -> Result<(), CpuPolicyError> {
        validate_usage(current, now_boottime_ns)?;
        same_lifetime(&self.observed, current)?;
        if now_boottime_ns < self.proposed_at_ns
            || now_boottime_ns - self.observed.sample_boottime_ns > CPU_POLICY_MAX_AGE_NS
            || now_boottime_ns - self.demand_sample_boottime_ns > CPU_POLICY_MAX_AGE_NS
            || current.sample_boottime_ns < self.observed.sample_boottime_ns
            || current.cumulative_cpu_ns < self.observed.cumulative_cpu_ns
            || current.event_sequence < self.observed.event_sequence
        {
            return Err(CpuPolicyError::Stale);
        }
        if current.revision != self.observed.revision
            || current.active_cap_ns != self.observed.active_cap_ns
            || self.cap_ns > self.maximum_cap_ns
            || current.active_cap_ns.abs_diff(self.cap_ns) > self.maximum_cap_ns / 10
        {
            return Err(CpuPolicyError::Conflict);
        }
        Ok(())
    }

    /// Read the original device again, then use its existing typed request
    /// constructor. `sequence` comes from the original durable operation owner;
    /// this function never allocates it, performs an install or retries one.
    pub fn original_request(
        &self,
        device: &AgentdHos2Device,
        sequence: u64,
        read_request_id: u64,
        now_boottime: impl FnOnce() -> Result<u64, String>,
    ) -> Result<Hos2InstallBudgetV1, CpuPolicyError> {
        let current = device
            .read_usage(read_request_id)
            .map_err(CpuPolicyError::Native)?;
        let now = now_boottime().map_err(CpuPolicyError::Native)?;
        self.revalidate(&current, now)?;
        device
            .install_request(sequence, current.revision, self.cap_ns)
            .map_err(CpuPolicyError::Native)
    }
}

/// Process-local sampling/hysteresis only. Restarting this state does not
/// restore a grant, change K/D, resolve an uncertain effect or reset CPU usage.
pub struct CpuPolicy {
    kind: CpuPolicyKind,
    maximum_cap_ns: u64,
    initial: AgentdHos2Usage,
    last: Option<(AgentdHos2Usage, CpuDemandSample, u64)>,
    direction: Option<ObservedCpuDemand>,
    consecutive: u8,
    lost_events: bool,
}

impl CpuPolicy {
    pub fn new(
        kind: CpuPolicyKind,
        maximum_cap_ns: u64,
        initial: &AgentdHos2Usage,
    ) -> Result<Self, CpuPolicyError> {
        validate_usage(initial, initial.sample_boottime_ns)?;
        if !(10..=HOS2_CPU_PERIOD_NS).contains(&maximum_cap_ns)
            || initial.active_cap_ns > maximum_cap_ns
            || matches!(kind, CpuPolicyKind::Fixed { cap_ns } if cap_ns > maximum_cap_ns)
        {
            return Err(CpuPolicyError::Invalid);
        }
        Ok(Self {
            kind,
            maximum_cap_ns,
            initial: initial.clone(),
            last: None,
            direction: None,
            consecutive: 0,
            lost_events: false,
        })
    }

    /// At most one accepted sample per second. Two consecutive, same-direction
    /// feedback samples are required; each change is at most floor(max/10).
    /// On unavailable input retain the actual last budget: no fallback write.
    pub fn propose(
        &mut self,
        usage: &AgentdHos2Usage,
        demand: &CpuDemandSample,
        now_boottime_ns: u64,
    ) -> Result<Option<CpuBudgetProposal>, CpuPolicyError> {
        let result = self.propose_inner(usage, demand, now_boottime_ns);
        if result.is_err() {
            self.direction = None;
            self.consecutive = 0;
        }
        result
    }

    fn propose_inner(
        &mut self,
        usage: &AgentdHos2Usage,
        measurement: &CpuDemandSample,
        now: u64,
    ) -> Result<Option<CpuBudgetProposal>, CpuPolicyError> {
        if usage.dropped_events != 0 {
            self.lost_events = true;
        }
        if self.lost_events {
            return Err(CpuPolicyError::EventLoss);
        }
        validate_usage(usage, now)?;
        same_lifetime(&self.initial, usage)?;
        if measurement.boot_id != usage.boot_id
            || measurement.observer_space_id != usage.observer_space_id
        {
            return Err(CpuPolicyError::IdentityChanged);
        }
        if measurement.sample_boottime_ns > now
            || now - measurement.sample_boottime_ns > CPU_POLICY_MAX_AGE_NS
        {
            return Err(CpuPolicyError::Stale);
        }
        if usage.sample_boottime_ns < self.initial.sample_boottime_ns
            || usage.cumulative_cpu_ns < self.initial.cumulative_cpu_ns
            || usage.event_sequence < self.initial.event_sequence
            || usage.revision < self.initial.revision
        {
            return Err(CpuPolicyError::Stale);
        }
        if usage.revision == self.initial.revision
            && usage.active_cap_ns != self.initial.active_cap_ns
        {
            return Err(CpuPolicyError::Conflict);
        }
        if usage.active_cap_ns > self.maximum_cap_ns {
            return Err(CpuPolicyError::Invalid);
        }
        if let Some((previous, previous_demand, accepted_at)) = &self.last {
            if now < *accepted_at
                || usage.sample_boottime_ns <= previous.sample_boottime_ns
                || measurement.sample_boottime_ns <= previous_demand.sample_boottime_ns
                || usage.cumulative_cpu_ns < previous.cumulative_cpu_ns
                || usage.event_sequence < previous.event_sequence
                || usage.revision < previous.revision
            {
                return Err(CpuPolicyError::Stale);
            }
            if now - *accepted_at < CPU_POLICY_INTERVAL_NS
                || usage.sample_boottime_ns - previous.sample_boottime_ns < CPU_POLICY_INTERVAL_NS
                || measurement.sample_boottime_ns - previous_demand.sample_boottime_ns < CPU_POLICY_INTERVAL_NS
            {
                return Err(CpuPolicyError::RateLimited);
            }
            if usage.revision != previous.revision {
                self.direction = None;
                self.consecutive = 0;
            } else if usage.active_cap_ns != previous.active_cap_ns {
                return Err(CpuPolicyError::Conflict);
            }
        }
        self.last = Some((usage.clone(), *measurement, now));
        let demand = measurement.demand;
        if demand == ObservedCpuDemand::UserPaused {
            self.direction = None;
            self.consecutive = 0;
            return Ok(None);
        }
        let step = self.maximum_cap_ns / 10;
        let cap = match self.kind {
            CpuPolicyKind::Fixed { cap_ns } => {
                if cap_ns > usage.active_cap_ns {
                    usage.active_cap_ns.saturating_add(step).min(cap_ns)
                } else {
                    usage.active_cap_ns.saturating_sub(step).max(cap_ns)
                }
            }
            CpuPolicyKind::Feedback => {
                if demand == ObservedCpuDemand::UnknownWaitReason {
                    return Err(CpuPolicyError::UnknownDemand);
                }
                if demand == ObservedCpuDemand::Stable {
                    self.direction = None;
                    self.consecutive = 0;
                    return Ok(None);
                }
                self.consecutive = if self.direction == Some(demand) {
                    self.consecutive.saturating_add(1)
                } else {
                    1
                };
                self.direction = Some(demand);
                if self.consecutive < 2 {
                    return Ok(None);
                }
                self.direction = None;
                self.consecutive = 0;
                match demand {
                    ObservedCpuDemand::RunnableCpuPressure => usage.active_cap_ns.saturating_add(step).min(self.maximum_cap_ns),
                    ObservedCpuDemand::ProvenSpareCapacity => usage.active_cap_ns.saturating_sub(step),
                    _ => return Err(CpuPolicyError::Invalid),
                }
            }
        };
        if cap == usage.active_cap_ns {
            return Ok(None);
        }
        Ok(Some(CpuBudgetProposal {
            observed: usage.clone(),
            demand_sample_boottime_ns: measurement.sample_boottime_ns,
            proposed_at_ns: now,
            cap_ns: cap,
            maximum_cap_ns: self.maximum_cap_ns,
        }))
    }
}

fn same_lifetime(left: &AgentdHos2Usage, right: &AgentdHos2Usage) -> Result<(), CpuPolicyError> {
    if left.boot_id != right.boot_id || left.observer_space_id != right.observer_space_id {
        return Err(CpuPolicyError::IdentityChanged);
    }
    Ok(())
}

fn validate_usage(value: &AgentdHos2Usage, now: u64) -> Result<(), CpuPolicyError> {
    if value.sample_boottime_ns > now || now - value.sample_boottime_ns > CPU_POLICY_MAX_AGE_NS {
        return Err(CpuPolicyError::Stale);
    }
    if value.dropped_events != 0 {
        return Err(CpuPolicyError::EventLoss);
    }
    let window = value.sample_boottime_ns - value.sample_boottime_ns % HOS2_CPU_PERIOD_NS;
    let elapsed = value.sample_boottime_ns - window;
    if value.boot_id == [0; 16]
        || value.observer_space_id == [0; 16]
        || value.revision == 0
        || value.active_period_ns != HOS2_CPU_PERIOD_NS
        || value.window_start_ns != window
        || value.window_consumed_ns > elapsed
        || value.window_consumed_ns > value.cumulative_cpu_ns
        || value.cumulative_cpu_ns > value.sample_boottime_ns
        || value.cumulative_cpu_ns - value.window_consumed_ns > window
        || value.active_cap_ns > HOS2_CPU_PERIOD_NS
    {
        return Err(CpuPolicyError::Invalid);
    }
    Ok(())
}

#[cfg(test)]
#[path = "cpu_policy_tests.rs"]
mod tests;
