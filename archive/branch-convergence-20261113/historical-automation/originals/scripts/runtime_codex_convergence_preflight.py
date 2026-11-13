#!/usr/bin/env python3
"""Align the one-shot patchers with the exact reviewed source shape."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
patcher = root / "scripts/runtime_codex_convergence.py"
content = patcher.read_text(encoding="utf-8")
old = """    '''fn unix_time_ms() -> Result<u64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    Ok(u64::try_from(elapsed.as_millis())?)
}
''',
"""
new = """    '''fn unix_time_ms() -> Result<u64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    u64::try_from(elapsed.as_millis()).map_err(|_| "system clock milliseconds overflow".into())
}
''',
"""
if content.count(old) != 1:
    raise SystemExit(f"expected one exact clock matcher in patcher, found {content.count(old)}")
patcher.write_text(content.replace(old, new, 1), encoding="utf-8")

fixer = root / "scripts/runtime_codex_convergence_fix.py"
fix = fixer.read_text(encoding="utf-8")
marker = "# The handoff is already generation-fenced by AgentdClient; the handoff type\n"
insertion = r"""# Bind the source-order test to the real authorized send helper rather than a
# removed direct request_typed call.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
    '        .find("client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart")\n',
    '        .find("send_authorized_turn_start(&mut client, entered_use, turn_params)")\n',
)

# Fault injection is per test thread. A process-global cell lets parallel tests
# consume one another's injected crash and makes the matrix nondeterministic.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_state.rs",
    "#[cfg(test)]\nuse std::sync::Mutex;\n#[cfg(test)]\nuse std::sync::OnceLock;\n",
    "#[cfg(test)]\nuse std::cell::RefCell;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_state.rs",
    r'''#[cfg(test)]
static INJECTED_FAULT: OnceLock<Mutex<Option<RuntimeCodexFaultPoint>>> = OnceLock::new();

pub(crate) fn runtime_codex_checkpoint(point: RuntimeCodexFaultPoint) -> Result<(), String> {
    #[cfg(test)]
    {
        let mut guard = INJECTED_FAULT
            .get_or_init(|| Mutex::new(None))
            .lock()
            .map_err(|_| "runtime.codex fault injector lock poisoned".to_string())?;
        if guard.as_ref() == Some(&point) {
            guard.take();
            return Err(format!("injected runtime.codex crash at {point:?}"));
        }
    }
    let _ = point;
    Ok(())
}

#[cfg(test)]
pub(crate) fn inject_runtime_codex_fault(point: RuntimeCodexFaultPoint) {
    *INJECTED_FAULT
        .get_or_init(|| Mutex::new(None))
        .lock()
        .expect("runtime.codex fault injector lock") = Some(point);
}
''',
    r'''#[cfg(test)]
std::thread_local! {
    static INJECTED_FAULT: RefCell<Option<RuntimeCodexFaultPoint>> = const { RefCell::new(None) };
}

pub(crate) fn runtime_codex_checkpoint(point: RuntimeCodexFaultPoint) -> Result<(), String> {
    #[cfg(test)]
    {
        let injected = INJECTED_FAULT.with(|fault| {
            let mut fault = fault.borrow_mut();
            if fault.as_ref() == Some(&point) {
                fault.take();
                true
            } else {
                false
            }
        });
        if injected {
            return Err(format!("injected runtime.codex crash at {point:?}"));
        }
    }
    let _ = point;
    Ok(())
}

#[cfg(test)]
pub(crate) fn inject_runtime_codex_fault(point: RuntimeCodexFaultPoint) {
    INJECTED_FAULT.with(|fault| *fault.borrow_mut() = Some(point));
}
''',
)

# Use the protocol's byte bound for pre-effect reasons; do not let a verbose
# upstream error turn a proven local abort into an avoidable owner conflict.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use codex_hepta_agent_protocol::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR;\n",
    "pub use codex_hepta_agent_protocol::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR;\npub use codex_hepta_agent_protocol::MAX_RUN_CANCEL_REASON_BYTES;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_hepta_agentd::HealthSnapshot;\n",
    "use codex_hepta_agentd::HealthSnapshot;\nuse codex_hepta_agentd::MAX_RUN_CANCEL_REASON_BYTES;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "async fn abort_before_effect_across_owners(\n",
    r'''fn bounded_abort_reason(reason: &str) -> String {
    let mut end = 0;
    for (index, character) in reason.char_indices() {
        let next = index.saturating_add(character.len_utf8());
        if next > MAX_RUN_CANCEL_REASON_BYTES {
            break;
        }
        end = next;
    }
    let bounded = &reason[..end];
    if bounded.trim().is_empty() {
        "runtime.codex pre-effect stop".to_string()
    } else {
        bounded.to_string()
    }
}

async fn abort_before_effect_across_owners(
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''    thread_lifecycle: &mut EphemeralThreadLifecycle,
) -> Result<()> {
    if let (Some(binding), Some(revision)) = (intelligence, *intelligence_revision) {
''',
    r'''    thread_lifecycle: &mut EphemeralThreadLifecycle,
) -> Result<()> {
    let reason = bounded_abort_reason(&reason);
    if let (Some(binding), Some(revision)) = (intelligence, *intelligence_revision) {
''',
)

# Treat the ephemeral thread as a scoped resource. Every error before effect
# entry attempts unsubscribe before shutdown; after effect entry it is retained
# for same-operation reconciliation.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_thread.rs",
    r'''    pub(crate) fn mark_effect_entered(&mut self) {
        self.effect_entered = true;
    }

    pub(crate) async fn close(
''',
    r'''    pub(crate) fn mark_effect_entered(&mut self) {
        self.effect_entered = true;
    }

    pub(crate) fn effect_entered(&self) -> bool {
        self.effect_entered
    }

    pub(crate) async fn close(
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''        if started.model != self.config.model {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
        let mut thread_lifecycle =
            EphemeralThreadLifecycle::new(started.thread.id.clone());
        execution_state.advance(RuntimeCodexPhase::ThreadPrepared)?;
        // Recheck the actual generation after connecting and creating the
''',
    r'''        let mut thread_lifecycle =
            EphemeralThreadLifecycle::new(started.thread.id.clone());
        let execution_result: Result<NativeRunOutput> = async {
            execution_state.advance(RuntimeCodexPhase::ThreadPrepared)?;
            if started.model != self.config.model {
                thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("provider substituted the requested model".into());
            }
        // Recheck the actual generation after connecting and creating the
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''        if cancellation.is_cancelled() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }
        if let Some(binding) = intelligence {
''',
    r'''        if cancellation.is_cancelled() {
            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }
        if let Some(binding) = intelligence {
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''            if Some(current_revision) != intelligence_revision {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("intelligence handoff revision changed before dispatch".into());
            }
''',
    r'''            if Some(current_revision) != intelligence_revision {
                thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("intelligence handoff revision changed before dispatch".into());
            }
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''        Ok(output)
    }

    async fn observe(
''',
    r'''        Ok(output)
        }
        .await;
        if execution_result.is_err() && !thread_lifecycle.effect_entered() {
            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        }
        execution_result
    }

    async fn observe(
''',
)

"""
if fix.count(marker) != 1:
    raise SystemExit(f"expected one fixer insertion marker, found {fix.count(marker)}")
fixer.write_text(fix.replace(marker, insertion + marker, 1), encoding="utf-8")

diagnostic = root / "runtime_codex_patch_failure.txt"
if diagnostic.exists():
    diagnostic.unlink()

Path(__file__).unlink()
