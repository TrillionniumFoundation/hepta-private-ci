#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:80]!r}")
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    content = read(path)
    start_index = content.find(start)
    if start_index < 0:
        raise SystemExit(f"{path}: missing start marker {start!r}")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{path}: missing end marker {end!r}")
    write(path, content[:start_index] + replacement.rstrip() + "\n\n" + content[end_index:])


# Expose only the internal slot map required by the detached per-Agent owner.
replace_once(
    "codex-rs/hepta-supervisor/src/supervisor.rs",
    "    slots: BTreeMap<AgentId, AgentSlot<D::Process>>,",
    "    pub(crate) slots: BTreeMap<AgentId, AgentSlot<D::Process>>,",
)
replace_once(
    "codex-rs/hepta-supervisor/src/supervisor.rs",
    """    pub(crate) fn record(&self, agent_id: &AgentId) -> Result<AgentRecord, SupervisorError> {
        self.registry
            .load()?
            .agent(agent_id)
            .cloned()
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))
    }
""",
    """    pub(crate) fn record(&self, agent_id: &AgentId) -> Result<AgentRecord, SupervisorError> {
        self.registry.load_agent(agent_id).map_err(Into::into)
    }
""",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod authority_signer;\n",
    "mod agent_shard;\nmod authority_signer;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/unix.rs",
    "/// Unix child wrapper with non-blocking polling and bounded per-child log channels.\npub struct UnixProcessDriver {",
    "/// Unix child wrapper with non-blocking polling and bounded per-child log channels.\n#[derive(Clone)]\npub struct UnixProcessDriver {",
)

write(
    "codex-rs/hepta-supervisor/src/agent_shard.rs",
    r'''//! Detached per-Agent lifecycle ownership.
//!
//! The daemon removes exactly one Agent slot while its effect is running.  The
//! fleet owner lock therefore protects only collect/apply, while the process
//! handle, durable transitions and control protocol execute in the Agent lane.

use std::collections::BTreeMap;

use codex_hepta_contracts::AgentId;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;

pub(crate) struct DetachedAgent<D: ProcessDriver> {
    agent_id: AgentId,
    owner: Supervisor<D>,
    collected_control_revision: u64,
    collected_lifecycle_generation: u64,
}

impl<D: ProcessDriver> DetachedAgent<D> {
    pub(crate) fn owner(&self) -> &Supervisor<D> {
        &self.owner
    }

    pub(crate) fn owner_mut(&mut self) -> &mut Supervisor<D> {
        &mut self.owner
    }
}

impl<D: ProcessDriver + Clone> Supervisor<D> {
    pub(crate) fn detach_agent(
        &mut self,
        agent_id: &AgentId,
    ) -> Result<DetachedAgent<D>, SupervisorError> {
        let record = self.registry.load_agent(agent_id)?;
        let slot = self
            .slots
            .remove(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let collected_control_revision = slot.control_revision;
        let mut slots = BTreeMap::new();
        slots.insert(agent_id.clone(), slot);
        Ok(DetachedAgent {
            agent_id: agent_id.clone(),
            owner: Supervisor {
                registry: self.registry.clone(),
                driver: self.driver.clone(),
                config: self.config.clone(),
                slots,
            },
            collected_control_revision,
            collected_lifecycle_generation: record.lifecycle.generation,
        })
    }

    pub(crate) fn attach_agent(
        &mut self,
        mut detached: DetachedAgent<D>,
    ) -> Result<(), SupervisorError> {
        if self.slots.contains_key(&detached.agent_id) {
            return Err(SupervisorError::Invalid(format!(
                "agent {} already has an attached lifecycle owner",
                detached.agent_id
            )));
        }
        if detached.owner.slots.len() != 1 {
            return Err(SupervisorError::Invalid(
                "detached lifecycle owner must contain exactly one Agent".to_string(),
            ));
        }
        let snapshot = detached
            .owner
            .snapshot(&detached.agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(detached.agent_id.clone()))?;
        if snapshot.control_revision < detached.collected_control_revision {
            return Err(SupervisorError::Invalid(
                "detached lifecycle owner regressed its control revision".to_string(),
            ));
        }
        let record = self.registry.load_agent(&detached.agent_id)?;
        if record.lifecycle.generation < detached.collected_lifecycle_generation {
            return Err(SupervisorError::Invalid(
                "detached lifecycle owner regressed its lifecycle generation".to_string(),
            ));
        }
        let slot = detached
            .owner
            .slots
            .remove(&detached.agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(detached.agent_id.clone()))?;
        self.slots.insert(detached.agent_id, slot);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::time::Instant;

    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::*;
    use crate::AdoptSpec;
    use crate::Adoption;
    use crate::AgentCommand;
    use crate::ManagedProcess;
    use crate::MatrixAdoptSpec;
    use crate::MatrixSpawnSpec;
    use crate::ProcessDriverError;
    use crate::ProcessObservation;
    use crate::SpawnSpec;
    use crate::SpawnedProcess;
    use crate::SupervisorConfig;

    #[derive(Clone)]
    struct Driver;

    struct Process;

    impl ManagedProcess for Process {
        fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
            Err(ProcessDriverError::new("not running"))
        }

        fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn kill(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }
    }

    impl ProcessDriver for Driver {
        type Process = Process;

        fn spawn(
            &mut self,
            _spec: &SpawnSpec,
        ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
            Err(ProcessDriverError::new("not used"))
        }

        fn adopt(
            &mut self,
            _spec: &AdoptSpec,
        ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
            Ok(Adoption::Missing)
        }

        fn spawn_matrixd(
            &mut self,
            _spec: &MatrixSpawnSpec,
        ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
            Err(ProcessDriverError::new("not used"))
        }

        fn adopt_matrixd(
            &mut self,
            _spec: &MatrixAdoptSpec,
        ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
            Ok(Adoption::Missing)
        }
    }

    #[test]
    fn detach_moves_only_the_selected_agent_and_attach_restores_it() {
        let temp = tempfile::tempdir().expect("temporary fleet");
        let root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(root.clone()).expect("registry");
        for (raw, name) in [
            ("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "a"),
            ("019153a4-3088-7e03-a56a-9b1964f75dd3", "b"),
        ] {
            let agent_id = AgentId::parse(raw).expect("agent id");
            let workspace = temp.path().join(name);
            std::fs::create_dir(&workspace).expect("workspace");
            registry
                .register(
                    AgentManifest::new(
                        agent_id,
                        WorkspaceBinding::new(
                            workspace.canonicalize().expect("canonical workspace"),
                            &root,
                        )
                        .expect("binding"),
                        ResourceBudget::local_default(),
                    )
                    .expect("manifest"),
                )
                .expect("register");
        }
        let (mut owner, _) = Supervisor::recover(
            registry,
            Driver,
            SupervisorConfig::local_default(),
            Instant::now(),
        )
        .expect("recover");
        let selected = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .expect("selected id");
        let peer = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").expect("peer id");
        let detached = owner.detach_agent(&selected).expect("detach");
        assert!(owner.snapshot(&selected).is_none());
        assert!(owner.snapshot(&peer).is_some());
        assert!(detached.owner().snapshot(&selected).is_some());
        owner.attach_agent(detached).expect("attach");
        assert!(owner.snapshot(&selected).is_some());
        assert!(owner.snapshot(&peer).is_some());
    }

    #[allow(dead_code)]
    fn command() -> AgentCommand {
        AgentCommand {
            program: PathBuf::from("unused"),
            args: Vec::new(),
        }
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/daemon_read_view.rs",
    r'''//! Immutable, bounded observation cache, not an authority or a mutation input.
//! Every mutation still compares its fence to the live per-Agent owner state.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::RwLock;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;

use super::SupervisorEpoch;
use super::SupervisordAgentStatus;
use super::SupervisordHealth;
use super::SupervisordMethod;
use super::SupervisordPayload;
use super::error_payload;
use super::status_from;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::daemon_protocol::MAX_SUPERVISORD_ROSTER;

const MAX_AGE: Duration = Duration::from_secs(2);

#[derive(Clone)]
struct Observation {
    captured_at: Instant,
    epoch: SupervisorEpoch,
    recovery_required: BTreeMap<AgentId, bool>,
    agents: BTreeMap<AgentId, SupervisordAgentStatus>,
}

#[derive(Default)]
pub(super) struct ReadView {
    current: RwLock<Option<Arc<Observation>>>,
}

impl ReadView {
    /// Startup/full-reconciliation publication. Runtime updates use
    /// `publish_agent`, so no fleet filesystem scan is performed while the
    /// fleet owner lock is held during ordinary operation.
    pub(super) fn publish<D: ProcessDriver>(
        &self,
        registry: &FleetRegistry,
        supervisor: &Supervisor<D>,
        epoch: &SupervisorEpoch,
    ) -> Result<(), SupervisorError> {
        let captured_at = Instant::now();
        let snapshot = registry.load()?;
        if snapshot.agents.len() > usize::from(MAX_SUPERVISORD_ROSTER) {
            return Err(SupervisorError::Invalid(
                "read view exceeds roster limit".to_string(),
            ));
        }
        let mut agents = BTreeMap::new();
        let mut recovery_required = BTreeMap::new();
        for (agent_id, record) in snapshot.agents {
            let status = status_from(epoch, &record, supervisor.snapshot(&agent_id))?;
            recovery_required.insert(
                agent_id.clone(),
                supervisor.production_recovery_required(&agent_id)?,
            );
            agents.insert(agent_id, status);
        }
        self.replace(Observation {
            captured_at,
            epoch: epoch.clone(),
            recovery_required,
            agents,
        })
    }

    pub(super) fn publish_agent(
        &self,
        epoch: &SupervisorEpoch,
        status: SupervisordAgentStatus,
        requires_recovery: bool,
    ) -> Result<(), SupervisorError> {
        let mut current = self.current.write().map_err(|_| {
            SupervisorError::Invalid("supervisord read view is unavailable".to_string())
        })?;
        let mut next = current
            .as_ref()
            .filter(|view| view.epoch == *epoch)
            .map(|view| (**view).clone())
            .unwrap_or_else(|| Observation {
                captured_at: Instant::now(),
                epoch: epoch.clone(),
                recovery_required: BTreeMap::new(),
                agents: BTreeMap::new(),
            });
        next.captured_at = Instant::now();
        next.recovery_required
            .insert(status.agent_id.clone(), requires_recovery);
        next.agents.insert(status.agent_id.clone(), status);
        if next.agents.len() > usize::from(MAX_SUPERVISORD_ROSTER) {
            return Err(SupervisorError::Invalid(
                "read view exceeds roster limit".to_string(),
            ));
        }
        *current = Some(Arc::new(next));
        Ok(())
    }

    fn replace(&self, observation: Observation) -> Result<(), SupervisorError> {
        let mut current = self.current.write().map_err(|_| {
            SupervisorError::Invalid("supervisord read view is unavailable".to_string())
        })?;
        *current = Some(Arc::new(observation));
        Ok(())
    }

    pub(super) fn invalidate(&self) {
        if let Ok(mut current) = self.current.write() {
            *current = None;
        }
    }

    pub(super) fn respond(
        &self,
        method: &SupervisordMethod,
        now: Instant,
        observed_faults: u64,
    ) -> Option<SupervisordPayload> {
        if !matches!(
            method,
            SupervisordMethod::Health
                | SupervisordMethod::Roster { .. }
                | SupervisordMethod::Snapshot { .. }
        ) {
            return None;
        }
        if let SupervisordMethod::Roster { limit } = method
            && !(1..=MAX_SUPERVISORD_ROSTER).contains(limit)
        {
            return Some(error_payload(
                "invalid_frame",
                "invalid roster limit",
                /*actual*/ None,
            ));
        }
        let observation = self.current.read().ok().and_then(|current| current.clone());
        let Some(view) = observation.filter(|view| {
            now.checked_duration_since(view.captured_at)
                .is_some_and(|age| age <= MAX_AGE)
        }) else {
            return Some(unavailable());
        };
        Some(match method {
            SupervisordMethod::Health => SupervisordPayload::Health(SupervisordHealth {
                ready: !view.recovery_required.values().any(|required| *required),
                supervisor_epoch: view.epoch.clone(),
                process_id: std::process::id(),
                registered_agents: view.agents.len() as u16,
                observed_faults,
            }),
            SupervisordMethod::Roster { limit } => SupervisordPayload::Roster {
                agents: view
                    .agents
                    .values()
                    .take(usize::from(*limit))
                    .cloned()
                    .collect(),
            },
            SupervisordMethod::Snapshot { agent_id } => match view.agents.get(agent_id) {
                Some(agent) => SupervisordPayload::Agent(agent.clone()),
                None => error_payload(
                    "unknown_agent",
                    "selected Agent is not registered",
                    /*actual*/ None,
                ),
            },
            SupervisordMethod::ReleaseSelection { .. }
            | SupervisordMethod::ProductionMutationStatus { .. }
            | SupervisordMethod::Start { .. }
            | SupervisordMethod::Drain { .. }
            | SupervisordMethod::Stop { .. }
            | SupervisordMethod::Kill { .. }
            | SupervisordMethod::Restart { .. }
            | SupervisordMethod::Upgrade { .. }
            | SupervisordMethod::Rollback { .. }
            | SupervisordMethod::SignedUpgrade { .. }
            | SupervisordMethod::SignedRollback { .. }
            | SupervisordMethod::ResolveProductionRecovery { .. } => return None,
        })
    }
}

pub(super) fn unavailable() -> SupervisordPayload {
    error_payload(
        "control_state_unavailable",
        "supervisord observation is unavailable or expired; refresh before retry",
        /*actual*/ None,
    )
}

#[cfg(test)]
#[path = "daemon_read_view_tests.rs"]
mod tests;
''',
)

write(
    "codex-rs/hepta-supervisor/src/daemon_execution.rs",
    r'''//! Per-Agent lifecycle admission and bounded blocking execution.
//!
//! A lane serializes one Agent while the global worker semaphore bounds host
//! pressure. Different Agents can execute concurrently; health/roster/snapshot
//! reads remain independent through the immutable read view.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use tokio::runtime::Handle;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::DaemonState;
use super::SupervisordMethod;
use super::SupervisordPayload;
use super::error_payload;
use super::mutex::micros;
use super::read_view::ReadView;
use super::read_view::unavailable;
use crate::UnixProcessDriver;

const LATENCY_BUCKETS: usize = 64;
const WORKER_CAPACITY: usize = 32;
const ADMISSION_TIMEOUT: Duration = Duration::from_millis(250);

struct LatencyHistogram {
    count: AtomicU64,
    buckets: [AtomicU64; LATENCY_BUCKETS],
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct LatencySummary {
    count: u64,
    p50_us: u64,
    p95_us: u64,
    p99_us: u64,
}

impl Default for LatencyHistogram {
    fn default() -> Self {
        Self {
            count: AtomicU64::new(0),
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }
}

impl LatencyHistogram {
    fn record(&self, duration: Duration) {
        let value = micros(duration);
        self.buckets[latency_bucket(value)].fetch_add(1, Ordering::Relaxed);
        self.count.fetch_add(1, Ordering::Release);
    }

    fn snapshot(&self) -> LatencySummary {
        let count = self.count.load(Ordering::Acquire);
        if count == 0 {
            return LatencySummary::default();
        }
        LatencySummary {
            count,
            p50_us: self.percentile(count, 50),
            p95_us: self.percentile(count, 95),
            p99_us: self.percentile(count, 99),
        }
    }

    fn percentile(&self, count: u64, percentile: u64) -> u64 {
        let target = count
            .saturating_mul(percentile)
            .saturating_add(99)
            .saturating_div(100)
            .max(1);
        let mut observed = 0_u64;
        for (index, bucket) in self.buckets.iter().enumerate() {
            observed = observed.saturating_add(bucket.load(Ordering::Relaxed));
            if observed >= target {
                return latency_bucket_upper_bound(index);
            }
        }
        u64::MAX
    }
}

fn latency_bucket(value_us: u64) -> usize {
    if value_us <= 1 {
        return 0;
    }
    usize::try_from(u64::BITS - value_us.leading_zeros())
        .unwrap_or(LATENCY_BUCKETS - 1)
        .min(LATENCY_BUCKETS - 1)
}

fn latency_bucket_upper_bound(index: usize) -> u64 {
    if index == 0 {
        return 1;
    }
    1_u64
        .checked_shl(u32::try_from(index).unwrap_or(u32::MAX))
        .unwrap_or(u64::MAX)
}

#[derive(Default)]
struct AgentLanes {
    lanes: StdMutex<BTreeMap<AgentId, Arc<Semaphore>>>,
}

impl AgentLanes {
    fn lane(&self, agent_id: &AgentId) -> Option<Arc<Semaphore>> {
        let mut lanes = self.lanes.lock().ok()?;
        Some(
            lanes
                .entry(agent_id.clone())
                .or_insert_with(|| Arc::new(Semaphore::new(1)))
                .clone(),
        )
    }

    fn count(&self) -> usize {
        self.lanes.lock().map_or(0, |lanes| lanes.len())
    }
}

pub(super) struct Execution {
    pub(super) view: ReadView,
    lanes: AgentLanes,
    pub(super) slots: Arc<Semaphore>,
    pub(super) poisoned: AtomicBool,
    cancellation: CancellationToken,
    pub(super) rejected: AtomicU64,
    pub(super) completed: AtomicU64,
    tick_skipped: AtomicU64,
    tick_delay_max_us: AtomicU64,
    inflight_agents: AtomicU64,
    lane_wait: LatencyHistogram,
    worker_wait: LatencyHistogram,
    owner_total: LatencyHistogram,
    read_total: LatencyHistogram,
    started: Instant,
    last_log_second: AtomicU64,
}

impl Execution {
    pub(super) fn new(cancellation: CancellationToken) -> Self {
        Self {
            view: ReadView::default(),
            lanes: AgentLanes::default(),
            slots: Arc::new(Semaphore::new(WORKER_CAPACITY)),
            poisoned: AtomicBool::new(false),
            cancellation,
            rejected: AtomicU64::new(0),
            completed: AtomicU64::new(0),
            tick_skipped: AtomicU64::new(0),
            tick_delay_max_us: AtomicU64::new(0),
            inflight_agents: AtomicU64::new(0),
            lane_wait: LatencyHistogram::default(),
            worker_wait: LatencyHistogram::default(),
            owner_total: LatencyHistogram::default(),
            read_total: LatencyHistogram::default(),
            started: Instant::now(),
            last_log_second: AtomicU64::new(0),
        }
    }

    pub(super) fn failed(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    fn stopped(&self) -> bool {
        self.poisoned.load(Ordering::Acquire) || self.cancellation.is_cancelled()
    }

    pub(super) fn poison(&self) {
        self.poisoned.store(true, Ordering::Release);
        self.view.invalidate();
        self.cancellation.cancel();
    }

    pub(super) fn agent_started(&self) {
        self.inflight_agents.fetch_add(1, Ordering::AcqRel);
    }

    pub(super) fn agent_finished(&self) {
        let previous = self.inflight_agents.fetch_sub(1, Ordering::AcqRel);
        if previous == 0 {
            self.poison();
        }
    }

    fn log_snapshot(&self) {
        let lane = self.lane_wait.snapshot();
        let worker = self.worker_wait.snapshot();
        let total = self.owner_total.snapshot();
        let read = self.read_total.snapshot();
        eprintln!(
            "hepta_supervisord_latency lane_count={} lane_p50_us={} lane_p95_us={} lane_p99_us={} worker_count={} worker_p50_us={} worker_p95_us={} worker_p99_us={} owner_count={} owner_p50_us={} owner_p95_us={} owner_p99_us={} read_count={} read_p50_us={} read_p95_us={} read_p99_us={}",
            lane.count,
            lane.p50_us,
            lane.p95_us,
            lane.p99_us,
            worker.count,
            worker.p50_us,
            worker.p95_us,
            worker.p99_us,
            total.count,
            total.p50_us,
            total.p95_us,
            total.p99_us,
            read.count,
            read.p50_us,
            read.p95_us,
            read.p99_us,
        );
    }
}

struct OwnerWork {
    state: Arc<DaemonState<UnixProcessDriver>>,
    _lane: OwnedSemaphorePermit,
    _worker: OwnedSemaphorePermit,
}

impl Drop for OwnerWork {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.state.execution.poison();
        }
        self.state.execution.completed.fetch_add(1, Ordering::Relaxed);
    }
}

fn spawn_owned<R, F>(
    state: Arc<DaemonState<UnixProcessDriver>>,
    lane: OwnedSemaphorePermit,
    worker: OwnedSemaphorePermit,
    work: F,
) -> JoinHandle<Option<R>>
where
    R: Send + 'static,
    F: FnOnce(&Arc<DaemonState<UnixProcessDriver>>) -> R + Send + 'static,
{
    let owner = OwnerWork {
        state,
        _lane: lane,
        _worker: worker,
    };
    tokio::task::spawn_blocking(move || {
        if owner.state.execution.stopped() {
            return None;
        }
        Some(work(&owner.state))
    })
}

fn method_agent_id(method: &SupervisordMethod) -> Option<&AgentId> {
    match method {
        SupervisordMethod::Snapshot { agent_id }
        | SupervisordMethod::ReleaseSelection { agent_id }
        | SupervisordMethod::ProductionMutationStatus { agent_id } => Some(agent_id),
        SupervisordMethod::Start { fence, .. }
        | SupervisordMethod::Drain { fence }
        | SupervisordMethod::Stop { fence }
        | SupervisordMethod::Kill { fence }
        | SupervisordMethod::Restart { fence }
        | SupervisordMethod::Upgrade { fence, .. }
        | SupervisordMethod::Rollback { fence }
        | SupervisordMethod::SignedUpgrade { fence, .. }
        | SupervisordMethod::SignedRollback { fence, .. }
        | SupervisordMethod::ResolveProductionRecovery { fence, .. } => Some(&fence.agent_id),
        SupervisordMethod::Health | SupervisordMethod::Roster { .. } => None,
    }
}

pub(super) async fn handle(
    state: Arc<DaemonState<UnixProcessDriver>>,
    method: SupervisordMethod,
) -> SupervisordPayload {
    let request_started = Instant::now();
    if state.execution.stopped() {
        return unavailable();
    }
    if let Some(reply) = state.execution.view.respond(
        &method,
        Instant::now(),
        state.observed_faults.load(Ordering::Relaxed),
    ) {
        state.execution.read_total.record(request_started.elapsed());
        return reply;
    }
    let Some(agent_id) = method_agent_id(&method).cloned() else {
        return unavailable();
    };
    let Some(lane) = state.execution.lanes.lane(&agent_id) else {
        state.execution.poison();
        return unavailable();
    };
    let lane_started = Instant::now();
    let lane_permit = tokio::select! {
        _ = state.execution.cancellation.cancelled() => return unavailable(),
        result = timeout(ADMISSION_TIMEOUT, lane.acquire_owned()) => match result {
            Ok(Ok(permit)) => permit,
            _ => {
                state.execution.lane_wait.record(lane_started.elapsed());
                state.execution.owner_total.record(request_started.elapsed());
                state.execution.rejected.fetch_add(1, Ordering::Relaxed);
                return error_payload(
                    "control_state_unavailable",
                    "selected Agent is busy; no operation was admitted; refresh before retry",
                    None,
                );
            }
        },
    };
    state.execution.lane_wait.record(lane_started.elapsed());

    let worker_started = Instant::now();
    let worker_permit = tokio::select! {
        _ = state.execution.cancellation.cancelled() => return unavailable(),
        result = timeout(ADMISSION_TIMEOUT, Arc::clone(&state.execution.slots).acquire_owned()) => match result {
            Ok(Ok(permit)) => permit,
            _ => {
                state.execution.worker_wait.record(worker_started.elapsed());
                state.execution.owner_total.record(request_started.elapsed());
                state.execution.rejected.fetch_add(1, Ordering::Relaxed);
                return error_payload(
                    "control_state_unavailable",
                    "lifecycle worker capacity is busy; no operation was admitted; retry later",
                    None,
                );
            }
        },
    };
    state.execution.worker_wait.record(worker_started.elapsed());

    let runtime = Handle::current();
    let metrics_state = Arc::clone(&state);
    let outcome = spawn_owned(state, lane_permit, worker_permit, move |state| {
        runtime.block_on(super::handle_request(Arc::clone(state), method))
    })
    .await;
    metrics_state
        .execution
        .owner_total
        .record(request_started.elapsed());
    match outcome {
        Ok(Some(reply)) => reply,
        Ok(None) => unavailable(),
        Err(_) => error_payload(
            "operation_indeterminate",
            "lifecycle worker failed; inspect durable state before retry",
            None,
        ),
    }
}

pub(super) async fn tick(state: Arc<DaemonState<UnixProcessDriver>>, scheduled: Instant) {
    if state.execution.stopped() {
        return;
    }
    state.execution.tick_delay_max_us.fetch_max(
        micros(Instant::now().saturating_duration_since(scheduled)),
        Ordering::Relaxed,
    );
    let agent_ids = {
        let supervisor = state.supervisor.lock().await;
        supervisor.agent_ids()
    };
    let mut jobs = Vec::with_capacity(agent_ids.len().min(WORKER_CAPACITY));
    for agent_id in agent_ids {
        let Some(lane) = state.execution.lanes.lane(&agent_id) else {
            state.execution.poison();
            return;
        };
        let Ok(lane_permit) = lane.try_acquire_owned() else {
            state.execution.tick_skipped.fetch_add(1, Ordering::Relaxed);
            continue;
        };
        let Ok(worker_permit) = Arc::clone(&state.execution.slots).try_acquire_owned() else {
            state.execution.tick_skipped.fetch_add(1, Ordering::Relaxed);
            continue;
        };
        let runtime = Handle::current();
        let task_state = Arc::clone(&state);
        jobs.push(spawn_owned(
            task_state,
            lane_permit,
            worker_permit,
            move |state| {
                runtime.block_on(super::with_agent_owner(
                    Arc::clone(state),
                    agent_id,
                    |supervisor| supervisor.tick(Instant::now()).faults.len(),
                ))
            },
        ));
    }
    for job in jobs {
        match job.await {
            Ok(Some(Ok(faults))) => {
                state
                    .observed_faults
                    .fetch_add(faults as u64, Ordering::Relaxed);
            }
            Ok(Some(Err(error))) => {
                state.observed_faults.fetch_add(1, Ordering::Relaxed);
                eprintln!("hepta_supervisord_tick agent_owner_error={error}");
            }
            Ok(None) => {}
            Err(_) => state.execution.poison(),
        }
    }

    let execution = &state.execution;
    let second = execution.started.elapsed().as_secs();
    let previous = execution.last_log_second.load(Ordering::Relaxed);
    let log_now = second.saturating_sub(previous) >= 5
        && execution
            .last_log_second
            .compare_exchange(previous, second, Ordering::Relaxed, Ordering::Relaxed)
            .is_ok();
    if log_now {
        let operational = {
            let supervisor = state.supervisor.lock().await;
            supervisor.operational_summary()
        };
        state.supervisor.log_snapshot();
        execution.log_snapshot();
        crate::control_latency::log_snapshot();
        match operational {
            Ok(summary) => eprintln!(
                "hepta_supervisord_progress registered_agents={} blocked_agents={} target_identity_changed={} awaiting_process_exit={} restart_backoff={} restart_budget_exhausted={} release_transition_in_progress={} persistence_uncertain={} recovery_quarantined={} control_state_unavailable={} resource_enforcement_gaps={}",
                summary.registered_agents,
                summary.blocked_agents,
                summary.target_identity_changed,
                summary.awaiting_process_exit,
                summary.restart_backoff,
                summary.restart_budget_exhausted,
                summary.release_transition_in_progress,
                summary.persistence_uncertain,
                summary.recovery_quarantined,
                summary.control_state_unavailable,
                summary.resource_enforcement_gaps,
            ),
            Err(_) => {
                state.observed_faults.fetch_add(1, Ordering::Relaxed);
                eprintln!("hepta_supervisord_progress unavailable=1");
            }
        }
        eprintln!(
            "hepta_supervisord_scheduler completed={} rejected_busy={} tick_skipped={} tick_delay_max_us={} agent_lanes={} inflight_agents={} worker_available={}",
            execution.completed.load(Ordering::Relaxed),
            execution.rejected.load(Ordering::Relaxed),
            execution.tick_skipped.load(Ordering::Relaxed),
            execution.tick_delay_max_us.load(Ordering::Relaxed),
            execution.lanes.count(),
            execution.inflight_agents.load(Ordering::Relaxed),
            execution.slots.available_permits(),
        );
    }
}

pub(super) fn refresh(
    state: &DaemonState<UnixProcessDriver>,
    supervisor: &crate::Supervisor<UnixProcessDriver>,
) {
    if state
        .execution
        .view
        .publish(&state.registry, supervisor, &state.supervisor_epoch)
        .is_err()
    {
        state.execution.view.invalidate();
        state.observed_faults.fetch_add(1, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod latency_tests {
    use super::*;

    #[test]
    fn histogram_reports_monotone_percentile_upper_bounds() {
        let histogram = LatencyHistogram::default();
        for value in [1_u64, 2, 4, 8, 16, 32, 64, 128, 256, 512] {
            histogram.record(Duration::from_micros(value));
        }
        let summary = histogram.snapshot();
        assert_eq!(summary.count, 10);
        assert!(summary.p50_us <= summary.p95_us);
        assert!(summary.p95_us <= summary.p99_us);
        assert!(summary.p99_us >= 512);
    }
}

#[cfg(test)]
#[path = "daemon_execution_tests.rs"]
mod tests;
''',
)

write(
    "codex-rs/hepta-supervisor/src/daemon_execution_tests.rs",
    r'''use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use pretty_assertions::assert_eq;
use tokio::time::timeout;

use super::super::shutdown_tests::Fixture;
use super::*;

fn agent(raw: &str) -> AgentId {
    AgentId::parse(raw).expect("fixed AgentId")
}

#[tokio::test(flavor = "current_thread")]
async fn different_agent_lanes_admit_independently() -> Result<()> {
    let lanes = AgentLanes::default();
    let first = lanes
        .lane(&agent("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"))
        .expect("first lane");
    let second = lanes
        .lane(&agent("019153a4-3088-7e03-a56a-9b1964f75dd3"))
        .expect("second lane");
    let _first = first.try_acquire_owned()?;
    let _second = second.try_acquire_owned()?;
    assert_eq!(lanes.count(), 2);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn same_agent_lane_serializes_without_consuming_worker_capacity() -> Result<()> {
    let fixture = Fixture::new()?;
    let state = &fixture.state;
    let selected = agent("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12");
    let lane = state.execution.lanes.lane(&selected).expect("lane");
    let busy = Arc::clone(&lane).try_acquire_owned()?;
    let available = state.execution.slots.available_permits();
    let response = handle(
        Arc::clone(state),
        SupervisordMethod::ProductionMutationStatus {
            agent_id: selected,
        },
    )
    .await;
    assert!(matches!(
        response,
        SupervisordPayload::Error { ref code, .. } if code == "control_state_unavailable"
    ));
    assert_eq!(state.execution.slots.available_permits(), available);
    drop(busy);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn owner_panic_poison_cancels_daemon_and_prevents_successor_work() -> Result<()> {
    let fixture = Fixture::new()?;
    let state = &fixture.state;
    let selected = agent("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12");
    let lane = state.execution.lanes.lane(&selected).expect("lane");
    let lane_permit = lane.try_acquire_owned()?;
    let worker = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let failed = spawn_owned(Arc::clone(state), lane_permit, worker, |_| -> () {
        panic!("injected owner panic")
    })
    .await;
    assert!(failed.expect_err("injected panic").is_panic());
    assert!(state.execution.poisoned.load(Ordering::Acquire));
    assert!(fixture.cancellation.is_cancelled());
    assert!(matches!(
        handle(Arc::clone(state), SupervisordMethod::Health).await,
        SupervisordPayload::Error { .. }
    ));
    let invoked = Arc::new(AtomicBool::new(false));
    let called = Arc::clone(&invoked);
    let lane = state.execution.lanes.lane(&selected).expect("lane");
    let lane_permit = lane.try_acquire_owned()?;
    let worker = Arc::clone(&state.execution.slots).try_acquire_owned()?;
    let result = spawn_owned(Arc::clone(state), lane_permit, worker, move |_| {
        called.store(true, Ordering::Release);
    })
    .await?;
    assert_eq!(result, None);
    assert!(!invoked.load(Ordering::Acquire));
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn cancellation_prevents_new_tick_work() -> Result<()> {
    let fixture = Fixture::new()?;
    fixture.cancellation.cancel();
    timeout(
        Duration::from_secs(1),
        tick(Arc::clone(&fixture.state), Instant::now()),
    )
    .await?;
    assert_eq!(fixture.state.execution.completed.load(Ordering::Relaxed), 0);
    Ok(())
}
''',
)

# Daemon generic bounds and per-Agent collect/effect/apply helper.
for old, new in [
    ("struct DaemonState<D: ProcessDriver> {", "struct DaemonState<D: ProcessDriver + Clone> {"),
    ("async fn handle_request<D: ProcessDriver>(", "async fn handle_request<D: ProcessDriver + Clone>("),
    ("async fn resolve_release_outside_lock<D: ProcessDriver>(", "async fn resolve_release_outside_lock<D: ProcessDriver + Clone>("),
    ("async fn agent_status<D: ProcessDriver>(", "async fn agent_status<D: ProcessDriver + Clone>("),
    ("fn agent_status_locked<D: ProcessDriver>(", "fn agent_status_locked<D: ProcessDriver + Clone>("),
]:
    replace_once("codex-rs/hepta-supervisor/src/daemon.rs", old, new)

helper = r'''#[cfg(unix)]
async fn with_agent_owner<D, R>(
    state: Arc<DaemonState<D>>,
    agent_id: AgentId,
    operation: impl FnOnce(&mut Supervisor<D>) -> R,
) -> Result<R, SupervisorError>
where
    D: ProcessDriver + Clone,
{
    let mut detached = {
        let mut fleet = state.supervisor.lock().await;
        fleet.detach_agent(&agent_id)?
    };
    state.execution.agent_started();
    let result = operation(detached.owner_mut());
    let observation = (|| {
        let record = state.registry.load_agent(&agent_id)?;
        let snapshot = detached.owner().snapshot(&agent_id);
        let status = status_from(&state.supervisor_epoch, &record, snapshot)?;
        let recovery_required = detached.owner().production_recovery_required(&agent_id)?;
        Ok::<_, SupervisorError>((status, recovery_required))
    })();
    let attach = {
        let mut fleet = state.supervisor.lock().await;
        fleet.attach_agent(detached)
    };
    state.execution.agent_finished();
    if let Err(error) = attach {
        state.execution.poison();
        return Err(error);
    }
    match observation {
        Ok((status, recovery_required)) => {
            if state
                .execution
                .view
                .publish_agent(
                    &state.supervisor_epoch,
                    status,
                    recovery_required,
                )
                .is_err()
            {
                state.execution.view.invalidate();
                state.observed_faults.fetch_add(1, Ordering::Relaxed);
            }
        }
        Err(_) => {
            state.execution.view.invalidate();
            state.observed_faults.fetch_add(1, Ordering::Relaxed);
        }
    }
    Ok(result)
}
'''
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nasync fn handle_recovery_resolution<D: ProcessDriver>(",
    helper + "\n#[cfg(unix)]\nasync fn handle_recovery_resolution<D: ProcessDriver + Clone>(",
)

recovery = r'''#[cfg(unix)]
async fn handle_recovery_resolution<D: ProcessDriver + Clone>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
    decision: ProductionRecoveryDecision,
) -> SupervisordPayload {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery is disabled in this build",
            None,
        );
    }
    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery requires an externally pinned verifier",
            None,
        );
    };
    let agent_id = fence.agent_id.clone();
    match with_agent_owner(Arc::clone(&state), agent_id.clone(), move |supervisor| {
        let actual = match agent_status_locked(&state, supervisor, &agent_id) {
            Ok(actual) => actual,
            Err(error) => return safe_rejection(error, None, false),
        };
        if !control_fence_matches(&fence, &actual.control_fence) {
            return error_payload(
                "stale_control_fence",
                "selected Agent changed; refresh before recovery",
                Some(actual),
            );
        }
        let authority_epoch =
            authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str());
        if let Err(error) = supervisor.resolve_production_recovery(
            &agent_id,
            &decision,
            &verifier,
            authority_epoch,
            unix_seconds_now(),
        ) {
            let post = agent_status_locked(&state, supervisor, &agent_id).ok();
            return safe_rejection(error, post.or(Some(actual)), false);
        }
        match supervisor.production_mutation_state(&agent_id) {
            Ok(state) => SupervisordPayload::ProductionMutationStatus { state },
            Err(error) => safe_rejection(error, Some(actual), true),
        }
    })
    .await
    {
        Ok(payload) => payload,
        Err(error) => safe_rejection(error, None, false),
    }
}
'''
replace_between(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nasync fn handle_recovery_resolution",
    "#[cfg(unix)]\nasync fn handle_signed_mutation",
    recovery,
)

signed = r'''#[cfg(unix)]
async fn handle_signed_mutation<D: ProcessDriver + Clone>(
    state: Arc<DaemonState<D>>,
    transition: H7H89ProductionTransition,
    fence: SupervisordControlFence,
    grant: H7H89ProductionGrant,
    h7_envelope: codex_hepta_memory::H7SignedArtifactEnvelope,
) -> SupervisordPayload {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations are disabled in this build",
            None,
        );
    }
    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations require an externally pinned verifier",
            None,
        );
    };
    if grant.transition != transition {
        return error_payload(
            "production_authority_rejected",
            "signed operation transition does not match the requested RPC method",
            None,
        );
    }
    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    match with_agent_owner(Arc::clone(&state), agent_id.clone(), move |supervisor| {
        let actual = match agent_status_locked(&state, supervisor, &agent_id) {
            Ok(actual) => actual,
            Err(error) => return safe_rejection(error, None, false),
        };
        if !control_fence_matches(&fence, &actual.control_fence) {
            return error_payload(
                "stale_control_fence",
                "selected Agent changed; refresh before retry",
                Some(actual),
            );
        }
        match supervisor.production_recovery_required(&agent_id) {
            Ok(true) => {
                return error_payload(
                    "signed_intent_recovery_required",
                    "resolve the quarantined production mutation before admitting another signed transition",
                    Some(actual),
                );
            }
            Ok(false) => {}
            Err(error) => return safe_rejection(error, Some(actual), false),
        }
        let authority_epoch =
            authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str());
        let receipt = match supervisor.apply_production_grant(
            &agent_id,
            &grant,
            &h7_envelope,
            &verifier,
            authority_epoch,
            unix_seconds_now(),
            Instant::now(),
        ) {
            Ok(receipt) => receipt,
            Err(error) => {
                let post = agent_status_locked(&state, supervisor, &agent_id).ok();
                return safe_rejection(error, post.or(Some(actual)), false);
            }
        };
        let Some(agent) = agent_status_locked(&state, supervisor, &agent_id).ok() else {
            return error_payload(
                "operation_indeterminate",
                "signed operation outcome is indeterminate; refresh before retry",
                None,
            );
        };
        SupervisordPayload::MutationAccepted {
            operation: match transition {
                H7H89ProductionTransition::Upgrade => SupervisordMutation::Upgrade,
                H7H89ProductionTransition::Rollback => SupervisordMutation::Rollback,
            },
            accepted_state_digest,
            agent,
            production_receipt: Some(receipt),
        }
    })
    .await
    {
        Ok(payload) => payload,
        Err(error) => safe_rejection(error, None, false),
    }
}
'''
replace_between(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nasync fn handle_signed_mutation",
    "#[cfg(unix)]\nfn unix_seconds_now",
    signed,
)

mutation = r'''#[cfg(unix)]
async fn handle_mutation<D: ProcessDriver + Clone>(
    state: Arc<DaemonState<D>>,
    operation: SupervisordMutation,
    fence: SupervisordControlFence,
    target: Option<AgentRelease>,
) -> SupervisordPayload {
    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    match with_agent_owner(Arc::clone(&state), agent_id.clone(), move |supervisor| {
        let actual = match agent_status_locked(&state, supervisor, &agent_id) {
            Ok(actual) => actual,
            Err(error) => return safe_rejection(error, None, false),
        };
        if !control_fence_matches(&fence, &actual.control_fence) {
            return error_payload(
                "stale_control_fence",
                "selected Agent changed; refresh before retry",
                Some(actual),
            );
        }
        match supervisor.production_recovery_required(&agent_id) {
            Ok(true) if operation != SupervisordMutation::Kill => {
                return error_payload(
                    "signed_intent_recovery_required",
                    "this Agent has a quarantined production mutation; only status, recovery, or emergency kill is allowed",
                    Some(actual),
                );
            }
            Ok(_) => {}
            Err(error) => return safe_rejection(error, Some(actual), false),
        }
        if state.production_grant_verifier.is_some()
            && matches!(
                operation,
                SupervisordMutation::Upgrade | SupervisordMutation::Rollback
            )
        {
            return error_payload(
                "signed_release_authority_required",
                "production mode requires SignedUpgrade or SignedRollback for release transitions",
                Some(actual),
            );
        }

        let prepared = match (operation, target) {
            (SupervisordMutation::Start, Some(target)) => PreparedMutation::Start(target),
            (SupervisordMutation::Drain, None) => PreparedMutation::Drain,
            (SupervisordMutation::Stop, None) => PreparedMutation::Stop,
            (SupervisordMutation::Kill, None) => PreparedMutation::Kill,
            (SupervisordMutation::Restart, None) => PreparedMutation::Restart,
            (SupervisordMutation::Upgrade, Some(target)) => PreparedMutation::Upgrade(target),
            (SupervisordMutation::Rollback, None) => PreparedMutation::Rollback,
            (SupervisordMutation::Start | SupervisordMutation::Upgrade, None) => {
                return error_payload(
                    "invalid_frame",
                    "request is not valid supervisord control JSON",
                    Some(actual),
                );
            }
            (
                SupervisordMutation::Drain
                | SupervisordMutation::Stop
                | SupervisordMutation::Kill
                | SupervisordMutation::Restart
                | SupervisordMutation::Rollback,
                Some(_),
            ) => {
                return error_payload(
                    "invalid_frame",
                    "request is not valid supervisord control JSON",
                    Some(actual),
                );
            }
        };
        let preflight = match &prepared {
            PreparedMutation::Start(_) => supervisor.preflight_start(&agent_id),
            PreparedMutation::Drain => supervisor.preflight_drain(&agent_id),
            PreparedMutation::Stop | PreparedMutation::Kill => {
                supervisor.preflight_stop_or_kill(&agent_id)
            }
            PreparedMutation::Restart => supervisor.preflight_restart(&agent_id),
            PreparedMutation::Upgrade(target) => supervisor.preflight_upgrade(&agent_id, target),
            PreparedMutation::Rollback => supervisor.preflight_rollback(&agent_id),
        };
        if let Err(error) = preflight {
            let refreshed = agent_status_locked(&state, supervisor, &agent_id).ok();
            return safe_rejection(error, refreshed.or(Some(actual)), false);
        }
        let next_revision = match supervisor.next_control_revision(&agent_id) {
            Ok(revision) => revision,
            Err(error) => return safe_rejection(error, Some(actual), false),
        };
        if let Err(error) = supervisor.set_control_revision(&agent_id, next_revision) {
            return safe_rejection(error, Some(actual), false);
        }
        let mutation = match prepared {
            PreparedMutation::Start(target) => {
                supervisor.start_release(&agent_id, target, Instant::now())
            }
            PreparedMutation::Drain => supervisor.drain(&agent_id, Instant::now()),
            PreparedMutation::Stop => supervisor.stop(&agent_id, Instant::now()),
            PreparedMutation::Kill => supervisor.kill(&agent_id),
            PreparedMutation::Restart => supervisor.restart(&agent_id, Instant::now()),
            PreparedMutation::Upgrade(target) => {
                supervisor.upgrade(&agent_id, target, Instant::now())
            }
            PreparedMutation::Rollback => supervisor.rollback(&agent_id, Instant::now()),
        };
        let post = agent_status_locked(&state, supervisor, &agent_id).ok();
        if let Err(error) = mutation {
            let audit_started = Instant::now();
            let disposition =
                error.control_failure_disposition(ControlEffectBoundary::EffectAttempted);
            eprintln!(
                "hepta_supervisord_control_audit operation={operation:?} agent_id={agent_id} control_revision={next_revision} outcome=rejected class={:?} next_action={:?}",
                disposition.class, disposition.next_action,
            );
            crate::control_latency::record_stage(
                latency_operation_for_mutation(&operation),
                crate::control_latency::ControlLatencyStage::AuditPublication,
                audit_started.elapsed(),
            );
            return safe_rejection(error, post, true);
        }
        let Some(agent) = post else {
            return error_payload(
                "operation_indeterminate",
                "operation outcome is indeterminate; refresh before retry",
                None,
            );
        };
        let audit_started = Instant::now();
        eprintln!(
            "hepta_supervisord_control_audit operation={operation:?} agent_id={agent_id} control_revision={next_revision} outcome=accepted",
        );
        crate::control_latency::record_stage(
            latency_operation_for_mutation(&operation),
            crate::control_latency::ControlLatencyStage::AuditPublication,
            audit_started.elapsed(),
        );
        SupervisordPayload::MutationAccepted {
            operation,
            accepted_state_digest,
            agent,
            production_receipt: None,
        }
    })
    .await
    {
        Ok(payload) => payload,
        Err(error) => safe_rejection(error, None, false),
    }
}
'''
replace_between(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nasync fn handle_mutation",
    "#[cfg(unix)]\nfn latency_operation_for_mutation",
    mutation,
)

replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    """    let record = state
        .registry
        .load()?
        .agent(agent_id)
        .cloned()
        .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
""",
    "    let record = state.registry.load_agent(agent_id)?;\n",
)

print("runtime.supervisor per-Agent concurrency materialized")
