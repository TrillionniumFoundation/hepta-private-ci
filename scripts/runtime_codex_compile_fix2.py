#!/usr/bin/env python3
"""One-shot compile fixes for the generated runtime.codex candidate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one replacement, found {count}: {old[:120]!r}"
        )
    write(path, content.replace(old, new, 1))


# Linux SO_PEERCRED exposes pid_t (i32). Reject negative values rather than
# narrowing with an unchecked cast before comparing the pinned process identity.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''            #[cfg(target_os = "linux")]
            let peer_pid = peer.pid();
''',
    '''            #[cfg(target_os = "linux")]
            let peer_pid = match peer.pid() {
                Some(pid) => Some(u32::try_from(pid)?),
                None => None,
            };
''',
)

# RemoteAppServerClient::shutdown consumes the client. The scoped execution
# closure must retain it for pre-effect cleanup and all terminal observation.
# Remove consuming shutdowns from the closure, then perform exactly one shutdown
# after the closure has completed and the thread lifecycle has been reconciled.
path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
content = read(path)
start_marker = "        let execution_result: Result<NativeRunOutput> = async {\n"
end_marker = "        execution_result\n    }\n\n    async fn observe(\n"
start = content.find(start_marker)
if start < 0:
    raise SystemExit("native_app_server.rs: missing scoped execution start")
end = content.find(end_marker, start)
if end < 0:
    raise SystemExit("native_app_server.rs: missing scoped execution tail")
segment = content[start:end]
shutdown = "            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n"
shutdown_count = segment.count(shutdown)
if shutdown_count < 2:
    raise SystemExit(
        f"native_app_server.rs: expected multiple scoped shutdowns, found {shutdown_count}"
    )
segment = segment.replace(shutdown, "")
old_tail = '''        if execution_result.is_err() && !thread_lifecycle.effect_entered() {
            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        }
'''
new_tail = '''        if execution_result.is_err() && !thread_lifecycle.effect_entered() {
            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
        }
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
'''
if segment.count(old_tail) != 1:
    raise SystemExit("native_app_server.rs: scoped execution cleanup tail drifted")
segment = segment.replace(old_tail, new_tail, 1)
write(path, content[:start] + segment + content[end:])

# A prior failed candidate may have retained this bounded diagnostic. It is not
# source or evidence for the newly generated candidate.
diagnostic = ROOT / "runtime_codex_compile_failure.txt"
if diagnostic.exists():
    diagnostic.unlink()

Path(__file__).unlink()
