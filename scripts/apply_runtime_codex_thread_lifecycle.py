#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "codex-rs/hepta-infer-worker-host/src/lib.rs",
    "pub mod runtime_codex_attempt;\n",
    "pub mod runtime_codex_attempt;\npub mod runtime_codex_thread_lifecycle;\n",
)

path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
target = ROOT / path
text = target.read_text(encoding="utf-8")

old = "use codex_hepta_types::StableId;\n"
new = '''use codex_hepta_types::StableId;
use crate::runtime_codex_thread_lifecycle::PreparedThreadGuard;
use crate::runtime_codex_thread_lifecycle::ThreadCleanupDisposition;
use crate::runtime_codex_thread_lifecycle::runtime_codex_thread_lifecycle_metrics;
'''
if text.count(old) != 1:
    raise RuntimeError("native_app_server.rs: stable-id import anchor drifted")
text = text.replace(old, new)

old = '''        .await??;
        if started.model != self.config.model {
'''
new = '''        .await??;
        let mut thread_lifecycle = PreparedThreadGuard::new(
            started.thread.id.clone(),
            started.thread.session_id.clone(),
            connection_id,
            runtime_codex_thread_lifecycle_metrics(),
        )?;
        if started.model != self.config.model {
'''
if text.count(old) != 1:
    raise RuntimeError("native_app_server.rs: thread-start completion anchor drifted")
text = text.replace(old, new)

old = '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        drop(pre_effect_abort);
'''
new = '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        thread_lifecycle.mark_effect_entered()?;
        drop(pre_effect_abort);
'''
if text.count(old) != 1:
    raise RuntimeError("native_app_server.rs: effect-entry anchor drifted")
text = text.replace(old, new)

old = '''        let binding = CodexTurnBinding {
            intent: adapter_intent,
            turn_id: StableId::new(turn.id.clone())?,
        };
'''
new = '''        thread_lifecycle.mark_started(&turn.id)?;
        let binding = CodexTurnBinding {
            intent: adapter_intent,
            turn_id: StableId::new(turn.id.clone())?,
        };
'''
if text.count(old) != 1:
    raise RuntimeError("native_app_server.rs: started-turn anchor drifted")
text = text.replace(old, new)

run_marker = "    async fn run_once(\n"
start = text.find(run_marker)
if start < 0:
    raise RuntimeError("native_app_server.rs: run_once anchor missing")
prefix, suffix = text[:start], text[start:]

final_cleanup = '''        if output.terminal_observed {
            let _ = timeout(
                RPC_TIMEOUT,
                client.request(ClientRequest::ThreadUnsubscribe {
                    request_id: RequestId::Integer(4),
                    params: ThreadUnsubscribeParams {
                        thread_id: output.thread_id.clone(),
                    },
                }),
            )
            .await;
        }
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
'''
replacement = '''        if output.terminal_observed {
            thread_lifecycle.mark_terminal_observed(&output.turn_id)?;
        }
        cleanup_prepared_thread(&mut client, &mut thread_lifecycle).await;
'''
if suffix.count(final_cleanup) != 1:
    raise RuntimeError(
        f"native_app_server.rs: expected one final cleanup block, found {suffix.count(final_cleanup)}"
    )
suffix = suffix.replace(final_cleanup, replacement)

shutdown = "let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;"
count = suffix.count(shutdown)
if count < 8:
    raise RuntimeError(f"native_app_server.rs: expected bounded shutdown exits, found {count}")
suffix = suffix.replace(
    shutdown,
    "cleanup_prepared_thread(&mut client, &mut thread_lifecycle).await;",
)
text = prefix + suffix

helper_anchor = "fn final_use_binding(\n"
helper = '''async fn cleanup_prepared_thread(
    client: &mut RemoteAppServerClient,
    lifecycle: &mut PreparedThreadGuard,
) {
    let cleanup_started = lifecycle.begin_cleanup().is_ok();
    let unsubscribed = matches!(
        timeout(
            RPC_TIMEOUT,
            client.request(ClientRequest::ThreadUnsubscribe {
                request_id: RequestId::Integer(4),
                params: ThreadUnsubscribeParams {
                    thread_id: lifecycle.thread_id().to_string(),
                },
            }),
        )
        .await,
        Ok(Ok(_))
    );
    if cleanup_started {
        if unsubscribed {
            let _cleanup =
                lifecycle.complete_cleanup(ThreadCleanupDisposition::Unsubscribed);
        } else {
            let _failure = lifecycle.record_cleanup_failure();
        }
    }
    let connection_closed = matches!(
        timeout(RPC_TIMEOUT, client.shutdown()).await,
        Ok(Ok(()))
    );
    if cleanup_started && !unsubscribed && connection_closed {
        let _cleanup =
            lifecycle.complete_cleanup(ThreadCleanupDisposition::ConnectionClosed);
    }
}

fn final_use_binding(
'''
if text.count(helper_anchor) != 1:
    raise RuntimeError("native_app_server.rs: final-use helper anchor drifted")
text = text.replace(helper_anchor, helper)
target.write_text(text, encoding="utf-8")
print(f"integrated runtime.codex thread lifecycle guard across {count + 1} cleanup paths")
