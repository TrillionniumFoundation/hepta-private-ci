#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:180]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"

# An idempotent Agentd acknowledgement means the exact run was already claimed.
# The losing worker must release only its local pre-effect reservation. Cancelling
# the Agentd run here would revoke the winner after it acquired the same digest.
replace_once(
    path,
    '''            // Idempotent acknowledgement is reconciliation, not a second
            // physical-send permit. A competing worker must not redispatch.
            if dispatched.phase != AgentRunPhase::Dispatched
                || dispatched.idempotent
''',
    '''            // Idempotent acknowledgement is reconciliation, not a second
            // physical-send permit. A competing worker must release only its
            // local proof and must never cancel the globally committed winner.
            if dispatched.idempotent {
                let reason =
                    "Agentd exact dispatch is already owned by another worker".to_string();
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
            if dispatched.phase != AgentRunPhase::Dispatched
''',
)

# Preserve a regression assertion that the loser path is local-only while all
# post-owner-commit fence failures continue through the exact cross-owner abort.
test_path = "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
target = ROOT / test_path
text = target.read_text(encoding="utf-8")
marker = "fn idempotent_dispatch_loser_never_aborts_the_global_owner()"
if marker not in text:
    text = text.rstrip() + r'''

#[test]
fn idempotent_dispatch_loser_never_aborts_the_global_owner() {
    let source = include_str!("native_app_server.rs");
    let loser_start = source
        .find("if dispatched.idempotent")
        .expect("idempotent loser branch");
    let next_validation = source[loser_start..]
        .find("if dispatched.phase != AgentRunPhase::Dispatched")
        .map(|offset| loser_start + offset)
        .expect("post-dispatch validation");
    let loser = &source[loser_start..next_validation];
    assert!(loser.contains("control.abort_native_before_effect("));
    assert!(!loser.contains("abort_pre_effect_consistently("));
    assert!(!loser.contains("run_abort_before_effect("));

    let post_commit = &source[next_validation..];
    assert!(post_commit.contains("abort_pre_effect_consistently("));
}
'''
    target.write_text(text + "\n", encoding="utf-8")

print("runtime.codex exact-dispatch winner preservation applied")
