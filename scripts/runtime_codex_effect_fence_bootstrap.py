#!/usr/bin/env python3
"""Apply the exact runtime.codex server-owned effect-entry fence patch.

This is a one-shot branch transformer.  It verifies Git blob identities and
fails closed when any reviewed source fragment moved.  The pull-request
bootstrap workflow formats, checks, commits, and removes this file.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_BLOBS = {
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs": "57eb184ae7deb81de61e1d1743e4ff7fe5c5318f",
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs": "7337ef0310530d2f39a8a5a59d3b5484567b635d",
    "codex-rs/hepta-infer-worker-host/src/native_execution.rs": "4b1d0b02b1c63928327b42cccf8f140502f6135b",
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs": "5fe5f17906fc19ac3aa84ae7f3efa38c21195924",
    "docs/modules/runtime.codex/REMEDIATION_STATUS.md": "372b84d7b933f3efc0aea0ba0a7a75747628ae37",
}


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    path(name).write_text(text, encoding="utf-8")


def verify_blob(name: str, expected: str) -> None:
    actual = subprocess.check_output(
        ["git", "hash-object", "--", name], cwd=ROOT, text=True
    ).strip()
    if actual != expected:
        raise SystemExit(f"{name}: expected blob {expected}, got {actual}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    first = text.find(start)
    if first < 0:
        raise SystemExit(f"{label}: start marker not found")
    second = text.find(start, first + 1)
    if second >= 0:
        raise SystemExit(f"{label}: start marker is ambiguous")
    stop = text.find(end, first + len(start))
    if stop < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:first] + replacement + text[stop:]


def patch_owner_state() -> None:
    name = "codex-rs/hepta-agentd/src/lane_b_runtime.rs"
    text = read(name)
    method = """    pub fn mark_dispatched_exact(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {"""
    documented = """    /// Irrevocable server-owned runtime.codex effect-entry fence.
    ///
    /// Only a fresh, non-idempotent receipt authorizes the caller to attempt
    /// the physical App Server send. An idempotent receipt is reconciliation,
    /// never a second-send permit. Once this CAS commits, `abort_before_effect`
    /// is permanently unavailable; process or acknowledgement loss remains
    /// same-operation reconciliation.
    pub fn mark_dispatched_exact(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {"""
    text = replace_once(text, method, documented, "effect-entry method documentation")

    old = """        match record.phase {
            RunPhase::ContextAttached => {
                require_revision(record, pre_dispatch_revision)?;
                if record.dispatch_digest.is_some() {
                    return Err(AgentRunError::Conflict);
                }
                record.dispatch_digest = Some(dispatch_digest.to_string());
            }
            RunPhase::Dispatched => {
                let dispatched_revision = pre_dispatch_revision
                    .checked_add(1)
                    .ok_or(AgentRunError::ArithmeticOverflow)?;
                require_revision(record, dispatched_revision)?;
                if record.dispatch_digest.as_deref() != Some(dispatch_digest) {
                    return Err(AgentRunError::Conflict);
                }
            }
            _ => return Err(AgentRunError::InvalidTransition),
        }
"""
    new = """        // ContextAttached is the final abortable owner state. A fresh exact
        // transition to Dispatched is the server-owned effect-entry fence and
        // is deliberately irreversible even when the caller later proves that
        // it crashed before the socket write. That conservative ambiguity is
        // required to make abort-after-send impossible.
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::InvalidTransition);
        }
        require_revision(record, pre_dispatch_revision)?;
        if record.dispatch_digest.is_some() {
            return Err(AgentRunError::Conflict);
        }
        record.dispatch_digest = Some(dispatch_digest.to_string());
"""
    text = replace_once(text, old, new, "irreversible owner fence")
    write(name, text)


def patch_owner_tests() -> None:
    name = "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs"
    text = read(name)
    start = """#[test]
fn exact_dispatch_abort_is_digest_bound_and_idempotent() {"""
    end = """#[test]
fn duplicate_owner_stress_never_accepts_two_dispatch_digests() {"""
    replacement = """#[test]
fn exact_dispatch_is_a_single_winner_irrevocable_effect_entry_fence() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("start");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");

    let fresh = coordinator
        .mark_dispatched_exact(300, "run.1", 2, &digest('a'))
        .expect("fresh exact effect-entry fence");
    assert_eq!(fresh.phase, RunPhase::Dispatched);
    assert_eq!(fresh.dispatch_digest, Some(digest('a')));
    assert!(!fresh.idempotent, "only this receipt is a send permit");

    let reconciled = coordinator
        .mark_dispatched_exact(301, "run.1", 2, &digest('a'))
        .expect("same fence reconciliation");
    assert!(reconciled.idempotent, "reconciliation is never a send permit");
    assert_eq!(
        coordinator.mark_dispatched_exact(301, "run.1", 2, &digest('b')),
        Err(AgentRunError::Conflict)
    );

    let before = coordinator.run("run.1");
    assert_eq!(
        coordinator.abort_before_effect("run.1", 2, &digest('a'), "late abort"),
        Err(AgentRunError::InvalidTransition),
        "the server fence must make abort-after-send impossible"
    );
    assert_eq!(coordinator.run("run.1"), before);
    assert_eq!(coordinator.active_run_count(), 1);
}

#[test]
fn exact_abort_is_available_only_before_effect_entry_and_is_idempotent() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("start");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");

    let aborted = coordinator
        .abort_before_effect("run.1", 2, &digest('c'), "final-use denied")
        .expect("abort context-attached predecessor");
    assert_eq!(aborted.phase, RunPhase::Cancelled);
    assert_eq!(aborted.dispatch_digest, Some(digest('c')));
    assert_eq!(coordinator.active_run_count(), 0);

    let repeated = coordinator
        .abort_before_effect("run.1", 2, &digest('c'), "final-use denied")
        .expect("repeat exact abort");
    assert!(repeated.idempotent);
    assert_eq!(
        coordinator.abort_before_effect("run.1", 2, &digest('d'), "final-use denied"),
        Err(AgentRunError::Conflict)
    );
    assert_eq!(
        coordinator.abort_before_effect("run.1", 2, &digest('c'), "different reason"),
        Err(AgentRunError::Conflict)
    );
}

""" + end
    text = replace_between(text, start, end, replacement, "owner fence tests")

    start = """#[test]
fn exact_abort_retry_rejects_revision_or_reason_drift() {"""
    end = """#[test]
fn normal_cancel_is_not_reusable_as_a_pre_effect_abort() {"""
    replacement = """#[test]
fn exact_abort_retry_rejects_revision_digest_or_reason_drift() {
    let mut owner = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    owner.start_run(100, snapshot()).unwrap();
    owner.attach_context(200, 1, attachment()).unwrap();
    let original = owner
        .abort_before_effect("run.1", 2, &digest('a'), "pre-effect fence denied")
        .unwrap();
    assert!(
        owner
            .abort_before_effect("run.1", 2, &digest('a'), "pre-effect fence denied")
            .unwrap()
            .idempotent
    );
    assert!(
        owner
            .abort_before_effect("run.1", 1, &digest('a'), "pre-effect fence denied")
            .is_err()
    );
    assert!(
        owner
            .abort_before_effect("run.1", 2, &digest('b'), "pre-effect fence denied")
            .is_err()
    );
    assert!(
        owner
            .abort_before_effect("run.1", 2, &digest('a'), "different reason")
            .is_err()
    );
    assert_eq!(owner.run("run.1"), Some(original));
    assert_eq!(owner.active_run_count(), 0);
}

""" + end
    text = replace_between(text, start, end, replacement, "abort retry tests")
    write(name, text)


def patch_product_ordering() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/native_execution.rs"
    text = read(name)
    text = replace_once(
        text,
        """        let mut owner_abort_required = intelligence.is_some();
        let preparation: Result<(EnteredUseToken, Duration)> = async {""",
        """        let mut owner_abort_required = intelligence.is_some();
        // Once the exact Agentd effect-entry CAS is attempted, neither the
        // owner nor the local journal may be downgraded to definitely-unsent.
        // A lost/mismatched/idempotent acknowledgement is reconcile-only and
        // never authorizes a physical send.
        let mut effect_entry_fence_started = false;
        let preparation: Result<(EnteredUseToken, Duration)> = async {""",
        "effect-entry flag",
    )

    start = """            if let Some(binding) = intelligence {
                let dispatched = owner
                    .run_mark_dispatched_exact("""
    end = """            let post_health = owner.health().await?;"""
    text = replace_between(text, start, end, end, "remove early owner dispatch")

    old = """            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            Ok((entered_use, send_budget))
"""
    new = """            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            if let Some(binding) = intelligence {
                // This is the server-owned, single-winner effect-entry fence.
                // Set the flag before awaiting the RPC: an unknown ACK must not
                // run either pre-effect compensation path.
                effect_entry_fence_started = true;
                let dispatched = owner
                    .run_mark_dispatched_exact(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_digest.clone(),
                    )
                    .await?;
                if dispatched.idempotent {
                    return Err(
                        "Agentd effect-entry fence was already committed; reconcile only"
                            .into(),
                    );
                }
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.dispatch_digest.as_deref() != Some(dispatch_digest.as_str())
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err(
                        "Agentd returned a mismatched fresh effect-entry fence receipt".into(),
                    );
                }
                intelligence_revision = Some(dispatched.revision);
            }
            Ok((entered_use, send_budget))
"""
    text = replace_once(text, old, new, "late owner effect-entry fence")

    start = """            Err(error) => {
                let reason: String = error.to_string().chars().take(512).collect();"""
    end = """        };
        // From here on, a missing acknowledgement is reconcile-only."""
    replacement = """            Err(error) => {
                if effect_entry_fence_started {
                    // The CAS may have committed. Preserve the local slot and
                    // App Server history, destroy the process-local abort proof,
                    // and never send without a fresh non-idempotent ACK.
                    thread_guard.effect_entered();
                    drop(pre_effect_abort);
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(format!(
                        "runtime.codex effect-entry fence requires same-operation reconciliation: {error}"
                    )
                    .into());
                }
                let reason: String = error.to_string().chars().take(512).collect();
                let stopped = if owner_abort_required {
                    abort_pre_effect_consistently(
                        control,
                        &owner,
                        intelligence,
                        pre_effect_abort,
                        request_receipt.request_digest,
                        reason,
                    )
                    .await
                } else {
                    control
                        .abort_native_before_effect(pre_effect_abort, reason)
                        .map(|_| ())
                        .map_err(Into::into)
                };
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(error);
            }
""" + end
    text = replace_between(text, start, end, replacement, "effect-entry error handling")

    old = """        let attempt = attempt
            .prepare_durable(request_receipt.request_digest)?
            .commit_owner(
                intelligence_revision.unwrap_or(prepared_revision),
                request_receipt.request_digest,
            )?;
        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let attempt = attempt.enter_effect();
"""
    new = """        // The owner fence is now irreversible. Destroy local abort
        // authority and retain the thread before any further fallible local
        // bookkeeping; failures from here are reconcile-only.
        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let attempt = attempt
            .prepare_durable(request_receipt.request_digest)?
            .commit_owner(
                intelligence_revision.unwrap_or(prepared_revision),
                request_receipt.request_digest,
            )?;
        let attempt = attempt.enter_effect();
"""
    text = replace_once(text, old, new, "post-fence local ordering")
    write(name, text)


def patch_product_tests() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
    text = read(name)
    addition = r'''

#[test]
fn agentd_effect_entry_cas_is_the_last_fallible_gate_before_physical_send() {
    let source = include_str!("native_execution.rs");
    let final_context = source
        .find("owner.revalidate_cognitive_context(snapshot)")
        .expect("final context revalidation");
    let token_entry = source
        .find("verified_use.enter(&authority_binding)")
        .expect("final-use token entry");
    let owner_fence = source
        .find(".run_mark_dispatched_exact(")
        .expect("Agentd effect-entry CAS");
    let proof_destroy = source
        .find("drop(pre_effect_abort);")
        .expect("local abort proof destruction");
    let physical_send = source
        .find("send_authorized_turn_start(&mut client")
        .expect("physical turn/start");

    assert!(final_context < token_entry);
    assert!(token_entry < owner_fence);
    assert!(owner_fence < proof_destroy);
    assert!(proof_destroy < physical_send);
    assert!(source.contains(
        "Agentd effect-entry fence was already committed; reconcile only"
    ));
    assert!(source.contains(
        "effect-entry fence requires same-operation reconciliation"
    ));
}
'''
    if "fn agentd_effect_entry_cas_is_the_last_fallible_gate_before_physical_send" in text:
        raise SystemExit("product fence test already exists")
    text += addition
    write(name, text)


def patch_status() -> None:
    name = "docs/modules/runtime.codex/REMEDIATION_STATUS.md"
    text = read(name)
    text = replace_once(
        text,
        "Date: 2026-09-27 (Asia/Tokyo). Branch: `codex/runtime-codex-consolidated-20260927`.",
        "Date: 2026-09-27 (Asia/Tokyo). Branch: `runtime-codex/closure-20260927`.",
        "status branch identity",
    )
    old = """### Server-owned effect-entry fence

The worker owns an unforgeable live pre-effect abort token, but the new Agentd abort RPC transports serializable run/revision/digest/reason fields. Those fields alone cannot prove to Agentd that no physical send has occurred. Before merge/activation, add a server-owned effect-entry fence, enforced at the same owner that controls the effect, or an equivalent authenticated one-entry protocol. Once the fence may have been committed, abort must be impossible and a lost fence acknowledgement must remain reconcile-only. Add adversarial tests for abort-after-send, fence/abort races, duplicate workers and lost fence acknowledgement. **The current cross-owner P0 is not closed.**
"""
    new = """### Server-owned effect-entry fence

This source candidate now treats the fresh, non-idempotent Agentd `RunMarkDispatchedExact` CAS as the irreversible server-owned effect-entry fence. Final owner/ingress, context, cancellation, deadline and final-use-token checks all precede that CAS. Agentd accepts `abort-before-effect` only while the run remains `ContextAttached`; after the CAS reaches `Dispatched`, abort is impossible. Only the caller that receives the fresh exact ACK may issue physical `turn/start`. An idempotent response, mismatched response, transport loss or process loss authorizes no send and leaves both the local slot and owner state for same-operation reconciliation.

The source-level P0 design is therefore closed in this candidate, but **qualification is not yet closed**: exact-head and synthetic-merge Rust tests, adversarial duplicate-worker/fence tests and product physical-send-count evidence must pass for the final commit before this statement can be promoted from source design to verified evidence.
"""
    text = replace_once(text, old, new, "status effect-entry section")
    write(name, text)


def main() -> None:
    for name, expected in EXPECTED_BLOBS.items():
        verify_blob(name, expected)
    patch_owner_state()
    patch_owner_tests()
    patch_product_ordering()
    patch_product_tests()
    patch_status()

    # Remove the one-shot transport before publishing actual source.
    path(".github/workflows/runtime-codex-effect-fence-bootstrap.yml").unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
