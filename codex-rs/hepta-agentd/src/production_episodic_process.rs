//! MEM15: independent importer exit, then the real native worker CLI.
//! Capture-only process evidence; public fixture authorization, no benefit score.

use std::error::Error;
use std::ffi::OsString;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use pretty_assertions::assert_eq;
use serde::Serialize;

use super::FixtureTasks;
use super::PROMPT;
use super::QUERY;
use super::authority;
use super::diagnostic;
use super::write_receipt;

#[path = "production_episodic_process_child.rs"]
mod child;

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Mode {
    Attach,
    ReaderOff,
    Withhold,
    Tombstone,
}

impl Mode {
    pub(super) fn from_environment() -> Result<Self> {
        if std::env::var("HEPTA_MEM_NATIVE_PHASE")?.as_str() != "capture" {
            return Err("MEM15 only admits capture; no generation profile exists".into());
        }
        match std::env::var("HEPTA_MEM_NATIVE_INTERVENTION")?.as_str() {
            "attach" => Ok(Self::Attach),
            "reader-off" => Ok(Self::ReaderOff),
            "withhold" => Ok(Self::Withhold),
            "tombstone" => Ok(Self::Tombstone),
            _ => Err("MEM15 requires attach, reader-off, withhold, or tombstone".into()),
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "MEM15 fixture: requires precompiled A/C executables and a separately frozen capture-only adapter; no model generation authorized"]
async fn episodic_native_a_exit_capture() -> Result<()> {
    let mode = Mode::from_environment()?;
    super::run_fixture_with_process(diagnostic::Mode::CaptureAttach, Some(mode)).await
}

pub(super) struct Run<'a> {
    pub(super) mode: Mode,
    pub(super) identity: &'a crate::AgentdIdentity,
    pub(super) host: &'a Arc<crate::AgentdProductionWriterHost>,
    pub(super) output: &'a Path,
    pub(super) retained: &'a Path,
    pub(super) reads: Arc<AtomicUsize>,
    pub(super) model: &'a str,
    pub(super) request_id: &'a str,
    pub(super) snapshot: &'a str,
    pub(super) fact: &'a str,
    pub(super) tasks: &'a mut FixtureTasks,
}

pub(super) async fn run(run: Run<'_>) -> Result<()> {
    let Run {
        mode,
        identity,
        host,
        output,
        retained,
        reads,
        model,
        request_id,
        snapshot,
        fact,
        tasks,
    } = run;
    let importer = std::env::current_exe()?;
    let worker = codex_utils_cargo_bin::cargo_bin("hepta-infer-worker")?;
    let args = [
        child::importer_test_name(),
        "--ignored".into(),
        "--exact".into(),
        "--nocapture".into(),
        "--test-threads=1".into(),
    ]
    .map(OsString::from);
    let a = child::observe(
        &output.join("A"),
        &importer,
        &args,
        &[
            (
                "HEPTA_MEM15_IMPORT_CHILD".into(),
                "one-native-import-v1".into(),
            ),
            (
                "HEPTA_MEM15_AGENTD_SOCKET".into(),
                identity.control_socket.clone().into_os_string(),
            ),
            (
                "HEPTA_MEM15_AGENT_ID".into(),
                identity.agent_id.to_string().into(),
            ),
            ("HEPTA_MEM15_GENERATION".into(), "1".into()),
        ],
        snapshot.as_bytes(),
        Duration::from_secs(10),
    )
    .await?;
    let ack = a.import_ack(snapshot)?;
    write_receipt(output, "A_ACK.json", &ack)?;
    // Only an observed successful OS wait plus the exact single import ack may
    // cross this boundary. A timeout/lost ack cannot start C or another A.
    let client = crate::AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        /*spawn_generation*/ 1,
    )?;
    let withdrawal = if mode == Mode::Tombstone {
        let context = client.cognitive_context(QUERY.into(), /*limit*/ 4).await?;
        let target = context
            .items
            .iter()
            .find(|item| item.content == fact)
            .ok_or("native target missing")?;
        Some(diagnostic::Withdrawal {
            host: host.clone(),
            agent_id: identity.agent_id.clone(),
            memory_id: target.memory_id.clone(),
            revision: target.revision,
        })
    } else {
        None
    };
    let cut = host.writer().recovery_anchor().await?;
    let before = reads.load(Ordering::SeqCst);
    let policy = if mode == Mode::ReaderOff {
        authority::SourceReadPolicy::ReaderOff
    } else {
        authority::SourceReadPolicy::Context
    };
    let (config, issuer) = authority::start_config(
        &retained.join("mem15-final-use"),
        identity.agent_id.to_string(),
        reads.clone(),
        before,
        policy,
        withdrawal,
    )
    .await
    .map_err(|error| error.to_string())?;
    tasks.handles.push(issuer.abort_handle());
    // No verifier/state owner is opened in the parent. C opens this public config
    // itself. The fixture signing bytes are not passed through argv/env/stdin.
    let config_path = output.join("FINAL_USE_PUBLIC.json");
    write_receipt(
        output,
        "FINAL_USE_PUBLIC.json",
        &serde_json::json!({
            "issuer_socket": config.issuer_socket, "issuer_uid": config.issuer_uid,
            "signer_id": config.signer_id, "verifying_key": config.verifying_key,
            "authority_state_dir": config.authority_state_dir, "authority_epoch": config.authority_epoch,
            "revocation_revision": config.revocation_revision, "revoked_grant_ids": config.revoked_grant_ids,
            "issuer_timeout_ms": config.issuer_timeout_ms,
        }),
    )?;
    let journal = output.join("C.journal");
    let mut args = vec![
        "--profile".into(),
        "native-app-server".into(),
        "--agentd-socket".into(),
        identity.control_socket.clone().into_os_string(),
        "--agent-id".into(),
        identity.agent_id.to_string().into(),
        "--generation".into(),
        "1".into(),
        "--model".into(),
        model.into(),
        "--journal".into(),
        journal.clone().into_os_string(),
        "--request-id".into(),
        request_id.into(),
        "--maximum-in-flight".into(),
        "1".into(),
        "--final-use-authority-config".into(),
        config_path.clone().into_os_string(),
        "--timeout-ms".into(),
        "180000".into(),
    ];
    if mode != Mode::ReaderOff {
        args.extend([
            "--context-query".into(),
            QUERY.into(),
            "--context-delivery".into(),
            if mode == Mode::Withhold {
                "withhold".into()
            } else {
                "attach".into()
            },
        ]);
    }
    write_receipt(
        output,
        "DISPATCH_INPUT.json",
        &serde_json::json!({
            "request_id": request_id, "mode": mode, "source_checks_before": before, "owner_cut": cut,
            "A_exit": a.receipt, "A_ack": ack, "public_config": child::pin(&config_path)?,
            "profile": "ExplicitContextOnly", "maximum_attempts": 1, "retention_off_implemented": false,
            "full_memory_off_demonstrated": false, "requires_capture_adapter_binding": true,
        }),
    )?;
    let c = child::observe(
        &output.join("C"),
        &worker,
        &args,
        &[],
        PROMPT.as_bytes(),
        Duration::from_secs(180),
    )
    .await?;
    let issuer_result = issuer
        .await
        .map_err(|error| error.to_string())
        .and_then(|result| result.map_err(|error| error.to_string()));
    write_receipt(output, "FIXTURE_AUTHORITY.json", &issuer_result)?;
    let after = reads.load(Ordering::SeqCst);
    let cut_after = host.writer().recovery_anchor().await?;
    let control = DurableInferenceControl::open(&journal, /*capacity*/ 16_384)?;
    let record = control.native_record(request_id).cloned();
    let terminal = record
        .as_ref()
        .and_then(|item| item.observation.as_ref())
        .is_some_and(|item| item.succeeded() && item.terminal_observed);
    let revoked = c
        .stderr
        .contains("canonical episodic head changed outside the bridge");
    let ordered = a.receipt["exited_at_unix_ns"]
        .as_u64()
        .zip(c.receipt["started_at_unix_ns"].as_u64())
        .is_some_and(|(a, c)| a <= c);
    write_receipt(
        output,
        "RESULT.json",
        &serde_json::json!({
            "schema": "hepta.mem15.native-a-exit-result.v1", "mode": mode, "request_id": request_id,
            "A_exit": a.receipt, "C_exit": c.receipt, "A_exit_precedes_C_start": ordered,
            "A_importer_process_exits_before_C": ordered && a.success(),
            "A_is_deterministic_import_not_model_learning": true, "owner_remains_alive": true,
            "durable_record": record, "source_reads_before": before, "source_reads_after": after,
            "owner_cut_before": cut, "owner_cut_after": cut_after, "terminal_observed": terminal,
            "native_revocation_rejected": revoked, "physical_provider_request_count": null,
            "model_generation_count": null, "requires_adapter_evidence": true,
            "fixture_only": true, "production_authenticated": false,
            "full_memory_off_demonstrated": false, "retention_off_implemented": false,
            "scientific_acceptance": "HOLD", "unseen_source_benefit_evaluated": false,
        }),
    )?;
    issuer_result?;
    assert!(ordered && a.success());
    assert_ne!(a.receipt["pid"], a.receipt["parent_pid"]);
    assert_ne!(c.receipt["pid"], c.receipt["parent_pid"]);
    assert!(
        !terminal && !c.success(),
        "capture-only cannot be a successful generation"
    );
    assert_eq!(c.receipt["timed_out"], false);
    if mode == Mode::Tombstone {
        assert!(revoked);
        assert_ne!(cut_after, cut);
        assert_eq!(after, before + 3);
    } else {
        assert_eq!(cut_after, cut);
        assert_eq!(after, before + if mode == Mode::ReaderOff { 0 } else { 4 });
        let dispatch = record
            .as_ref()
            .and_then(|item| item.dispatch.as_ref())
            .ok_or("original native dispatch missing")?;
        assert_eq!(
            dispatch.owner_context_digest.is_none(),
            mode == Mode::ReaderOff
        );
        assert!(!dispatch.thread_id.is_empty());
    }
    Ok(())
}
