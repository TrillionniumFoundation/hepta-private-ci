#!/usr/bin/env python3
"""Add a real child-process kill/restart test for the durable Agentd owner."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def cargo(text: str) -> str:
    block = '''
[[bin]]
name = "runtime-codex-crash-fixture"
path = "src/bin/runtime-codex-crash-fixture.rs"
test = false
'''
    if 'name = "runtime-codex-crash-fixture"' not in text:
        marker = '''[[bin]]
name = "hepta-agentd-browser"
path = "src/bin/hepta-agentd-browser.rs"
test = false
'''
        if marker not in text:
            raise RuntimeError("Agentd browser bin marker missing")
        text = text.replace(marker, marker + block, 1)
    return text


def write_fixture() -> None:
    path = ROOT / "codex-rs/hepta-agentd/src/bin/runtime-codex-crash-fixture.rs"
    if path.exists() and "runtime.codex real process crash fixture" in path.read_text(encoding="utf-8"):
        return
    path.write_text(r'''//! runtime.codex real process crash fixture.
//!
//! This binary is invoked only by the repository qualification test. It
//! publishes one durable transition, fsyncs a marker, and deliberately remains
//! alive so the parent can deliver SIGKILL at a known post-commit boundary.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_agentd::AgentRunCoordinator;
use codex_hepta_agentd::ContextAttachment;
use codex_hepta_agentd::RunSnapshot;
use codex_hepta_agentd::RuntimeComposition;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const RUN_ID: &str = "run:process-crash";
const ABORT_REASON: &str = "qualification process killed after abort commit";
const COMMITMENT_DOMAIN: &[u8] = b"hepta.runtime.codex.pre-effect-abort.commitment.v1";
const PROOF_DOMAIN: &[u8] = b"hepta.runtime.codex.pre-effect-abort.proof.v1";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CrashMarkerV1 {
    schema_version: u32,
    dispatch_binding_digest: String,
    dispatch_revision: u64,
    abort_nonce_hex: String,
    commitment_digest: String,
    proof_digest: String,
}

fn main() -> Result<()> {
    let mut arguments = std::env::args_os().skip(1);
    let mode = arguments
        .next()
        .and_then(|value| value.into_string().ok())
        .context("missing fixture mode")?;
    let store = arguments.next().map(PathBuf::from).context("missing store path")?;
    let marker = arguments
        .next()
        .map(PathBuf::from)
        .context("missing marker path")?;
    if arguments.next().is_some() {
        anyhow::bail!("unexpected fixture argument");
    }
    match mode.as_str() {
        "dispatch" => dispatch(&store, &marker)?,
        "abort" => abort(&store, &marker)?,
        _ => anyhow::bail!("unsupported fixture mode"),
    }
    loop {
        thread::sleep(Duration::from_secs(60));
    }
}

fn dispatch(store_path: &Path, marker_path: &Path) -> Result<()> {
    let now = now_ms()?;
    let mut owner = AgentRunCoordinator::open_durable(composition(), store_path.to_path_buf())?;
    let admitted = owner.start_run(now, snapshot(now)?)?;
    owner.persist()?;
    let attached = owner.attach_context(now + 1, admitted.revision, attachment(now)?)?;
    owner.persist()?;
    let dispatch_binding_digest = digest(b"process-crash-bound-dispatch");
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
    owner.persist()?;
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

fn abort(store_path: &Path, marker_path: &Path) -> Result<()> {
    let marker: CrashMarkerV1 = serde_json::from_slice(
        &std::fs::read(marker_path).context("read dispatch marker")?,
    )
    .context("decode dispatch marker")?;
    if marker.schema_version != 1 {
        anyhow::bail!("unsupported marker schema");
    }
    let mut owner = AgentRunCoordinator::open_durable(composition(), store_path.to_path_buf())?;
    owner.abort_before_effect(
        RUN_ID,
        marker.dispatch_revision,
        &marker.dispatch_binding_digest,
        &marker.abort_nonce_hex,
        &marker.proof_digest,
        ABORT_REASON,
    )?;
    owner.persist()?;
    let abort_marker = marker_path.with_extension("aborted");
    write_marker(&abort_marker, &marker)
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent:process-crash".to_string(),
        supervisor_generation: 41,
        agentd_generation: 41,
        configuration_digest: digest(b"process-crash-configuration"),
        ports_digest: digest(b"process-crash-ports"),
        max_active_runs: 4,
    }
}

fn snapshot(now: u64) -> Result<RunSnapshot> {
    Ok(RunSnapshot {
        run_id: RUN_ID.to_string(),
        request_digest: digest(b"request"),
        objective_digest: digest(b"objective"),
        body_digest: digest(b"body"),
        artifact_set_digest: digest(b"artifacts"),
        authority_epoch: 7,
        generation: 41,
        fence_digest: digest(b"fence"),
        deadline_ms: now.checked_add(3_600_000).context("deadline overflow")?,
    })
}

fn attachment(now: u64) -> Result<ContextAttachment> {
    let snapshot = snapshot(now)?;
    Ok(ContextAttachment {
        run_id: snapshot.run_id,
        request_digest: snapshot.request_digest,
        objective_digest: snapshot.objective_digest,
        body_digest: snapshot.body_digest,
        artifact_set_digest: snapshot.artifact_set_digest,
        authority_epoch: snapshot.authority_epoch,
        generation: snapshot.generation,
        fence_digest: snapshot.fence_digest,
        deadline_ms: snapshot.deadline_ms,
        context_digest: digest(b"context"),
        compilation_receipt_digest: digest(b"compilation-receipt"),
    })
}

fn random_nonce() -> Result<[u8; 32]> {
    let mut nonce = [0_u8; 32];
    File::open("/dev/urandom")
        .context("open operating-system random source")?
        .read_exact(&mut nonce)
        .context("read operating-system random source")?;
    Ok(nonce)
}

fn digest(value: &[u8]) -> String {
    Digest32::of_bytes(value).to_string()
}

fn framed_abort_digest(
    domain: &[u8],
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: Option<&str>,
) -> String {
    let mut bytes = Vec::new();
    push_part(&mut bytes, domain);
    push_part(&mut bytes, run_id.as_bytes());
    push_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_part(&mut bytes, nonce);
    if let Some(reason) = reason {
        push_part(&mut bytes, reason.as_bytes());
    }
    digest(&bytes)
}

fn push_part(output: &mut Vec<u8>, value: &[u8]) {
    output.extend_from_slice(&u64::try_from(value.len()).expect("bounded fixture field").to_be_bytes());
    output.extend_from_slice(value);
}

fn write_marker(path: &Path, marker: &CrashMarkerV1) -> Result<()> {
    let parent = path.parent().context("marker path has no parent")?;
    std::fs::create_dir_all(parent).context("create marker parent")?;
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    let bytes = serde_json::to_vec(marker).context("encode marker")?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .context("create marker temp")?;
    file.write_all(&bytes).context("write marker")?;
    file.sync_all().context("sync marker")?;
    std::fs::rename(&temporary, path).context("publish marker")?;
    File::open(parent)
        .context("open marker parent")?
        .sync_all()
        .context("sync marker parent")?;
    Ok(())
}

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("clock before epoch")?
            .as_millis(),
    )?)
}
''', encoding="utf-8")


def write_test() -> None:
    path = ROOT / "codex-rs/hepta-agentd/tests/runtime_codex_process_crash.rs"
    if path.exists() and "real_sigkill_restart_preserves_bound_dispatch_and_abort_proof" in path.read_text(encoding="utf-8"):
        return
    path.write_text(r'''#![cfg(unix)]

use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agentd::AgentRunCoordinator;
use codex_hepta_agentd::RunPhase;
use codex_hepta_agentd::RuntimeComposition;
use codex_hepta_types::Digest32;
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

    let recovered = AgentRunCoordinator::open_durable(composition(), store)
        .expect("recover aborted owner");
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
''', encoding="utf-8")


def main() -> None:
    rewrite("codex-rs/hepta-agentd/Cargo.toml", cargo)
    write_fixture()
    write_test()


if __name__ == "__main__":
    main()
