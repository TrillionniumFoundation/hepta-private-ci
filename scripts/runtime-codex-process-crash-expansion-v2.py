#!/usr/bin/env python3
"""Expand runtime.codex process-kill evidence around uncommitted owner cuts.

This is ordinary reviewed source. It deliberately has no dependency on a Git
history object and never executes code loaded through `git cat-file`.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def fixture(text: str) -> str:
    if '"dispatch_uncommitted"' in text:
        return text
    old = '''    match mode.as_str() {
        "dispatch" => dispatch(&store, &marker)?,
        "abort" => abort(&store, &marker)?,
        _ => anyhow::bail!("unsupported fixture mode"),
    }
'''
    new = '''    match mode.as_str() {
        "dispatch" => dispatch(&store, &marker)?,
        "dispatch_uncommitted" => dispatch_uncommitted(&store, &marker)?,
        "abort" => abort(&store, &marker)?,
        "abort_uncommitted" => abort_uncommitted(&store, &marker)?,
        _ => anyhow::bail!("unsupported fixture mode"),
    }
'''
    if old not in text:
        raise RuntimeError("process crash fixture mode anchor absent")
    text = text.replace(old, new, 1)

    anchor = '''fn abort(store_path: &Path, marker_path: &Path) -> Result<()> {
'''
    addition = r'''fn dispatch_uncommitted(store_path: &Path, marker_path: &Path) -> Result<()> {
    let now = now_ms()?;
    let mut owner = AgentRunCoordinator::open_durable(composition(), store_path.to_path_buf())?;
    let admitted = owner.start_run(now, snapshot(now)?)?;
    owner.persist()?;
    let attached = owner.attach_context(now + 1, admitted.revision, attachment(now)?)?;
    owner.persist()?;
    let dispatch_binding_digest = digest(b"process-crash-uncommitted-dispatch");
    let nonce = random_nonce()?;
    let commitment_digest = framed_abort_digest(
        COMMITMENT_DOMAIN,
        RUN_ID,
        &dispatch_binding_digest,
        &nonce,
        None,
    );
    let proof_digest = framed_abort_digest(
        PROOF_DOMAIN,
        RUN_ID,
        &dispatch_binding_digest,
        &nonce,
        Some(ABORT_REASON),
    );
    let dispatched = owner.mark_dispatched_bound(
        now + 2,
        RUN_ID,
        attached.revision,
        dispatch_binding_digest.clone(),
        commitment_digest.clone(),
    )?;
    // Deliberately do not persist the candidate. The marker proves that the
    // child reached the pre-fsync cut before the parent sends SIGKILL.
    write_marker(
        marker_path,
        &CrashMarkerV1 {
            schema_version: 1,
            dispatch_binding_digest,
            dispatch_revision: dispatched.revision,
            abort_nonce_hex: nonce.iter().map(|byte| format!("{byte:02x}")).collect(),
            commitment_digest,
            proof_digest,
        },
    )
}

''' + anchor
    if anchor not in text:
        raise RuntimeError("process crash abort anchor absent")
    text = text.replace(anchor, addition, 1)

    anchor = '''fn composition() -> RuntimeComposition {
'''
    addition = r'''fn abort_uncommitted(store_path: &Path, marker_path: &Path) -> Result<()> {
    let marker: CrashMarkerV1 = serde_json::from_slice(
        &std::fs::read(marker_path).context("read dispatch marker")?,
    )
    .context("decode dispatch marker")?;
    let mut owner = AgentRunCoordinator::open_durable(composition(), store_path.to_path_buf())?;
    owner.abort_before_effect(
        RUN_ID,
        marker.dispatch_revision,
        &marker.dispatch_binding_digest,
        &marker.abort_nonce_hex,
        &marker.proof_digest,
        ABORT_REASON,
    )?;
    // Deliberately stop before persistence. Recovery must expose the preceding
    // Dispatched owner state, not the process-local abort candidate.
    write_marker(&marker_path.with_extension("abort-uncommitted"), &marker)
}

''' + anchor
    if anchor not in text:
        raise RuntimeError("process crash composition anchor absent")
    return text.replace(anchor, addition, 1)


def tests(text: str) -> str:
    marker = "real_sigkill_before_dispatch_and_abort_fsync_replays_only_committed_owner_state"
    if marker in text:
        return text
    anchor = '''fn spawn_fixture(mode: &str, store: &Path, marker: &Path) -> Child {
'''
    addition = r'''#[test]
fn real_sigkill_before_dispatch_and_abort_fsync_replays_only_committed_owner_state() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = directory.path().join("agent-runs.json");
    let marker = directory.path().join("dispatch-uncommitted.json");

    let mut child = spawn_fixture("dispatch_uncommitted", &store, &marker);
    wait_for_file(&marker, &mut child);
    child.kill().expect("kill pre-dispatch-fsync fixture");
    child.wait().expect("wait pre-dispatch-fsync fixture");

    let recovered = AgentRunCoordinator::open_durable(composition(), store.clone())
        .expect("recover context-attached owner");
    let receipt = recovered.run(RUN_ID).expect("context-attached run");
    assert_eq!(receipt.phase, RunPhase::ContextAttached);
    assert!(receipt.dispatch_binding_digest.is_none());
    assert!(receipt.pre_effect_abort_commitment_digest.is_none());
    drop(recovered);

    // Use a distinct committed store so the second fixture creates the exact
    // run from an empty durable owner rather than colliding with the preceding
    // context-attached pre-fsync scenario.
    let committed_store = directory.path().join("agent-runs-committed.json");
    let committed_marker = directory.path().join("dispatch-committed.json");
    let mut child = spawn_fixture("dispatch", &committed_store, &committed_marker);
    wait_for_file(&committed_marker, &mut child);
    child.kill().expect("kill committed dispatch fixture");
    child.wait().expect("wait committed dispatch fixture");

    let abort_cut = committed_marker.with_extension("abort-uncommitted");
    let mut child = spawn_fixture(
        "abort_uncommitted",
        &committed_store,
        &committed_marker,
    );
    wait_for_file(&abort_cut, &mut child);
    child.kill().expect("kill pre-abort-fsync fixture");
    child.wait().expect("wait pre-abort-fsync fixture");

    let recovered = AgentRunCoordinator::open_durable(composition(), committed_store)
        .expect("recover dispatched owner after uncommitted abort");
    let receipt = recovered.run(RUN_ID).expect("dispatched run");
    assert_eq!(receipt.phase, RunPhase::Dispatched);
    assert!(receipt.pre_effect_abort_proof_digest.is_none());
}

#[test]
fn durable_owner_rejects_generation_rollover_and_ignores_unpublished_temp_state() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = directory.path().join("agent-runs.json");
    let marker = directory.path().join("dispatch.json");
    let mut child = spawn_fixture("dispatch", &store, &marker);
    wait_for_file(&marker, &mut child);
    child.kill().expect("kill dispatch fixture");
    child.wait().expect("wait dispatch fixture");

    std::fs::write(store.with_extension("unpublished.tmp"), b"not a committed owner snapshot")
        .expect("write unrelated unpublished temp state");
    let recovered = AgentRunCoordinator::open_durable(composition(), store.clone())
        .expect("recover committed owner while temp state exists");
    assert_eq!(recovered.run(RUN_ID).unwrap().phase, RunPhase::Dispatched);
    drop(recovered);

    let mut rolled = composition();
    rolled.agentd_generation += 1;
    assert!(AgentRunCoordinator::open_durable(rolled, store).is_err());
}

''' + anchor
    if anchor not in text:
        raise RuntimeError("process crash test spawn anchor absent")
    return text.replace(anchor, addition, 1)


def main() -> None:
    rewrite(
        "codex-rs/hepta-agentd/src/bin/runtime-codex-crash-fixture.rs",
        fixture,
    )
    rewrite("codex-rs/hepta-agentd/tests/runtime_codex_process_crash.rs", tests)


if __name__ == "__main__":
    main()
