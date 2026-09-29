#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern!r}")
    write(path, next_text)


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + addition.strip() + "\n")


replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse tokio::sync::Mutex;\n",
    "#[cfg(unix)]\nuse crate::MeasuredMutex;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    supervisor: Mutex<Supervisor<D>>,\n",
    "    supervisor: MeasuredMutex<Supervisor<D>>,\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "        supervisor: Mutex::new(supervisor),\n",
    '        supervisor: MeasuredMutex::named("runtime.supervisor.global", supervisor),\n',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    let _ = ticker.await;\n    result\n}\n\n#[cfg(not(unix))]",
    """    let _ = ticker.await;
    let lock = state.supervisor.telemetry();
    eprintln!(
        "runtime.supervisor mutex summary acquisitions={} contended={} total_wait_ns={} max_wait_ns={} slow_waits={} total_hold_ns={} max_hold_ns={} slow_holds={}",
        lock.acquisitions,
        lock.contended_acquisitions,
        lock.total_wait_ns,
        lock.max_wait_ns,
        lock.slow_waits,
        lock.total_hold_ns,
        lock.max_hold_ns,
        lock.slow_holds,
    );
    result
}

#[cfg(not(unix))]""",
)

replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    "use std::io::Write;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    """    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    publish::publish(&temp, &final_path)?;
    Ok(())
""",
    """    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp)?;
    let result: Result<(), SignedIntentError> = (|| {
        crate::durability::write_all(&mut file, &bytes, "signed_intent")?;
        crate::durability::sync_all(&file, "signed_intent")?;
        drop(file);
        publish::publish(&temp, &final_path)?;
        Ok(())
    })();
    if result.is_err() && temp.exists() {
        let _ = std::fs::remove_file(&temp);
    }
    result
""",
)

replace_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    "use std::fs::OpenOptions;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    "use std::io::Write;\n",
    "",
)
regex_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    r"    let mut file = OpenOptions::new\(\)\n        \.write\(true\)\n        \.create_new\(true\)\n        \.open\(&temp\)\?;\n    file\.write_all\(&bytes\)\?;\n    file\.sync_all\(\)\?;\n    drop\(file\);\n    replace_same_directory\(&temp, &final_path\)\?;\n    sync_directory\(run_root\)\?;\n    Ok\(\(\)\)\n}\n\nfn replace_same_directory\(.*?\n}\n\n#\[cfg\(unix\)\]\nfn sync_directory\(.*?\n}\n\n#\[cfg\(not\(unix\)\)\]\nfn sync_directory\(.*?\n}\n",
    """    crate::durable_publish::write_atomic(
        &temp,
        &final_path,
        &bytes,
        "release_transaction",
    )?;
    Ok(())
}
""",
)

replace_once(
    "codex-rs/hepta-supervisor/src/restart_journal.rs",
    "use std::fs::OpenOptions;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/restart_journal.rs",
    "use std::io::Write;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/restart_journal.rs",
    """    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = crate::durable_publish::publish(&temp_path, &final_path) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(error.into());
    }
    Ok(())
""",
    """    crate::durable_publish::write_atomic(
        &temp_path,
        &final_path,
        &bytes,
        "restart_journal",
    )?;
    Ok(())
""",
)

replace_once(
    "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json",
    '  "productCallerState": "not_composed",\n',
    '  "productCallerState": "source_composed_pinned_bundle_not_activated",\n',
)

append_once(
    "docs/modules/runtime.supervisor/TECHNICAL.md",
    "### Repository-controlled qualification implementation (2026-09-30)",
    """
### Repository-controlled qualification implementation (2026-09-30)

The source tree now measures wait and hold time on the existing global supervisor
writer lock and carries an executable 256-instance qualification covering healthy
fleets, 10/50/100 percent crash waves, slow process-driver work, slow durable work,
and concurrent status/drain/tick traffic. The measurement does not partition the
lock or widen lifecycle authority. The ordering decision and refactor trigger are
recorded in [HOL_REFACTOR_DECISION.md](HOL_REFACTOR_DECISION.md).

Crash-relevant process lease, restart record, signed-intent and release-transaction
writers share qualification-only write, fsync, rename/link and directory-sync fault
points. The default product contains no runtime fault switch. A real subprocess
SIGKILL test validates the resulting files from a fresh process. Commands and the
remaining target-host evidence boundary are documented in
[qualification/runtime-supervisor/README.md](../../../qualification/runtime-supervisor/README.md).

The named `hepta-supervisord` product caller can consume an exact-digest public-key
bundle produced by the external release-policy owner. The bundle contains no
signing key, and rotation changes the pinned signer identity/epoch/key/digest tuple.
This closes source composition only; deployment, external signer operation and
independent acceptance remain externally governed.

`hepta-supervisor-recovery-diagnose` is a read-only operator command. It classifies
process ambiguity, release-state ambiguity, intent mismatch, Fleet-frontier drift,
authority-epoch change and durability failure, and maps each class to a bounded
operator action. It never terminalizes a transaction or manufactures authority.
""",
)

append_once(
    "docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md",
    "## 9. Executable repository qualification added 2026-09-30",
    """
## 9. Executable repository qualification added 2026-09-30

Repository-controlled tests now execute the crash matrix for process lease, unified
restart record, signed intent and release transaction at file write, file sync,
rename/hard-link and parent-directory sync boundaries. Disk-full is represented by
the platform `StorageFull` error at the actual writer; corruption tests truncate each
real file and require fail-closed decoding. The SIGKILL case uses a separate process,
publishes the real four durable records, synchronizes a readiness marker, receives
`SIGKILL`, and is inspected by a fresh process.

The 256-instance test emits one machine-readable JSON line with tick duration,
status-read p50/p95/p99/max latency, mutex wait/hold counters and crash-wave fault
counts. Slow driver and slow durable-holder cases deliberately demonstrate the
serialization cost. This is evidence that head-of-line blocking is measurable, not
by itself evidence that current target-host deadlines or service objectives are
violated. The global writer remains until a target-host receipt proves that trigger;
then a collect/effect/apply or per-Agent design must retain generation, Fleet-CAS and
release-transaction ordering.

The new source-level authority composition consumes a SHA-256-pinned public verifier
bundle and tests signer rotation, wrong signer, expired grant, stale daemon-authority
epoch and current Fleet revocation. No signing key enters the supervisor and no
release selection is self-issued. Deployed distribution, target-host measurements
and independent operational acceptance remain open external gates.
""",
)

print("runtime.supervisor qualification patches applied")
