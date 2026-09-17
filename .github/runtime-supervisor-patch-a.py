from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(p): return (ROOT / p).read_text()
def write(p, s): (ROOT / p).write_text(s)
def one(s, old, new, label):
    n=s.count(old)
    if n != 1: raise SystemExit(f"{label}: expected 1 occurrence, got {n}")
    return s.replace(old,new,1)

# SupervisorConfig: one bounded policy for main agent and Matrix restart.
p="codex-rs/hepta-supervisor/src/model.rs"; s=read(p)
s=one(s,"    pub stop_grace: Duration,\n    pub event_capacity: usize,","    pub stop_grace: Duration,\n    pub restart_backoff_min: Duration,\n    pub restart_backoff_max: Duration,\n    pub restart_recovery_window: Duration,\n    pub restart_max_attempts: u32,\n    pub event_capacity: usize,","config fields")
s=one(s,"            stop_grace: Duration::from_secs(5),\n            event_capacity: 128,","            stop_grace: Duration::from_secs(5),\n            restart_backoff_min: Duration::from_millis(250),\n            restart_backoff_max: Duration::from_secs(30),\n            restart_recovery_window: Duration::from_secs(300),\n            restart_max_attempts: 3,\n            event_capacity: 128,","config defaults")
s=one(s,"            || self.stop_grace.is_zero()\n            || !(1..=4_096).contains(&self.event_capacity)","            || self.stop_grace.is_zero()\n            || self.restart_backoff_min.is_zero()\n            || self.restart_backoff_max < self.restart_backoff_min\n            || self.restart_recovery_window < self.restart_backoff_min\n            || !(1..=32).contains(&self.restart_max_attempts)\n            || !(1..=4_096).contains(&self.event_capacity)","config validation")
write(p,s)

# Every explicit test config gets deterministic small restart values.
for f in (ROOT/"codex-rs").rglob("*.rs"):
    if f.as_posix().endswith("hepta-supervisor/src/model.rs"): continue
    s=f.read_text()
    if "SupervisorConfig {" not in s: continue
    pat=re.compile(r"(?P<i>^[ \t]+)stop_grace: (?P<v>[^,\n]+),\n(?P=i)event_capacity:",re.M)
    def repl(m):
        i=m.group("i")
        return f"{i}stop_grace: {m.group('v')},\n{i}restart_backoff_min: Duration::from_millis(1),\n{i}restart_backoff_max: Duration::from_millis(8),\n{i}restart_recovery_window: Duration::from_secs(1),\n{i}restart_max_attempts: 3,\n{i}event_capacity:"
    s2,n=pat.subn(repl,s)
    if n: f.write_text(s2)

# Runtime state distinguishes crash-owned exits from explicit termination.
p="codex-rs/hepta-supervisor/src/runtime.rs"; s=read(p)
s=one(s,"    pub healthy: bool,\n    pub fenced: bool,\n}","    pub healthy: bool,\n    pub fenced: bool,\n    pub restart_on_failure: bool,\n}","runtime restart ownership")
s=one(s,"    pub restart_attempt: u32,\n    pub retry_at: Option<Instant>,\n    pub restart_after_exit: bool,","    pub restart_attempt: u32,\n    pub restart_window_started_at: Option<Instant>,\n    pub retry_at: Option<Instant>,\n    pub restart_exhausted: bool,\n    pub restart_after_exit: bool,","matrix restart state")
s=one(s,"            restart_attempt: 0,\n            retry_at: None,\n            restart_after_exit: false,","            restart_attempt: 0,\n            restart_window_started_at: None,\n            retry_at: None,\n            restart_exhausted: false,\n            restart_after_exit: false,","matrix restart init")
s=one(s,"    pub last_command: Option<AgentCommand>,\n    pub restart_pending: bool,\n    pub active_release: Option<AgentRelease>,","    pub last_command: Option<AgentCommand>,\n    pub restart_pending: bool,\n    pub restart_attempt: u32,\n    pub restart_window_started_at: Option<Instant>,\n    pub restart_retry_at: Option<Instant>,\n    pub restart_exhausted: bool,\n    pub active_release: Option<AgentRelease>,","agent restart state")
s=one(s,"            last_command: None,\n            restart_pending: false,\n            active_release: None,","            last_command: None,\n            restart_pending: false,\n            restart_attempt: 0,\n            restart_window_started_at: None,\n            restart_retry_at: None,\n            restart_exhausted: false,\n            active_release: None,","agent restart init")
write(p,s)

# Spawn/adoption default to restart-on-failure for live main children.
p="codex-rs/hepta-supervisor/src/recovery.rs"; s=read(p)
s=one(s,"            healthy: false,\n            fenced: false,\n        });\n        slot.event(starting.generation, SupervisorEventKind::Spawned);","            healthy: false,\n            fenced: false,\n            restart_on_failure: true,\n        });\n        slot.event(starting.generation, SupervisorEventKind::Spawned);","spawn restart flag")
s=one(s,"                    healthy: false,\n                    fenced: false,\n                });\n                slot.event(\n                    record.lifecycle.generation,\n                    SupervisorEventKind::OrphanAdopted,","                    healthy: false,\n                    fenced: false,\n                    restart_on_failure: matches!(\n                        record.lifecycle.lifecycle,\n                        AgentLifecycle::Starting | AgentLifecycle::Running\n                    ),\n                });\n                slot.event(\n                    record.lifecycle.generation,\n                    SupervisorEventKind::OrphanAdopted,","adopt restart flag")
write(p,s)

# Explicit drain/stop/kill owns the exit and suppresses crash restart.
p="codex-rs/hepta-supervisor/src/control.rs"; s=read(p)
s=one(s,"    ) -> Result<(), SupervisorError> {\n        if self.defer_agent_action_for_matrix(\n            agent_id,\n            slot,\n            DeferredAgentActionKind::Drain,","    ) -> Result<(), SupervisorError> {\n        if let Some(runtime) = slot.runtime.as_mut() { runtime.restart_on_failure = false; }\n        if self.defer_agent_action_for_matrix(\n            agent_id,\n            slot,\n            DeferredAgentActionKind::Drain,","drain ownership")
s=s.replace("        slot.restart_pending = false;\n","        slot.restart_pending = false;\n        slot.restart_retry_at = None;\n",2)
s=one(s,"        slot.restart_retry_at = None;\n        if self.defer_agent_action_for_matrix(agent_id, slot, DeferredAgentActionKind::Stop, now)? {","        slot.restart_retry_at = None;\n        if let Some(runtime) = slot.runtime.as_mut() { runtime.restart_on_failure = false; }\n        if self.defer_agent_action_for_matrix(agent_id, slot, DeferredAgentActionKind::Stop, now)? {","stop ownership")
s=one(s,"        slot.restart_retry_at = None;\n        slot.deferred_agent_action = None;","        slot.restart_retry_at = None;\n        if let Some(runtime) = slot.runtime.as_mut() { runtime.restart_on_failure = false; }\n        slot.deferred_agent_action = None;","kill ownership")
write(p,s)

# Main crash recovery: delay + fixed attempt budget per configured window.
p="codex-rs/hepta-supervisor/src/tick.rs"; s=read(p)
old='''    pub(crate) fn tick_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(mut runtime) = slot.runtime.take() {
            let keep = match self.tick_runtime(agent_id, slot, &mut runtime, now) {
                Ok(keep) => keep,
                Err(error) => {
                    slot.runtime = Some(runtime);
                    return Err(error);
                }
            };
            if keep {
                slot.runtime = Some(runtime);
            } else if !self.continue_release_change_after_exit(agent_id, slot, now)?
                && slot.restart_pending
            {
                slot.restart_pending = false;
                let release = slot.active_release.clone().or_else(|| {
                    slot.last_command
                        .clone()
                        .and_then(|command| crate::AgentRelease::unversioned(command).ok())
                });
                let release =
                    release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
                self.start_release_slot(agent_id, slot, release, now)?;
            }
        }
        self.tick_matrix_companion(agent_id, slot, now)
    }
'''
new='''    pub(crate) fn tick_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(mut runtime) = slot.runtime.take() {
            let keep = match self.tick_runtime(agent_id, slot, &mut runtime, now) {
                Ok(keep) => keep,
                Err(error) => {
                    slot.runtime = Some(runtime);
                    return Err(error);
                }
            };
            if keep {
                slot.runtime = Some(runtime);
            } else {
                let restart_on_failure = runtime.restart_on_failure && !runtime.fenced;
                let release_change_continued =
                    self.continue_release_change_after_exit(agent_id, slot, now)?;
                if !release_change_continued
                    && restart_on_failure
                    && !slot.restart_pending
                    && slot.release_change.is_none()
                {
                    self.schedule_automatic_restart(agent_id, slot, now)?;
                }
            }
        }
        self.maybe_start_pending_restart(agent_id, slot, now)?;
        self.tick_matrix_companion(agent_id, slot, now)
    }

    pub(crate) fn reset_restart_budget(&self, slot: &mut AgentSlot<D::Process>) {
        slot.restart_pending = false;
        slot.restart_attempt = 0;
        slot.restart_window_started_at = None;
        slot.restart_retry_at = None;
        slot.restart_exhausted = false;
    }

    fn schedule_automatic_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let expired = slot.restart_window_started_at.is_some_and(|started| {
            now.checked_duration_since(started)
                .is_some_and(|elapsed| elapsed >= self.config.restart_recovery_window)
        });
        if slot.restart_window_started_at.is_none() || expired {
            slot.restart_attempt = 0;
            slot.restart_window_started_at = Some(now);
            slot.restart_exhausted = false;
        }
        let generation = self.record(agent_id)?.lifecycle.generation;
        if slot.restart_attempt >= self.config.restart_max_attempts {
            slot.restart_pending = false;
            slot.restart_retry_at = None;
            slot.restart_exhausted = true;
            slot.event(generation, SupervisorEventKind::DriverFault(format!(
                "automatic restart budget exhausted after {} attempts", slot.restart_attempt
            )));
            return Ok(());
        }
        slot.restart_attempt = slot.restart_attempt.saturating_add(1);
        let shift = slot.restart_attempt.saturating_sub(1).min(31);
        let delay = self.config.restart_backoff_min
            .checked_mul(1_u32 << shift)
            .unwrap_or(self.config.restart_backoff_max)
            .min(self.config.restart_backoff_max);
        slot.restart_pending = true;
        slot.restart_retry_at = Some(deadline(now, delay)?);
        slot.restart_exhausted = false;
        slot.event(generation, SupervisorEventKind::RestartQueued);
        Ok(())
    }

    fn maybe_start_pending_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_some() || !slot.restart_pending { return Ok(()); }
        if slot.restart_retry_at.is_some_and(|retry_at| now < retry_at) { return Ok(()); }
        let automatic = slot.restart_retry_at.is_some();
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command.clone().and_then(|command| crate::AgentRelease::unversioned(command).ok())
        }).ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        slot.restart_pending = false;
        slot.restart_retry_at = None;
        match self.start_release_slot(agent_id, slot, release, now) {
            Ok(()) => Ok(()),
            Err(error) if automatic => {
                self.schedule_automatic_restart(agent_id, slot, now)?;
                Err(error)
            }
            Err(error) => Err(error),
        }
    }
'''
s=one(s,old,new,"tick slot")
write(p,s)

print("patch A staged")
