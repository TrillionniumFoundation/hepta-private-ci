// SPDX-License-Identifier: MPL-2.0

mod max_config;
mod native;

use alloc::sync::Arc;
use core::sync::atomic::{AtomicU32, Ordering};

use aster_systree::{Error, MAX_ATTR_SIZE, Result, SysAttrSetBuilder, SysPerms, SysStr};
use aster_util::{per_cpu_counter::PerCpuCounter, printer::VmPrinter};
use os_control::CPU_PERIOD_NS;
use ostd::{
    cpu::CpuId,
    mm::{VmReader, VmWriter},
    sync::{LocalIrqDisabled, SpinLock},
    task::{Task, atomic_mode::AsAtomicModeGuard},
    timer::Jiffies,
    warn,
};

use self::native::CpuBandwidthState;
use crate::{
    fs::cgroupfs::{
        CgroupMembership, CgroupNode,
        systree_node::{CgroupSysNode, CgroupSystem},
    },
    process::{Process, posix_thread::AsPosixThread},
    thread::AsThread,
    util::ReadCString,
};

/// A sub-controller responsible for CPU resource management in the cgroup subsystem.
///
/// This controller always exists so that `cpu.stat` remains readable even before `+cpu`
/// is enabled. When inactive, only the base usage fields are exposed and the non-root
/// CPU control files are hidden.
pub(crate) struct CpuController {
    /// Persistent CPU usage accounting for this cgroup.
    stats: CpuStats,
    /// Optional CPU resource control attributes exposed only when `+cpu` is active.
    control: Option<CpuControl>,
}

/// CPU usage accounting that survives CPU controller toggles.
struct CpuStats {
    /// A counter accumulates CPU time spent executing user-space code.
    ///
    /// The counter is in units of one [`Jiffies`] per increment.
    user: PerCpuCounter,
    /// A counter accumulates CPU time spent executing kernel code on behalf of tasks.
    ///
    /// The counter is in units of one [`Jiffies`] per increment.
    system: PerCpuCounter,
}

/// CPU resource controls that are reset whenever `+cpu` is re-enabled.
struct CpuControl {
    /// A value stores the configured relative CPU share for scheduler integration.
    weight: AtomicU32,
    /// The sole bandwidth accounting state and its configuration revision.
    max: SpinLock<CpuBandwidthState, LocalIrqDisabled>,
}

/// A CPU bandwidth limit.
#[cfg_attr(ktest, derive(Debug, Eq, PartialEq))]
#[derive(Clone, Copy)]
struct CpuMax {
    quota_usec: u64,
    period_usec: u64,
    window_start_ns: u64,
    used_ns: u64,
    /// All settled execution of this incarnation, including completed windows.
    cumulative_ns: u64,
    /// Latest observed endpoint, not another clock or an execution counter.
    last_observed_ns: u64,
    /// A lost or overflowing interval cannot become a successful native sample.
    accounting_fault: bool,
    /// A period change can retain consumption from a different window shape.
    native_window_valid_from_ns: Option<u64>,
    /// Positive overrun from earlier quota windows. Never grants unused credit.
    carry_debt_ns: u64,
    nr_periods: u64,
    nr_throttled: u64,
    throttled_since_ns: Option<u64>,
    throttled_ns: u64,
}

impl CpuMax {
    /// Preserves Linux's microsecond configuration, including very large quotas.
    ///
    /// An unrepresentable finite quota exceeds every representable nanosecond
    /// interval. Saturating its enforcement threshold is conservative; native
    /// N0 snapshots separately require a finite cap no larger than 100ms.
    fn us_to_ns(us: u64) -> u64 {
        us.saturating_mul(1_000)
    }

    fn period_ns(&self) -> u64 {
        Self::us_to_ns(self.period_usec).max(1)
    }

    /// Compute the periods visible to a cpu.stat observer WITHOUT closing a
    /// quota window. The running task's interval may not have been charged
    /// yet, so an observational read must not call advance() and erase it.
    fn observed_nr_periods(&self, now: u64) -> u64 {
        let period = self.period_ns();
        let start = now / period * period;
        if self.window_start_ns == 0 || start <= self.window_start_ns {
            self.nr_periods
        } else {
            self.nr_periods
                .saturating_add((start - self.window_start_ns) / period)
        }
    }

    fn advance(&mut self, now: u64) {
        self.last_observed_ns = self.last_observed_ns.max(now);
        let period = self.period_ns();
        let start = now / period * period;
        // A stale timestamp must not rewind the accounting window and grant
        // the same CPU quota again. The original BOOTTIME source is monotonic, but the
        // state transition still needs to fail closed on an old observation.
        if start > self.window_start_ns {
            if let Some(since) = self.throttled_since_ns.take() {
                self.throttled_ns = self
                    .throttled_ns
                    .saturating_add(start.max(since).min(now).saturating_sub(since));
            }
            if self.window_start_ns != 0 && start > self.window_start_ns {
                self.nr_periods = self
                    .nr_periods
                    .saturating_add((start - self.window_start_ns) / period);
            }
            // When a 1000Hz tick preempts after a small quota is spent,
            // discarding the overrun on every period would systematically
            // grant another full quota. Repay *positive* debt from elapsed
            // budgets; do not bank unused runtime as transferable credit.
            let elapsed = start.saturating_sub(self.window_start_ns) / period;
            let allowance = if self.quota_usec == u64::MAX {
                u64::MAX
            } else {
                Self::us_to_ns(self.quota_usec).saturating_mul(elapsed)
            };
            self.carry_debt_ns = self
                .carry_debt_ns
                .saturating_add(self.used_ns)
                .saturating_sub(allowance);
            self.window_start_ns = start;
            self.used_ns = 0;
        }
    }

    /// Settle the positive debt of completed windows touched by a runtime
    /// interval. A timer tick may straddle a quota boundary: charging only
    /// the current window loses the CPU time before that boundary.
    ///
    /// This is O(1), even if the scheduler reports an unusually long interval.
    /// Empty periods repay existing debt but do not accumulate positive credit.
    fn debt_after_crossing(&self, from: u64, new_start: u64, period: u64) -> u64 {
        let quota = Self::us_to_ns(self.quota_usec);
        let old_end = self.window_start_ns.saturating_add(period);
        let old_spent = old_end.saturating_sub(from.max(self.window_start_ns));
        let mut debt = self
            .carry_debt_ns
            .saturating_add(self.used_ns)
            .saturating_add(old_spent)
            .saturating_sub(quota);

        // Completed periods after the old window and before the new one.
        let middle_start = old_end;
        let middle_count = new_start.saturating_sub(middle_start) / period;
        if middle_count == 0 {
            return debt;
        }
        // Process completely idle periods before the first execution period.
        let idle_count =
            (from.max(middle_start).saturating_sub(middle_start) / period).min(middle_count);
        debt = debt.saturating_sub(quota.saturating_mul(idle_count));
        let first_active = middle_start.saturating_add(period.saturating_mul(idle_count));
        if first_active == new_start {
            return debt;
        }

        // The first non-idle completed period may contain only a suffix of
        // the interval; all remaining completed periods ran continuously.
        let first_spent = first_active
            .saturating_add(period)
            .saturating_sub(from.max(first_active));
        debt = debt.saturating_add(first_spent).saturating_sub(quota);
        let full_count = new_start.saturating_sub(first_active.saturating_add(period)) / period;
        if period >= quota {
            debt.saturating_add(period.saturating_sub(quota).saturating_mul(full_count))
        } else {
            debt.saturating_sub(quota.saturating_sub(period).saturating_mul(full_count))
        }
    }

    fn charge(&mut self, from: u64, until: u64) {
        if until < from {
            self.accounting_fault = true;
            return;
        }
        let elapsed = until - from;
        if let Some(cumulative) = self.cumulative_ns.checked_add(elapsed) {
            self.cumulative_ns = cumulative;
        } else {
            self.cumulative_ns = u64::MAX;
            self.accounting_fault = true;
        }
        self.last_observed_ns = self.last_observed_ns.max(until);
        let period = self.period_ns();
        let new_start = until / period * period;
        // Never re-open an earlier accounting window on a backward clock.
        if new_start < self.window_start_ns {
            return;
        }

        // Save the true debt from completed periods before the normal advance
        // updates nr_periods/throttled_usec and resets used_ns. This avoids
        // counting older idle periods as transferable positive CPU credit.
        let corrected_debt = if new_start > self.window_start_ns && self.quota_usec != u64::MAX {
            Some(self.debt_after_crossing(from, new_start, period))
        } else {
            None
        };
        self.advance(until);
        if let Some(debt) = corrected_debt {
            self.carry_debt_ns = debt;
        }
        self.used_ns = self
            .used_ns
            .saturating_add(until.saturating_sub(from.max(self.window_start_ns)));
    }

    fn eligible(&mut self, now: u64) -> bool {
        // Different CPUs can reach this shared owner in a different order
        // from their sample capture. Keep the current accounting window and
        // throttling timestamps; an earlier cut cannot rewind either one.
        let now = now.max(self.last_observed_ns);
        if self.accounting_fault {
            // Ordinary unlimited work and local administrative recovery remain
            // available; an unknown interval cannot authorize finite bandwidth.
            return self.quota_usec == u64::MAX;
        }
        self.advance(now);
        if self.quota_usec == u64::MAX
            || self.used_ns.saturating_add(self.carry_debt_ns) < Self::us_to_ns(self.quota_usec)
        {
            if let Some(since) = self.throttled_since_ns.take() {
                self.throttled_ns = self.throttled_ns.saturating_add(now.saturating_sub(since));
            }
            return true;
        }
        if self.throttled_since_ns.is_none() {
            self.nr_throttled = self.nr_throttled.saturating_add(1);
            self.throttled_since_ns = Some(now);
        }
        false
    }

    fn reconfigure(&mut self, quota_usec: u64, period_usec: u64, now: u64) {
        // A cut captured on another CPU may reach this owner after a later
        // observation. Reconfiguration must never reopen the earlier window.
        let now = now.max(self.last_observed_ns);
        self.advance(now);
        let already_used = self.used_ns;
        if period_usec != self.period_usec {
            // The original owner retains already-used CPU through a resize.
            // Its current bucket may consequently contain an incomplete or
            // differently shaped native window. Wait for a whole new N0 window
            // instead of inventing a second fixed-period observation ledger.
            self.native_window_valid_from_ns = (now / CPU_PERIOD_NS)
                .checked_add(1)
                .and_then(|next| next.checked_mul(CPU_PERIOD_NS));
        }
        self.quota_usec = quota_usec;
        self.period_usec = period_usec;
        let period = self.period_ns();
        self.window_start_ns = now / period * period;
        self.used_ns = already_used;
        if quota_usec == u64::MAX {
            if let Some(since) = self.throttled_since_ns.take() {
                self.throttled_ns = self.throttled_ns.saturating_add(now.saturating_sub(since));
            }
        }
    }

    fn throttled_usec(&self, now: u64) -> u64 {
        let nanos = self.throttled_ns.saturating_add(
            self.throttled_since_ns
                .map_or(0, |since| now.saturating_sub(since)),
        );
        nanos / 1_000
    }
}

/// Specifies the cgroup CPU sub-controller receives one [`Jiffies`] of charge.
#[derive(Clone, Copy)]
pub(crate) enum CpuStatKind {
    /// Charges one [`Jiffies`] to `user_usec`.
    User,
    /// Charges one [`Jiffies`] to `system_usec`.
    System,
}

impl CpuController {
    pub(super) fn init_attr_set(builder: &mut SysAttrSetBuilder, is_root: bool) {
        builder.add(SysStr::from("cpu.stat"), SysPerms::DEFAULT_RO_ATTR_PERMS);

        if !is_root {
            builder.add(SysStr::from("cpu.weight"), SysPerms::DEFAULT_RW_ATTR_PERMS);
            builder.add(SysStr::from("cpu.max"), SysPerms::DEFAULT_RW_ATTR_PERMS);
        }
    }

    fn new(is_active: bool) -> Self {
        Self {
            stats: CpuStats::new(),
            control: is_active.then(CpuControl::new),
        }
    }

    /// Initializes CPU usage statistics from the previous sub-controller.
    ///
    /// Toggling `+cpu` must reset some controller attributes such as `cpu.weight`
    /// and `cpu.max`, but `cpu.stat` remains visible and continues to report the
    /// accumulated CPU usage.
    pub(super) fn init_stats(&mut self, previous: &Self) {
        // No one cares which CPU the count is on. Therefore, choose the BSP for simplicity.
        self.stats.user.add_on_cpu(
            CpuId::bsp(),
            isize::try_from(previous.stats.user.sum_all_cpus()).unwrap_or(isize::MAX),
        );
        self.stats.system.add_on_cpu(
            CpuId::bsp(),
            isize::try_from(previous.stats.system.sum_all_cpus()).unwrap_or(isize::MAX),
        );
    }

    fn control(&self) -> Result<&CpuControl> {
        self.control.as_ref().ok_or(Error::AttributeError)
    }

    /// Closes management of this incarnation while retaining deferred CPU debits.
    pub(super) fn close_native_incarnation(&self, _membership: &mut CgroupMembership) {
        if let Some(control) = &self.control {
            control.max.lock().detach();
        }
    }

    fn read_cpu_stat(&self, printer: &mut VmPrinter) -> Result<usize> {
        /// Converts a per-CPU counter expressed in jiffies to microseconds.
        fn counter_usec(counter: &PerCpuCounter) -> u64 {
            let jiffies = u64::try_from(counter.sum_all_cpus()).unwrap_or(u64::MAX);
            u64::try_from(Jiffies::new(jiffies).as_duration().as_micros()).unwrap_or(u64::MAX)
        }

        let user_usec = counter_usec(&self.stats.user);
        let system_usec = counter_usec(&self.stats.system);
        let control_stats = if let Some(control) = &self.control {
            let now = aster_time::try_read_monotonic_sample()
                .and_then(|sample| sample.checked_nanos())
                .ok_or(Error::ResourceUnavailable)?;
            let state = control.max.lock();
            let max = &state.max;
            // A read must not roll a shared cgroup ahead of the running
            // task's pending scheduler CPU charge. In particular, never
            // grant a fresh quota merely by reading cpu.stat.
            Some((
                max.observed_nr_periods(now),
                max.nr_throttled,
                max.throttled_usec(now),
            ))
        } else {
            None
        };

        // User-memory writes can fault and reschedule. Finish collection and
        // release the bandwidth lock before writing any part of the result.
        writeln!(
            printer,
            "usage_usec {}",
            user_usec.saturating_add(system_usec)
        )?;
        writeln!(printer, "user_usec {}", user_usec)?;
        writeln!(printer, "system_usec {}", system_usec)?;
        if let Some((nr_periods, nr_throttled, throttled_usec)) = control_stats {
            writeln!(printer, "nr_periods {}", nr_periods)?;
            writeln!(printer, "nr_throttled {}", nr_throttled)?;
            writeln!(printer, "throttled_usec {}", throttled_usec)?;
            writeln!(printer, "nr_bursts 0")?;
            writeln!(printer, "burst_usec 0")?;
        }

        Ok(printer.bytes_written())
    }

    /// Accounts one [`Jiffies`] of CPU time on `cpu`.
    fn account(&self, cpu: CpuId, stat_kind: CpuStatKind) {
        match stat_kind {
            CpuStatKind::User => self.stats.user.add_on_cpu(cpu, 1),
            CpuStatKind::System => self.stats.system.add_on_cpu(cpu, 1),
        }
    }
}

impl CpuControl {
    fn new() -> Self {
        // The default CPU weight is 100 and the default CPU bandwidth limit is
        // unlimited quota with a 100ms period.
        //
        // Reference: <https://docs.kernel.org/admin-guide/cgroup-v2.html#cpu-interface-files>
        const DEFAULT_WEIGHT: u32 = 100;
        const DEFAULT_QUOTA_USEC: u64 = u64::MAX;
        const DEFAULT_PERIOD_USEC: u64 = 100_000;

        Self {
            weight: AtomicU32::new(DEFAULT_WEIGHT),
            max: SpinLock::new(CpuBandwidthState::new(CpuMax {
                quota_usec: DEFAULT_QUOTA_USEC,
                period_usec: DEFAULT_PERIOD_USEC,
                window_start_ns: 0,
                used_ns: 0,
                cumulative_ns: 0,
                last_observed_ns: 0,
                accounting_fault: false,
                native_window_valid_from_ns: Some(0),
                carry_debt_ns: 0,
                nr_periods: 0,
                nr_throttled: 0,
                throttled_since_ns: None,
                throttled_ns: 0,
            })),
        }
    }
}

impl CpuStats {
    fn new() -> Self {
        Self {
            user: PerCpuCounter::new(),
            system: PerCpuCounter::new(),
        }
    }
}

impl super::SubControl for CpuController {
    fn is_attr_absent(&self, name: &str) -> bool {
        matches!(name, "cpu.weight" | "cpu.max") && self.control.is_none()
    }

    fn read_attr_at(&self, name: &str, offset: usize, writer: &mut VmWriter) -> Result<usize> {
        let mut printer = VmPrinter::new_skip(writer, offset);

        match name {
            "cpu.stat" => return self.read_cpu_stat(&mut printer),
            "cpu.weight" => {
                let weight = self.control()?.weight.load(Ordering::Relaxed);
                writeln!(printer, "{}", weight)?;
            }
            "cpu.max" => {
                let max = self.control()?.max.lock().max;
                if max.quota_usec == u64::MAX {
                    writeln!(printer, "max {}", max.period_usec)?;
                } else {
                    writeln!(printer, "{} {}", max.quota_usec, max.period_usec)?;
                }
            }
            _ => return Err(Error::AttributeError),
        }

        Ok(printer.bytes_written())
    }

    fn write_attr(&self, name: &str, reader: &mut VmReader) -> Result<usize> {
        match name {
            "cpu.weight" => {
                let control = self.control()?;

                // The cgroup v2 CPU weight is a scheduling weight in the range 1..=10000.
                //
                // Reference: <https://docs.kernel.org/admin-guide/cgroup-v2.html#cpu-interface-files>
                const MIN_WEIGHT: u32 = 1;
                const MAX_WEIGHT: u32 = 10_000;

                let (content, len) = reader
                    .read_cstring_until_end(MAX_ATTR_SIZE)
                    .map_err(|_| Error::PageFault)?;
                let weight = content
                    .to_str()
                    .map_err(|_| Error::InvalidOperation)?
                    .trim()
                    .parse::<u32>()
                    .map_err(|_| Error::InvalidOperation)?;
                if !(MIN_WEIGHT..=MAX_WEIGHT).contains(&weight) {
                    return Err(Error::InvalidOperation);
                }

                // TODO: Enforce cgroup CPU weight for scheduling and remove this warning.
                warn!(
                    "`cpu.weight` is accepted but not enforced yet; weight = {}",
                    weight
                );
                control.weight.store(weight, Ordering::Relaxed);

                Ok(len)
            }
            "cpu.max" => {
                let control = self.control()?;

                let (content, len) = reader
                    .read_cstring_until_end(MAX_ATTR_SIZE)
                    .map_err(|_| Error::PageFault)?;
                let content = content
                    .to_str()
                    .map_err(|_| Error::InvalidOperation)?
                    .trim();
                let config = max_config::CpuMaxConfig::parse(content)
                    .map_err(|_| Error::InvalidOperation)?;

                // The local running interval belongs to the old configuration.
                // Lock order: local runqueue -> each original bandwidth owner.
                // The callback and settlement use the same captured timestamp;
                // the budget lock is never held while entering the runqueue.
                crate::sched::with_current_cpu_bandwidth_settled(|now| {
                    control.max.lock().reconfigure_at(config, now)
                })?;

                Ok(len)
            }
            _ => Err(Error::AttributeError),
        }
    }
}

impl super::SubControlStatic for CpuController {
    fn new(is_root: bool, is_active: bool) -> Self {
        Self::new(is_root || is_active)
    }

    fn type_() -> super::SubCtrlType {
        super::SubCtrlType::Cpu
    }

    fn read_from(controller: &super::Controller) -> Arc<super::SubController<Self>> {
        controller.cpu.read().get().clone()
    }
}

impl super::SubController<CpuController> {
    /// Charges one calibrated BOOTTIME interval to the original ancestor chain.
    fn charge_bandwidth_hierarchy(&self, from: u64, until: u64) {
        let mut node = Some(self);
        while let Some(current) = node {
            if let Some(control) = current.inner.as_ref().unwrap().control.as_ref() {
                control.max.lock().max.charge(from, until);
            }
            node = current.parent.as_deref();
        }
    }

    fn invalidate_bandwidth_hierarchy(&self) {
        let mut node = Some(self);
        while let Some(current) = node {
            if let Some(control) = current.inner.as_ref().unwrap().control.as_ref() {
                control.max.lock().max.accounting_fault = true;
            }
            node = current.parent.as_deref();
        }
    }

    fn bandwidth_available_hierarchy(&self, now: Option<u64>) -> bool {
        let serialized = ostd::cpu::all_cpus().count() == 1;
        let mut node = Some(self);
        let mut available = true;
        while let Some(current) = node {
            if let Some(control) = current.inner.as_ref().unwrap().control.as_ref() {
                let mut state = control.max.lock();
                if let Some(now) = now {
                    // A local N0 observer cannot legitimately precede this
                    // owner's last cut. On SMP, capture and lock arrival may
                    // differ; the shared owner keeps its window high-water mark.
                    if serialized && now < state.max.last_observed_ns {
                        state.max.accounting_fault = true;
                    }
                    available &= state.max.eligible(now);
                } else {
                    state.max.accounting_fault = true;
                    available &= state.max.quota_usec == u64::MAX;
                }
            }
            node = current.parent.as_deref();
        }
        available
    }

    fn account_hierarchy(&self, stat_kind: CpuStatKind) {
        // This is race-free because `charge_cpu_time` holds `cgroup_guard` when
        // invoking this method.
        let cpu = CpuId::current_racy();

        let mut current = Some(self);
        while let Some(node) = current {
            node.inner.as_ref().unwrap().account(cpu, stat_kind);
            current = node.parent.as_deref();
        }
    }
}

impl super::Controller {
    /// Charges one [`Jiffies`] in the CPU sub-controller hierarchy.
    fn charge_cpu_time<G: AsAtomicModeGuard + ?Sized>(&self, guard: &G, stat_kind: CpuStatKind) {
        self.cpu.read_with(guard).account_hierarchy(stat_kind);
    }
}

/// Uses the existing cgroup controller for both Linux and future HOS callers.
pub(crate) fn task_cpu_eligible(task: &Task, now: Option<u64>) -> bool {
    let Some(thread) = task.as_posix_thread() else {
        return true;
    };
    let Some(process) = thread.weak_process().upgrade() else {
        // On SMP a POSIX task can still be visible to the scheduler while
        // its Process Arc has already been destroyed. Only an already-exited
        // thread may finish that cleanup without its old cgroup identity.
        return task.as_thread().is_some_and(|thread| thread.is_exited());
    };
    let guard = process.cgroup();
    if let Some(group) = guard.get() {
        group
            .controller()
            .cpu
            .read_with(&guard)
            .bandwidth_available_hierarchy(now)
    } else {
        CgroupSystem::singleton()
            .controller()
            .cpu
            .read_with(&guard)
            .bandwidth_available_hierarchy(now)
    }
}

/// A running segment's reference to the original CPU accounting owner.
///
/// This contains no budget, counter, or native authority. Retaining the actual
/// sub-controller also retains its immutable ancestor chain. A cgroup node
/// alone is insufficient: its RCU slot may publish a different incarnation
/// before the scheduler settles the segment. The node lease keeps rmdir from
/// closing the node while this reference still has an unsettled segment.
pub(crate) struct CpuChargeOwner {
    cpu: Arc<super::SubController<CpuController>>,
    cgroup: Option<Arc<CgroupNode>>,
}

impl CpuChargeOwner {
    /// Captures the live binding for the next segment, without allocation.
    pub(crate) fn for_task(task: &Task) -> Option<Self> {
        let thread = task.as_posix_thread()?;
        // An exiting task can be preempted during kernel cleanup and later
        // resume with a new CurrentRuntime. Preserve its last running owner
        // across that switch, even if its cgroup was detached or replaced.
        if task.as_thread().is_some_and(|thread| thread.is_exited())
            && let Some(owner) = thread.retained_cpu_charge_owner()
        {
            return Some(owner);
        }
        if let Some(process) = thread.weak_process().upgrade() {
            // Read the binding before the zombie flag. A present binding is
            // authoritative even if migration has not updated the backup yet.
            let guard = process.cgroup();
            if guard.get().is_some() || !process.status().is_zombie() {
                let owner = Self::from_cgroup(guard.get().map(|cgroup| cgroup.clone()));
                thread.retain_cpu_charge_owner(owner.clone());
                return Some(owner);
            }
        }

        // The scheduler normally already owns the running segment's exact
        // incarnation before exit. This fallback preserves the existing
        // detached/reaped-task binding for callers capturing an exited task.
        Some(Self::from_cgroup(thread.cpu_cgroup()))
    }

    fn from_cgroup(cgroup: Option<Arc<CgroupNode>>) -> Self {
        let cpu = if let Some(group) = &cgroup {
            group.retain_cpu_charge_lease();
            group.controller().cpu.read().get().clone()
        } else {
            CgroupSystem::singleton()
                .controller()
                .cpu
                .read()
                .get()
                .clone()
        };
        Self { cpu, cgroup }
    }

    pub(crate) fn charge(&self, from: u64, until: u64) {
        // Management closure must not discard CPU time already incurred.
        // In particular, do not look up the node's current RCU incarnation.
        self.cpu.charge_bandwidth_hierarchy(from, until);
    }

    pub(crate) fn invalidate_accounting(&self) {
        self.cpu.invalidate_bandwidth_hierarchy();
    }

    pub(crate) fn belongs_to(&self, cgroup: Option<&Arc<CgroupNode>>) -> bool {
        match (&self.cgroup, cgroup) {
            (Some(old), Some(new)) => Arc::ptr_eq(old, new),
            (None, None) => true,
            _ => false,
        }
    }
}

impl Clone for CpuChargeOwner {
    fn clone(&self) -> Self {
        if let Some(cgroup) = &self.cgroup {
            cgroup.retain_cpu_charge_lease();
        }
        Self {
            cpu: self.cpu.clone(),
            cgroup: self.cgroup.clone(),
        }
    }
}

impl Drop for CpuChargeOwner {
    fn drop(&mut self) {
        if let Some(cgroup) = &self.cgroup {
            cgroup.release_cpu_charge_lease();
        }
    }
}

/// Charges an explicit interval in owner tests without a running class task.
/// Production scheduling retains `CpuChargeOwner` from the segment's start.
#[cfg(ktest)]
fn charge_task_cpu(task: &Task, from: u64, until: u64) {
    if let Some(owner) = CpuChargeOwner::for_task(task) {
        owner.charge(from, until);
    }
}

/// Charges one [`Jiffies`] of CPU time to `process`'s cgroup hierarchy.
///
/// If `process` is not attached to a non-root cgroup, the charge is applied to the root cgroup.
pub(crate) fn charge_cpu_time(process: &Process, stat_kind: CpuStatKind) {
    let cgroup_guard = process.cgroup();

    if let Some(cgroup) = cgroup_guard.get() {
        cgroup
            .controller()
            .charge_cpu_time(&cgroup_guard, stat_kind);
    } else {
        CgroupSystem::singleton()
            .controller()
            .charge_cpu_time(&cgroup_guard, stat_kind);
    }
}

#[cfg(ktest)]
mod config_regressions;

#[cfg(ktest)]
mod final_charge_regressions;

#[cfg(ktest)]
mod bandwidth_settlement_regressions;

#[cfg(ktest)]
mod owner_retention_regressions;

#[cfg(ktest)]
mod scheduler_handoff_regressions;

#[cfg(ktest)]
mod quota_debt_regressions {
    use ostd::prelude::ktest;

    use super::CpuMax;

    fn sample(quota_usec: u64, period_usec: u64, start: u64) -> CpuMax {
        CpuMax {
            quota_usec,
            period_usec,
            window_start_ns: start,
            used_ns: 0,
            cumulative_ns: 0,
            last_observed_ns: 0,
            accounting_fault: false,
            native_window_valid_from_ns: Some(0),
            carry_debt_ns: 0,
            nr_periods: 0,
            nr_throttled: 0,
            throttled_since_ns: None,
            throttled_ns: 0,
        }
    }

    #[ktest]
    fn cpu_stat_projection_must_not_close_unsettled_quota_window() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.nr_periods = 7;
        budget.used_ns = quota.saturating_mul(2);
        budget.throttled_since_ns = Some(start + period / 2);
        let from = start + period - quota / 2;
        let until = start + period + quota / 2;

        // cpu.stat can run while a scheduling interval is not yet charged.
        // Its projected number of periods may change, but it must not
        // mutate used clocks, positive debt, throttling or window origin.
        let before = budget;
        assert_eq!(budget.observed_nr_periods(until), 8);
        assert_eq!(budget.window_start_ns, before.window_start_ns);
        assert_eq!(budget.nr_periods, before.nr_periods);
        assert_eq!(budget.used_ns, before.used_ns);
        assert_eq!(budget.carry_debt_ns, before.carry_debt_ns);
        assert_eq!(budget.throttled_since_ns, before.throttled_since_ns);

        // The later scheduler debit can still account the old-period tail.
        budget.charge(from, until);
        assert_eq!(budget.window_start_ns, start + period);
        assert_eq!(budget.used_ns, quota / 2);
        assert_eq!(budget.carry_debt_ns, quota + quota / 2);
        assert_eq!(budget.nr_periods, 8);
        assert!(!budget.eligible(until));
    }

    #[ktest]
    fn cpu_stat_projection_cannot_rewind_accounting_or_mint_credit() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(4);
        let mut budget = sample(1_000, 100_000, start);
        budget.nr_periods = 9;
        budget.used_ns = quota;
        budget.carry_debt_ns = quota / 2;
        assert_eq!(budget.observed_nr_periods(start - period / 2), 9);
        assert_eq!(budget.observed_nr_periods(start + 3 * period + 1), 12);
        assert_eq!(budget.window_start_ns, start);
        assert_eq!(budget.used_ns, quota);
        assert_eq!(budget.carry_debt_ns, quota / 2);
        // Unlike a statistics read, the real scheduler advances and settles.
        budget.advance(start + 3 * period + 1);
        assert_eq!(budget.nr_periods, 12);
        assert_eq!(budget.carry_debt_ns, 0);
    }

    #[ktest]
    fn overrun_must_carry_then_repay_without_refill() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota.saturating_mul(2);
        budget.advance(start + period);
        assert_eq!(budget.used_ns, 0);
        assert_eq!(budget.carry_debt_ns, quota);
        assert!(!budget.eligible(start + period));
        budget.advance(start + period * 2);
        assert_eq!(budget.carry_debt_ns, 0);
        assert!(budget.eligible(start + period * 2));
    }

    #[ktest]
    fn unused_budget_must_not_accumulate_as_credit() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota / 2;
        budget.advance(start + period);
        assert_eq!(budget.carry_debt_ns, 0);
        budget.used_ns = quota;
        assert!(!budget.eligible(start + period));
    }

    #[ktest]
    fn reconfiguration_in_same_window_must_not_refill() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota;
        budget.carry_debt_ns = quota / 2;
        let now = start + period / 2;
        budget.reconfigure(1_000, 100_000, now);
        assert_eq!(budget.used_ns, quota);
        assert_eq!(budget.carry_debt_ns, quota / 2);
        assert!(!budget.eligible(now));
    }

    #[ktest]
    fn scheduler_runtime_crossing_tick_window_keeps_previous_cpu_charge() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        // A non-preemptible interval extends two quotas before the 100ms
        // boundary, and another quarter quota into the next period.
        budget.charge(start + period - quota * 2, start + period + quota / 4);
        assert_eq!(budget.window_start_ns, start + period);
        assert_eq!(budget.carry_debt_ns, quota);
        assert_eq!(budget.used_ns, quota / 4);
        assert!(!budget.eligible(start + period + quota / 4));
    }

    #[ktest]
    fn crossing_splits_already_charged_and_new_cpu_without_double_count() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota / 2;
        budget.charge(start + period - quota * 3, start + period + quota / 2);
        assert_eq!(budget.carry_debt_ns, quota * 2 + quota / 2);
        assert_eq!(budget.used_ns, quota / 2);
    }

    #[ktest]
    fn idle_skipped_periods_never_subsidize_late_burst() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        let last_completed = start + 6 * period;
        budget.charge(
            last_completed + period / 2,
            last_completed + period + quota / 2,
        );
        assert_eq!(budget.window_start_ns, last_completed + period);
        // A suffix beginning at floor(P/2) contains ceil(P/2) clocks.
        // TSC calibration can make P odd; do not discard its final clock.
        let completed_work = period - period / 2;
        assert_eq!(budget.carry_debt_ns, completed_work - quota);
        assert_eq!(budget.used_ns, quota / 2);
        assert!(!budget.eligible(last_completed + period + quota / 2));
    }

    #[ktest]
    fn long_continuous_interval_has_constant_time_bounded_debt_accounting() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.charge(start + period / 2, start + 5 * period + quota / 2);
        // Count the first suffix by its endpoints, including an odd P's
        // final clock. The following four completed periods were fully busy;
        // no per-period heap work or loop is needed in the production path.
        let completed_work = period - period / 2;
        let expected = completed_work - quota + 4 * (period - quota);
        assert_eq!(budget.carry_debt_ns, expected);
        assert_eq!(budget.used_ns, quota / 2);
    }

    #[ktest]
    fn odd_and_even_completed_periods_preserve_every_clock() {
        let quota = CpuMax::us_to_ns(1_000);
        // The crossing helper takes its period explicitly. Exercise both
        // parities regardless of the host's calibrated TSC frequency, while
        // retaining its real quota conversion and completed-window logic.
        let base_period = quota.checked_mul(4).unwrap();
        for extra_clock in [1, 2] {
            let period = base_period.checked_add(extra_clock).unwrap();
            let start = period.checked_mul(2).unwrap();
            for idle_periods in [0, 6] {
                for full_periods in [0, 4] {
                    let budget = sample(1_000, 100_000, start);
                    let from = start + idle_periods * period + period / 2;
                    let new_start = start + (idle_periods + 1 + full_periods) * period;
                    // Independently integrate each completed window by its
                    // endpoint overlap. Idle budgets must never become credit.
                    let mut expected_debt = 0u64;
                    let mut window = start;
                    while window < new_start {
                        let work = (window + period).saturating_sub(from.max(window));
                        expected_debt = expected_debt.saturating_add(work).saturating_sub(quota);
                        window += period;
                    }
                    assert_eq!(
                        budget.debt_after_crossing(from, new_start, period),
                        expected_debt,
                    );
                }
            }
        }
    }

    #[ktest]
    fn earlier_clock_value_cannot_reopen_or_refill_previous_period() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(4);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota;
        budget.carry_debt_ns = quota / 2;
        budget.advance(start - period / 2);
        budget.charge(start - period / 2, start - 1);
        assert_eq!(budget.window_start_ns, start);
        assert_eq!(budget.used_ns, quota);
        assert_eq!(budget.carry_debt_ns, quota / 2);
        assert!(!budget.eligible(start));
    }

    #[ktest]
    fn charging_500_intervals_matches_simple_period_by_period_reference() {
        // Adversarial reference oracle runs only in ktest; the real scheduler
        // hot path remains O(1) even if multiple windows elapsed between ticks.
        fn next(seed: &mut u64) -> u64 {
            *seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            *seed
        }

        let period = CpuMax::us_to_ns(100_000).max(1);
        let start = period.saturating_mul(2);
        let mut seed = 0xA03A06_A11CEu64;
        for _ in 0..500 {
            let quota_us = 1_000 + next(&mut seed) % 99_001;
            let quota = CpuMax::us_to_ns(quota_us);
            let mut budget = sample(quota_us, 100_000, start);
            let old_used = next(&mut seed) % period;
            let old_debt = next(&mut seed) % period;
            budget.used_ns = old_used;
            budget.carry_debt_ns = old_debt;

            let from = start + (next(&mut seed) % 10) * period + next(&mut seed) % period;
            let until = from + next(&mut seed) % (period * 11);
            let new_start = until / period * period;
            let mut slow_debt = old_debt;
            let mut window = start;
            while window < new_start {
                let work = (window + period)
                    .min(until)
                    .saturating_sub(from.max(window));
                let spent = work + if window == start { old_used } else { 0 };
                slow_debt = slow_debt.saturating_add(spent).saturating_sub(quota);
                window += period;
            }
            let slow_used = if new_start == start {
                old_used.saturating_add(until.saturating_sub(from.max(start)))
            } else {
                until.saturating_sub(from.max(new_start))
            };
            budget.charge(from, until);
            assert_eq!(budget.window_start_ns, new_start);
            assert_eq!(budget.used_ns, slow_used);
            assert_eq!(budget.carry_debt_ns, slow_debt);
        }
    }

    #[ktest]
    fn skipped_periods_pay_down_debt_but_never_mint_credit() {
        let period = CpuMax::us_to_ns(100_000).max(1);
        let quota = CpuMax::us_to_ns(1_000);
        let start = period.saturating_mul(2);
        let mut budget = sample(1_000, 100_000, start);
        budget.used_ns = quota.saturating_mul(3);
        budget.advance(start + period * 4);
        assert_eq!(budget.carry_debt_ns, 0);
        assert_eq!(budget.used_ns, 0);
        budget.used_ns = quota;
        assert!(!budget.eligible(start + period * 4));
    }
}
