#![cfg(unix)]

use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agentd::AgentRunCoordinator;
use codex_hepta_agentd::RunPhase;
use codex_hepta_agentd::RuntimeComposition;
use serde::Deserialize;

const RUN_ID: &str = "run:process-crash";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CrashMarkerV1 {
    schema_version: u32,
    dispatch_binding_digest: String,
    dispatch_revision: u64,
    abort_nonce_hex: String,
    commitment_digest: String,
    proof_digest: String,
}

#[test]
fn real_sigkill_restart_preserves_bound_dispatch_and_abort_proof() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = directory.path().join("agent-runs.json");
    let marker = directory.path().join("dispatch.json");
    let aborted = marker.with_extension("aborted");

    let mut child = spawn_fixture("dispatch", &store, &marker);
    wait_for_file(&marker, &mut child);
    child.kill().expect("kill dispatch fixture");
    child.wait().expect("wait dispatch fixture");

    let marker_value: CrashMarkerV1 =
        serde_json::from_slice(&std::fs::read(&marker).expect("read marker"))
            .expect("decode marker");
    assert_eq!(marker_value.schema_version, 1);
    assert_eq!(marker_value.abort_nonce_hex.len(), 64);
    let recovered = AgentRunCoordinator::open_durable(composition(), store.clone())
        .expect("recover dispatched owner");
    let dispatched = recovered.run(RUN_ID).expect("dispatched run");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
    assert_eq!(dispatched.revision, marker_value.dispatch_revision);
    assert_eq!(
        dispatched.dispatch_binding_digest.as_deref(),
        Some(marker_value.dispatch_binding_digest.as_str())
    );
    assert_eq!(
        dispatched.pre_effect_abort_commitment_digest.as_deref(),
        Some(marker_value.commitment_digest.as_str())
    );
    assert!(dispatched.pre_effect_abort_proof_digest.is_none());
    drop(recovered);

    let mut child = spawn_fixture("abort", &store, &marker);
    wait_for_file(&aborted, &mut child);
    child.kill().expect("kill abort fixture");
    child.wait().expect("wait abort fixture");

    let recovered =
        AgentRunCoordinator::open_durable(composition(), store).expect("recover aborted owner");
    let receipt = recovered.run(RUN_ID).expect("aborted run");
    assert_eq!(receipt.phase, RunPhase::AbortedBeforeEffect);
    assert_eq!(
        receipt.dispatch_binding_digest.as_deref(),
        Some(marker_value.dispatch_binding_digest.as_str())
    );
    assert_eq!(
        receipt.pre_effect_abort_commitment_digest.as_deref(),
        Some(marker_value.commitment_digest.as_str())
    );
    assert_eq!(
        receipt.pre_effect_abort_proof_digest.as_deref(),
        Some(marker_value.proof_digest.as_str())
    );
    assert!(!receipt.terminal_observed);
}

#[test]
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

    // Establish one committed dispatch, then kill a successor before the abort
    // candidate is persisted. Recovery must retain Dispatched with no proof.
    let committed_store = directory.path().join("agent-runs-committed.json");
    let committed_marker = directory.path().join("dispatch-committed.json");
    let mut child = spawn_fixture("dispatch", &committed_store, &committed_marker);
    wait_for_file(&committed_marker, &mut child);
    child.kill().expect("kill committed dispatch fixture");
    child.wait().expect("wait committed dispatch fixture");

    let abort_cut = committed_marker.with_extension("abort-uncommitted");
    let mut child = spawn_fixture("abort_uncommitted", &committed_store, &committed_marker);
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

    std::fs::write(
        store.with_extension("unpublished.tmp"),
        b"not a committed owner snapshot",
    )
    .expect("write unrelated unpublished temp state");
    let recovered = AgentRunCoordinator::open_durable(composition(), store.clone())
        .expect("recover committed owner while temp state exists");
    assert_eq!(recovered.run(RUN_ID).unwrap().phase, RunPhase::Dispatched);
    drop(recovered);

    let mut rolled = composition();
    rolled.agentd_generation += 1;
    assert!(AgentRunCoordinator::open_durable(rolled, store).is_err());
}

fn spawn_fixture(mode: &str, store: &Path, marker: &Path) -> Child {
    Command::new(env!("CARGO_BIN_EXE_runtime-codex-crash-fixture"))
        .arg(mode)
        .arg(store)
        .arg(marker)
        .spawn()
        .expect("spawn crash fixture")
}

fn wait_for_file(path: &Path, child: &mut Child) {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if path.is_file() {
            return;
        }
        if let Some(status) = child.try_wait().expect("poll child") {
            panic!("crash fixture exited before marker publication: {status}");
        }
        assert!(Instant::now() < deadline, "timed out waiting for {path:?}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent:process-crash".to_string(),
        supervisor_generation: 41,
        agentd_generation: 41,
        configuration_digest: Digest32::of_bytes(b"process-crash-configuration").to_string(),
        ports_digest: Digest32::of_bytes(b"process-crash-ports").to_string(),
        max_active_runs: 4,
    }
}
