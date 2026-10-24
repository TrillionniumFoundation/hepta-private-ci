//! Fixed development probe through the existing Agentd runtime/control path.
//! The independently retained source cut is real; its external authority issuer
//! is controlled qualification input, not a production supervisor grant.

mod native_memory_support;

use codex_hepta_agent_protocol::MemoryCellReadIngress;
use codex_hepta_agent_protocol::MemoryCellReadState;
use codex_hepta_agent_protocol::MemoryCellRole;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::NativeMemoryModelConfigV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::*;
use native_memory_support::*;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    anyhow::ensure!(
        args.len() >= 2,
        "prepare ROOT | run ROOT MODEL_CONFIG SOURCE_DOCUMENT ANCHOR_SHA256"
    );
    let root = std::path::absolute(&args[1])?;
    match args[0].as_str() {
        "prepare" if args.len() == 2 => prepare(&root).await,
        "run" if args.len() == 5 => {
            let result = probe(&root, Path::new(&args[2]), Path::new(&args[3]), &args[4]).await;
            if let Err(error) = &result {
                retain(
                    &root.join("failure.json"),
                    &serde_json::json!({"error": format!("{error:#}"), "production_qualified": false}),
                )?;
            }
            result
        }
        _ => anyhow::bail!("closed probe arguments required"),
    }
}

async fn probe(
    root: &Path,
    model_config: &Path,
    document_path: &Path,
    anchor_sha256: &str,
) -> anyhow::Result<()> {
    let (config, registry) = config(root)?;
    let home = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
        &config.identity().home_root,
    )?;
    codex_utils_home_dir::set_process_codex_home_override(home)?;
    let socket = config.identity().control_socket.clone();
    let (host, authority_withdrawn) = open_host(root, &config, anchor_sha256).await?;
    let access = CognitiveAccess::agent_private(owner()?);
    let document_bytes = std::fs::read(document_path)?;
    let mut document: MemoryCellDocumentV1 = serde_json::from_slice(&document_bytes)?;
    document.validate()?;
    let initial_source = source(document_bytes, "ci-import:covariance-diagnostics")?;
    let production = host
        .remember_with_kg(
            &access,
            &initial_source,
            &MemoryDraft {
                stable_key: document.key.stable_key()?,
                revision: revision(&initial_source)?,
            },
            &KgFactSetDraft::default(),
        )
        .await?;
    retain(&root.join("production-source.json"), &production)?;
    let claim = claim(&document, production)?;
    retain(&root.join("hnmf-event.json"), &claim.event)?;
    let model: NativeMemoryModelConfigV1 = serde_json::from_slice(&std::fs::read(model_config)?)?;
    let cell = host
        .native_memory_cell(
            access.clone(),
            document.key.clone(),
            claim.clone(),
            model.clone(),
        )
        .await?;
    let mut forged = claim.clone();
    forged.production.authority_grant_digest = Sha256Digest::for_bytes(b"forged-source-authority");
    forged.production.receipt_sha256 = forged.production.compute_receipt_sha256();
    anyhow::ensure!(
        host.native_memory_cell(access.clone(), document.key.clone(), forged, model)
            .await
            .is_err(),
        "self-consistent forged source admitted"
    );
    let config = config
        .with_production_writer_host(Arc::clone(&host))?
        .with_native_memory_cell(Arc::clone(&cell))?;
    let daemon = tokio::spawn(codex_hepta_agentd::run(
        config,
        codex_arg0::Arg0DispatchPaths::default(),
    ));
    let client = AgentdClient::new(socket, owner()?, 1)?;
    let until = tokio::time::Instant::now() + Duration::from_secs(120);
    loop {
        anyhow::ensure!(
            !daemon.is_finished(),
            "actual daemon exited before readiness"
        );
        if client
            .health()
            .await
            .is_ok_and(|health| health.promotion_ready)
        {
            break;
        }
        anyhow::ensure!(
            tokio::time::Instant::now() < until,
            "actual daemon did not initialize App Server"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    // Controlled supervisor promotion after the real App Server probe succeeds.
    registry.compare_and_transition(&owner()?, 1, AgentLifecycle::Running)?;
    loop {
        if client.health().await.is_ok_and(|health| health.ready) {
            break;
        }
        anyhow::ensure!(
            tokio::time::Instant::now() < until,
            "actual daemon did not become ready"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    retain(&root.join("daemon-health.json"), &client.health().await?)?;
    anyhow::ensure!(
        client
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|c| c.id == "memory.cell.native"),
        "native capability absent"
    );
    let ingress = MemoryCellReadIngress {
        invocation_id: "native:real:1".to_string(),
        role: MemoryCellRole::Procedural,
        entity: document.key.entity.clone(),
        relation: document.key.relation.clone(),
        deadline_unix_ms: now_ms()? + 180_000,
    };
    let mut wrong_key = ingress.clone();
    wrong_key.invocation_id = "native:wrong-key".to_string();
    wrong_key.entity.push_str(" unknown");
    anyhow::ensure!(
        client.memory_cell_read_start(wrong_key).await.is_err(),
        "wrong key admitted"
    );
    let mut wrong_role = ingress.clone();
    wrong_role.invocation_id = "native:wrong-role".to_string();
    wrong_role.role = MemoryCellRole::Semantic;
    anyhow::ensure!(
        client.memory_cell_read_start(wrong_role).await.is_err(),
        "wrong role admitted"
    );
    anyhow::ensure!(
        cell.backend_dispatch_attempts() == 0,
        "preflight refusal dispatched backend"
    );
    retain(
        &root.join("started.json"),
        &client.memory_cell_read_start(ingress.clone()).await?,
    )?;
    let result = loop {
        let status = client
            .memory_cell_read_status(ingress.invocation_id.clone())
            .await?;
        if status.state != MemoryCellReadState::Running {
            break status;
        }
        anyhow::ensure!(
            now_ms()? < ingress.deadline_unix_ms,
            "native job deadline elapsed"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    };
    retain(&root.join("raw-result.json"), &result)?;
    anyhow::ensure!(
        result.state == MemoryCellReadState::Succeeded,
        "actual native job refused: {:?}",
        result.refusal
    );
    anyhow::ensure!(
        cell.backend_dispatch_attempts() == 1,
        "unexpected actual backend attempt count"
    );
    anyhow::ensure!(
        client
            .memory_cell_read_start(ingress.clone())
            .await
            .is_err(),
        "completed nonce replay admitted"
    );
    authority_withdrawn.store(true, Ordering::SeqCst);
    let mut denied = ingress.clone();
    denied.invocation_id = "native:authority-revoked".to_string();
    anyhow::ensure!(
        client.memory_cell_read_start(denied).await.is_err(),
        "revoked authority admitted"
    );
    authority_withdrawn.store(false, Ordering::SeqCst);
    // Controlled revision changes test the fence; they are not new CI labels.
    let expected_value = document.value.clone();
    document.value = "controlled-revision-for-admission-fence".to_string();
    let correction_source = source(
        serde_json::to_vec(&document)?,
        "ci-import:controlled-correction",
    )?;
    let correction = host
        .correct_with_kg(
            &access,
            &claim.production.write.memory.id.memory_id,
            1,
            &correction_source,
            &revision(&correction_source)?,
            &KgFactSetDraft::default(),
        )
        .await?;
    retain(&root.join("controlled-correction.json"), &correction)?;
    anyhow::ensure!(
        client
            .memory_cell_read_status(ingress.invocation_id.clone())
            .await
            .is_err(),
        "cached stale result escaped correction fence"
    );
    let mut denied = ingress.clone();
    denied.invocation_id = "native:corrected-old-adapter".to_string();
    anyhow::ensure!(
        client.memory_cell_read_start(denied).await.is_err(),
        "old trained root escaped correction fence"
    );
    let withdrawal_source = source(
        b"controlled trial withdrawal".to_vec(),
        "ci-import:withdrawal",
    )?;
    let withdrawal = host
        .forget_with_kg(
            &access,
            &claim.production.write.memory.id.memory_id,
            2,
            &withdrawal_source,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "controlled trial withdrawal".to_string(),
                valid_from_unix_seconds: withdrawal_source.observed_at_unix_seconds,
                citations: vec![],
            },
        )
        .await?;
    retain(&root.join("withdrawal.json"), &withdrawal)?;
    let mut denied = ingress.clone();
    denied.invocation_id = "native:withdrawn".to_string();
    anyhow::ensure!(
        client.memory_cell_read_start(denied).await.is_err(),
        "withdrawn source admitted"
    );
    anyhow::ensure!(
        cell.backend_dispatch_attempts() == 1,
        "refused uses caused additional backend entry"
    );
    retain(
        &root.join("final-anchor.json"),
        &host.writer().recovery_anchor().await?,
    )?;
    retain(
        &root.join("report.json"),
        &serde_json::json!({
            "schema": "hepta.memory-cell.native-daemon-development.v1", "engineering_pass": true,
            "actual_runtime_run": true, "actual_control_socket": true, "actual_neuron_model_port": true,
            "backend_dispatch_attempts": cell.backend_dispatch_attempts(),
            "parameter_exact_correct": result.text.as_deref().is_some_and(|text| text.trim() == expected_value), "parameter_denominator": 1,
            "source_id": claim.production.write.source.source_id.as_str(), "source_root": claim.production.source_content_sha256.as_str(),
            "memory_id": claim.production.write.memory.id.memory_id.as_str(), "initial_revision": 1, "withdrawal_revision": withdrawal.write.memory.id.revision,
            "refused": ["unknown-key", "wrong-role", "forged-production-receipt", "replayed-nonce", "withdrawn-authority", "corrected-cached-result", "corrected-old-adapter", "withdrawn-source"],
            "neuron_runtime_calibrated_tick": false, "source_authority": "controlled native qualification issuer",
            "github_permission_authentication": false, "confirmation": false, "production_qualified": false
        }),
    )?;
    // End only this controlled runtime task; the owner's drop guard cancels
    // native subprocess work. This probe makes no graceful-drain claim.
    daemon.abort();
    let _cancelled = daemon.await;
    anyhow::ensure!(
        cell.backend_dispatch_attempts() == 1,
        "unexpected cleanup dispatch"
    );
    println!("native daemon development probe completed");
    Ok(())
}
