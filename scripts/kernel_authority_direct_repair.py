#!/usr/bin/env python3
"""One-shot, fail-closed repair for the kernel.authority convergence candidate.

This script is intentionally narrow: every rewrite is shape-checked and it exits
without writing a partial replacement when the candidate no longer matches the
reviewed source.  The temporary workflow that invokes it removes this file after
committing the repaired source anchor and regenerated status projections.
"""

from __future__ import annotations

from pathlib import Path


def read(path: str) -> tuple[Path, str]:
    file = Path(path)
    return file, file.read_text(encoding="utf-8")


def write_if_changed(file: Path, before: str, after: str) -> None:
    if after != before:
        file.write_text(after, encoding="utf-8")


def replace_once(path: str, old: str, new: str, *, already: str | None = None) -> None:
    file, text = read(path)
    if old in text:
        updated = text.replace(old, new, 1)
    elif already is not None and already in text:
        updated = text
    elif new in text:
        updated = text
    else:
        raise SystemExit(f"{path}: expected repair anchor is missing")
    write_if_changed(file, text, updated)


# Production trust evidence validation: use the canonical slice membership
# operation rather than two clippy-rejected manual scans.
file, text = read("codex-rs/hepta-contracts/src/authority_trust.rs")
manual = "digests.iter().any(|digest| *digest == [0; 32])"
canonical = "digests.contains(&[0; 32])"
manual_count = text.count(manual)
if manual_count:
    if manual_count != 2:
        raise SystemExit(f"unexpected zero-digest validation count: {manual_count}")
    updated = text.replace(manual, canonical)
elif text.count(canonical) >= 2:
    updated = text
else:
    raise SystemExit("production trust digest validation has an unexpected shape")
write_if_changed(file, text, updated)

# The issuer key ring is moved into the production owner and is not reused.
replace_once(
    "codex-rs/hepta-contracts/src/authority_trust_tests.rs",
    """        issuer_keys.clone(),
        &verified_head,""",
    """        issuer_keys,
        &verified_head,""",
)

# Recovery may finish a durable pending transition, but it must not synthesize
# a committed state from an arbitrary restored snapshot just because the caller
# presents the same authenticated head as the external frontier.
file, text = read("codex-rs/hepta-contracts/src/final_use.rs")
old_comment = """    /// Recover existing state only after exact external-frontier verification.
    /// The authenticated `head` may complete a frontier-first pending or commit
    /// transition, but it can never move the trusted frontier itself."""
new_comment = """    /// Recover existing state only after exact external-frontier verification.
    /// The authenticated `head` may complete only a transition represented by
    /// the durable pending marker or its exact trusted frontier. It cannot
    /// manufacture a committed head from an arbitrary restored snapshot and it
    /// can never move the trusted frontier itself."""
if old_comment in text:
    text = text.replace(old_comment, new_comment, 1)
elif new_comment not in text:
    raise SystemExit("final-use recovery contract comment has an unexpected shape")
unsafe_commit_synthesis = """
    if head_advances(&state.head, authenticated_head) {
        let mut committed = state.clone();
        if authenticated_head.authority_epoch > committed.head.authority_epoch {
            committed.used_nonces.clear();
        }
        committed.head = authenticated_head.clone();
        committed.pending_revocations = None;
        if frontier_for_state(&committed) == trusted {
            store.persist(&committed)?;
            *state = committed;
            return Ok(());
        }
    }
"""
if unsafe_commit_synthesis in text:
    text = text.replace(unsafe_commit_synthesis, "\n", 1)
elif "committed.head = authenticated_head.clone();" in text:
    raise SystemExit("unrecognized restored-snapshot commit synthesis remains")
write_if_changed(file, file.read_text(encoding="utf-8"), text)

# A v1 migration fixture must remove post-v1 objects in reverse dependency
# order.  The timer drain trigger references the v2 outcome table.
file, text = read("codex-rs/hepta-automation/tests/automation.rs")
anchor = """    let mut rewind = pool.begin().await.expect("begin legacy schema rewind");
    sqlx::query("DROP INDEX automation_dispatch_outcome_state_idx")"""
replacement = """    let mut rewind = pool.begin().await.expect("begin legacy schema rewind");
    sqlx::query("DROP TRIGGER IF EXISTS automation_timer_lifecycle_drain")
        .execute(&mut *rewind)
        .await
        .expect("drop timer lifecycle drain trigger");
    sqlx::query("DROP INDEX automation_dispatch_outcome_state_idx")"""
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif "drop timer lifecycle drain trigger" not in text:
    raise SystemExit("automation v1 rewind prelude has an unexpected shape")
anchor = """        "DROP TRIGGER IF EXISTS automation_runs_schedule_revision_no_update",
        "DROP TRIGGER IF EXISTS automation_task_default_policy","""
replacement = """        "DROP TRIGGER IF EXISTS automation_runs_schedule_revision_no_update",
        "DROP TABLE IF EXISTS automation_timer_lifecycle",
        "DROP TRIGGER IF EXISTS automation_task_default_policy","""
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif '"DROP TABLE IF EXISTS automation_timer_lifecycle"' not in text:
    raise SystemExit("automation v1 rewind object list has an unexpected shape")
write_if_changed(file, file.read_text(encoding="utf-8"), text)

# The recovery pilot deliberately asks the descriptor-bound production path to
# establish immutable identities.  Harden the fixture permissions first.
file, text = read("codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs")
import_anchor = "use std::fs;\nuse std::sync::Arc;"
import_replacement = "use std::fs;\nuse std::os::unix::fs::PermissionsExt;\nuse std::sync::Arc;"
if import_anchor in text:
    text = text.replace(import_anchor, import_replacement, 1)
elif "use std::os::unix::fs::PermissionsExt;" not in text:
    raise SystemExit("agentd recovery test imports have an unexpected shape")
anchor = """    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let expected = store.recovery_anchor().await?;
    drop(store);"""
replacement = """    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let expected = store.recovery_anchor().await?;
    let database_path = store.path().to_path_buf();
    let cognitive_root = config.identity().layout.cognitive_root().to_path_buf();
    drop(store);
    fs::set_permissions(&cognitive_root, fs::Permissions::from_mode(0o700))?;
    fs::set_permissions(&database_path, fs::Permissions::from_mode(0o600))?;
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut sidecar = database_path.as_os_str().to_os_string();
        sidecar.push(suffix);
        let sidecar = std::path::PathBuf::from(sidecar);
        if sidecar.exists() {
            fs::set_permissions(sidecar, fs::Permissions::from_mode(0o600))?;
        }
    }"""
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif "let database_path = store.path().to_path_buf();" not in text:
    raise SystemExit("agentd recovery fixture has an unexpected shape")
write_if_changed(file, file.read_text(encoding="utf-8"), text)

# The production dispatch binder is the sole expected internal caller of raw
# lease verification. Record that exact closed-world callsite.
file, text = read("CALLERS.toml")
old = """[[boundary]]
id = "authority_lease_verify_use"
symbol = "AuthorityLeaseVerifier::verify_use"
call_pattern = '\\.\\s*verify_use\\s*\\('
caller_type_marker = "AuthorityLeaseVerifier"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub struct AuthorityLeaseVerifier", "pub fn verify_use(", "LeaseVerifiedUseToken"]
product_callers = []
caller_markers = []"""
new = """[[boundary]]
id = "authority_lease_verify_use"
symbol = "AuthorityLeaseVerifier::verify_use"
call_pattern = '\\.\\s*verify_use\\s*\\('
caller_type_marker = "AuthorityLeaseVerifier"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub struct AuthorityLeaseVerifier", "pub fn verify_use(", "LeaseVerifiedUseToken"]
product_callers = ["codex-rs/hepta-contracts/src/authority_trust.rs"]
caller_markers = ["AuthorityLeaseVerifier", "self.verify_use(", "AuthorityDispatchBinding"]"""
if old in text:
    updated = text.replace(old, new, 1)
elif new in text:
    updated = text
else:
    raise SystemExit("authority_lease_verify_use inventory has an unexpected shape")
write_if_changed(file, text, updated)
