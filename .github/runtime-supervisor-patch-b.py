from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def write(p,s): (ROOT/p).write_text(s)
def one(s,old,new,label):
    n=s.count(old)
    if n != 1: raise SystemExit(f"{label}: expected 1 occurrence, got {n}")
    return s.replace(old,new,1)

# Matrix: same fixed recovery-window budget; no infinite retries.
p="codex-rs/hepta-supervisor/src/matrix.rs"; s=read(p)
s=s.replace("                        slot.matrix.degraded = false;\n                        slot.matrix.restart_attempt = 0;\n                        slot.matrix.retry_at = None;\n                        slot.matrix.last_error = None;","                        slot.matrix.degraded = false;\n                        slot.matrix.retry_at = None;\n                        slot.matrix.restart_exhausted = false;\n                        slot.matrix.last_error = None;")
s=one(s,"            let retry_due = slot.matrix.retry_at.is_none_or(|retry_at| now >= retry_at);\n            if retry_due {","            let retry_due = !slot.matrix.restart_exhausted\n                && slot.matrix.retry_at.is_none_or(|retry_at| now >= retry_at);\n            if retry_due {","matrix retry gate")
old='''        let message = bounded_message(message);
        slot.matrix.degraded = true;
        slot.matrix.last_error = Some(message.clone());
        slot.matrix.restart_attempt = slot.matrix.restart_attempt.saturating_add(1);
        let shift = slot.matrix.restart_attempt.saturating_sub(1).min(7);
        let delay = MATRIX_RESTART_MIN
            .checked_mul(1_u32 << shift)
            .unwrap_or(MATRIX_RESTART_MAX)
            .min(MATRIX_RESTART_MAX);
        slot.matrix.retry_at = now.checked_add(delay);
        slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
'''
new='''        let message = bounded_message(message);
        slot.matrix.degraded = true;
        let expired = slot.matrix.restart_window_started_at.is_some_and(|started| {
            now.checked_duration_since(started)
                .is_some_and(|elapsed| elapsed >= self.config.restart_recovery_window)
        });
        if slot.matrix.restart_window_started_at.is_none() || expired {
            slot.matrix.restart_attempt = 0;
            slot.matrix.restart_window_started_at = Some(now);
            slot.matrix.restart_exhausted = false;
        }
        if slot.matrix.restart_attempt >= self.config.restart_max_attempts {
            let exhausted = bounded_message(format!(
                "{message}; Matrix automatic restart budget exhausted after {} attempts",
                slot.matrix.restart_attempt
            ));
            slot.matrix.last_error = Some(exhausted.clone());
            slot.matrix.retry_at = None;
            slot.matrix.restart_exhausted = true;
            slot.event(generation, SupervisorEventKind::MatrixDegraded(exhausted));
            return;
        }
        slot.matrix.restart_attempt = slot.matrix.restart_attempt.saturating_add(1);
        slot.matrix.last_error = Some(message.clone());
        let shift = slot.matrix.restart_attempt.saturating_sub(1).min(31);
        let delay = self.config.restart_backoff_min
            .checked_mul(1_u32 << shift)
            .unwrap_or(self.config.restart_backoff_max)
            .min(self.config.restart_backoff_max)
            .max(MATRIX_RESTART_MIN)
            .min(MATRIX_RESTART_MAX);
        slot.matrix.retry_at = now.checked_add(delay);
        slot.matrix.restart_exhausted = false;
        slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
'''
s=one(s,old,new,"matrix degrade")
write(p,s)

# Supervisor: explicit starts reset automatic budget; signed intent becomes an
# in-memory witness immediately after durable publication; tick can be per-agent.
p="codex-rs/hepta-supervisor/src/supervisor.rs"; s=read(p)
s=one(s,"        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.start_slot(agent_id, slot, command, now)\n        })","        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.reset_restart_budget(slot);\n            supervisor.start_slot(agent_id, slot, command, now)\n        })","start reset")
s=one(s,"        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.start_release_slot(agent_id, slot, release, now)\n        })","        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.reset_restart_budget(slot);\n            supervisor.start_release_slot(agent_id, slot, release, now)\n        })","start release reset")
s=one(s,"        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.restart_slot(agent_id, slot, now)\n        })","        self.with_slot(agent_id, |supervisor, slot| {\n            supervisor.reset_restart_budget(slot);\n            supervisor.restart_slot(agent_id, slot, now)\n        })","restart reset")
s=one(s,"            write_intent(record.layout.run_root(), &intent)\n                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n            supervisor.set_control_revision(agent_id, next_control_revision)?;\n            slot.signed_intent = Some(intent.clone());","            write_intent(record.layout.run_root(), &intent)\n                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n            slot.signed_intent = Some(intent.clone());\n            supervisor.set_control_revision(agent_id, next_control_revision)?;","signed witness ordering")
needle="    pub(crate) fn next_control_revision(&self, agent_id: &AgentId) -> Result<u64, SupervisorError> {"
if s.count(needle)!=1: raise SystemExit("next_control_revision insertion point")
s=s.replace(needle,"    pub(crate) fn signed_mutation_in_progress(&self, agent_id: &AgentId) -> bool {\n        self.slots\n            .get(agent_id)\n            .and_then(|slot| slot.signed_intent.as_ref())\n            .is_some_and(|intent| !matches!(intent.status, SignedIntentStatus::Committed))\n    }\n\n"+needle,1)
pat=re.compile(r"    pub fn tick\(&mut self, now: Instant\) -> TickReport \{.*?^    \}\n\n",re.M|re.S)
m=pat.search(s)
if not m: raise SystemExit("tick method not found")
replacement='''    pub fn tick_agent(&mut self, agent_id: &AgentId, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let result = self.with_slot(agent_id, |supervisor, slot| {
            supervisor.tick_slot(agent_id, slot, now)
        });
        if let Err(error) = result {
            self.record_fault(agent_id, &error, &mut report);
        }
        report
    }

    pub fn tick(&mut self, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let agent_ids: Vec<_> = self.slots.keys().cloned().collect();
        for agent_id in agent_ids {
            report.faults.extend(self.tick_agent(&agent_id, now).faults);
        }
        report
    }

'''
s=s[:m.start()]+replacement+s[m.end():]
write(p,s)

# Daemon: don't hold one mutex across the full 256-agent sweep. Signed errors
# become indeterminate after durable intent/revision mutation.
p="codex-rs/hepta-supervisor/src/daemon.rs"; s=read(p)
s=one(s,"                    let faults = tick_state.supervisor.lock().await.tick(Instant::now()).faults;\n                    tick_state.observed_faults.fetch_add(faults.len() as u64, Ordering::Relaxed);","                    let agent_ids = tick_state.supervisor.lock().await.agent_ids();\n                    let mut fault_count = 0_u64;\n                    for agent_id in agent_ids {\n                        let faults = tick_state.supervisor.lock().await\n                            .tick_agent(&agent_id, Instant::now()).faults;\n                        fault_count = fault_count.saturating_add(faults.len() as u64);\n                        tokio::task::yield_now().await;\n                    }\n                    tick_state.observed_faults.fetch_add(fault_count, Ordering::Relaxed);","ticker lock granularity")
s=one(s,"            let post = agent_status_locked(&state, &supervisor, &agent_id).ok();\n            return safe_rejection(\n                error,\n                post.or(Some(actual)),\n                /*mutation_started*/ false,\n            );","            let post = agent_status_locked(&state, &supervisor, &agent_id).ok();\n            let mutation_started = supervisor.signed_mutation_in_progress(&agent_id)\n                || post.as_ref().is_some_and(|status| {\n                    status.control_fence.state_digest != actual.control_fence.state_digest\n                });\n            return safe_rejection(\n                error,\n                post.or(Some(actual)),\n                mutation_started,\n            );","signed error semantics")
write(p,s)

# Regression tests for delayed automatic restart and fixed budget.
p="codex-rs/hepta-supervisor/src/supervisor_tests.rs"; s=read(p)
if "automatic_crash_restart_is_backed_off_and_budgeted" not in s:
    s += r'''

#[test]
fn automatic_crash_restart_is_backed_off_and_budgeted() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let mut now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    supervisor.tick(now);
    assert_eq!(control.spawn_count(&fleet.first), 1);

    for attempt in 1..=3_u32 {
        control.set_exit(&fleet.first);
        supervisor.tick(now);
        let snapshot = supervisor.snapshot(&fleet.first).expect("snapshot");
        assert!(snapshot.restart_pending);
        assert_eq!(
            supervisor.slots.get(&fleet.first).expect("slot").restart_attempt,
            attempt
        );
        assert_eq!(control.spawn_count(&fleet.first), usize::try_from(attempt).unwrap());

        now += Duration::from_millis(16);
        supervisor.tick(now);
        assert_eq!(control.spawn_count(&fleet.first), usize::try_from(attempt + 1).unwrap());
        control.set_healthy(&fleet.first);
        supervisor.tick(now);
        now += Duration::from_millis(16);
    }

    control.set_exit(&fleet.first);
    supervisor.tick(now);
    let slot = supervisor.slots.get(&fleet.first).expect("slot");
    assert!(!slot.restart_pending);
    assert!(slot.restart_exhausted);
    assert_eq!(slot.restart_attempt, 3);
    assert_eq!(control.spawn_count(&fleet.first), 4);
    Ok(())
}

#[test]
fn supervisor_config_rejects_unbounded_restart_policy() {
    let mut invalid = config();
    invalid.restart_max_attempts = 0;
    assert!(invalid.validate().is_err());
    invalid = config();
    invalid.restart_backoff_max = Duration::ZERO;
    assert!(invalid.validate().is_err());
}
'''
write(p,s)

# Dossier distinguishes repository implementation from host/authority closure.
p="qualification/module-execution-dossiers/detail/runtime.supervisor.md"; s=read(p)
s=one(s,"- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness.\n","- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness. Unexpected main-agent exits use bounded exponential backoff with a fixed three-attempt budget per configured recovery window; explicit drain/stop/kill/release transitions suppress crash restart. Matrix companion recovery uses the same fixed budget instead of retrying indefinitely.\n","dossier restart")
s=one(s,"- **Remaining work:** Qualify the actual deployed executable, host watchdog/drain behavior and independently accepted release transition; source tests do not prove the target host process lifecycle.\n","- **Remaining work:** Qualify the actual deployed executable, host watchdog/drain behavior, crash-consistency fault injection and independently accepted release transition; source tests do not prove the target host process lifecycle. Production release selection remains an externally authorized composition concern rather than a supervisor-owned candidate-selection capability.\n","dossier remaining")
write(p,s)

print("patch B staged")
