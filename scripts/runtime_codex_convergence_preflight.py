#!/usr/bin/env python3
"""Align the one-shot patchers with the exact reviewed source shape."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
patcher = root / "scripts/runtime_codex_convergence.py"
content = patcher.read_text(encoding="utf-8")
old = '''    ''' + "'''fn unix_time_ms() -> Result<u64> {\n" + '''    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    Ok(u64::try_from(elapsed.as_millis())?)
}
''',
'''
new = '''    ''' + "'''fn unix_time_ms() -> Result<u64> {\n" + '''    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    u64::try_from(elapsed.as_millis()).map_err(|_| "system clock milliseconds overflow".into())
}
''',
'''
if content.count(old) != 1:
    raise SystemExit(f"expected one exact clock matcher in patcher, found {content.count(old)}")
patcher.write_text(content.replace(old, new, 1), encoding="utf-8")

fixer = root / "scripts/runtime_codex_convergence_fix.py"
fix = fixer.read_text(encoding="utf-8")
marker = "# The handoff is already generation-fenced by AgentdClient; the handoff type\n"
insertion = r'''# Bind the source-order test to the real authorized send helper rather than a
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
    r''' + "'''" + r'''#[cfg(test)]
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
''' + "'''" + r''',
    r''' + "'''" + r'''#[cfg(test)]
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
''' + "'''" + r''',
)

'''
if fix.count(marker) != 1:
    raise SystemExit(f"expected one fixer insertion marker, found {fix.count(marker)}")
fixer.write_text(fix.replace(marker, insertion + marker, 1), encoding="utf-8")

diagnostic = root / "runtime_codex_patch_failure.txt"
if diagnostic.exists():
    diagnostic.unlink()

Path(__file__).unlink()
