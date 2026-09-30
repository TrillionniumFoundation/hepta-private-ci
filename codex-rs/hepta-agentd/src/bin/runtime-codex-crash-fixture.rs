//! runtime.codex real process crash fixture.
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
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agentd::AgentRunCoordinator;
use codex_hepta_agentd::ContextAttachment;
use codex_hepta_agentd::RunSnapshot;
use codex_hepta_agentd::RuntimeComposition;
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
    let store = arguments
        .next()
        .map(PathBuf::from)
        .context("missing store path")?;
    let marker = arguments
        .next()
        .map(PathBuf::from)
        .context("missing marker path")?;
    if arguments.next().is_some() {
        anyhow::bail!("unexpected fixture argument");
    }
    match mode.as_str() {
        "dispatch" => dispatch(&store, &marker)?,
        "dispatch_uncommitted" => dispatch_uncommitted(&store, &marker)?,
        "abort" => abort(&store, &marker)?,
        "abort_uncommitted" => abort_uncommitted(&store, &marker)?,
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

fn dispatch_uncommitted(store_path: &Path, marker_path: &Path) -> Result<()> {
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

fn abort(store_path: &Path, marker_path: &Path) -> Result<()> {
    let marker: CrashMarkerV1 =
        serde_json::from_slice(&std::fs::read(marker_path).context("read dispatch marker")?)
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

fn abort_uncommitted(store_path: &Path, marker_path: &Path) -> Result<()> {
    let marker: CrashMarkerV1 =
        serde_json::from_slice(&std::fs::read(marker_path).context("read dispatch marker")?)
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
    output.extend_from_slice(
        &u64::try_from(value.len())
            .expect("bounded fixture field")
            .to_be_bytes(),
    );
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
