//! One real pretrained v2 callback through the explicitly controlled shadow owner.
//! Reuses an existing checkpoint; never trains or substitutes an expected answer.
//! This qualification example does not install a default daemon context provider.

mod native_memory_shadow_support;
mod native_memory_support;

use std::path::Path;
use std::sync::atomic::Ordering;
use codex_hepta_agentd::NativeMemoryError;
use codex_hepta_agentd::NativeMemoryModelConfigV1;
use codex_hepta_agentd::NativeMemoryShadowStartV1;
use codex_hepta_memory::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use native_memory_shadow_support::*;
use native_memory_support::*;

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    anyhow::ensure!(args.len() >= 2, "prepare ROOT | run ROOT SHADOW_CONFIG SOURCE_DOCUMENT ANCHOR_SHA256");
    let root = std::path::absolute(&args[1])?;
    match args[0].as_str() {
        "prepare" if args.len() == 2 => prepare(&root).await,
        "run" if args.len() == 5 => {
            let result = probe(&root, Path::new(&args[2]), Path::new(&args[3]), &args[4]).await;
            if let Err(error) = &result {
                retain(&root.join("failure.json"), &serde_json::json!({
                    "error": format!("{error:#}"), "production_qualified": false,
                    "actual_model_calls": null, "partial_evidence_retained": true,
                }))?;
            }
            result
        }
        _ => anyhow::bail!("closed shadow qualification arguments required"),
    }
}

async fn probe(root: &Path, config_path: &Path, document_path: &Path, anchor: &str) -> anyhow::Result<()> {
    let (configuration, _registry) = config(root)?;
    let (host, authority_withdrawn) = open_host(root, &configuration, anchor).await?;
    let access = CognitiveAccess::agent_private(owner()?);
    let document_bytes = std::fs::read(document_path)?;
    let document: MemoryCellDocumentV1 = serde_json::from_slice(&document_bytes)?;
    document.validate()?;
    let original_source = source(document_bytes, "qualification:pretrained-shadow-import")?;
    let production = host.remember_with_kg(&access, &original_source, &MemoryDraft {
        stable_key: document.key.stable_key()?, revision: revision(&original_source)?,
    }, &KgFactSetDraft::default()).await?;
    retain(&root.join("production-source.json"), &production)?;
    let claim = claim(&document, production)?;
    retain(&root.join("hnmf-event.json"), &claim.event)?;
    let model: NativeMemoryModelConfigV1 = serde_json::from_slice(&std::fs::read(config_path)?)?;
    let registered = descriptor(&model)?;
    retain(&root.join("registered-shadow-profile.json"), &serde_json::json!({
        "schema": "hepta.memory-cell.controlled-shadow-profile.v1",
        "config_sha256": Digest32::of_bytes(&std::fs::read(config_path)?).to_string(),
        "model": model, "shadow_profile_digest": registered.semantic_digest()?.to_string(),
        "shadow_profile": format!("{registered:?}"), "sparse_profile": format!("{:?}", profile(&model)?.sparse),
        "resource_limits_are_configured_not_measured": true, "calibration": null,
        "original_v1_observation_width": 4, "shadow_observation_width": model.output_width,
        "extra_training_updates": 0, "production_qualified": false,
    }))?;
    let cell = host.native_memory_cell(access.clone(), document.key.clone(), claim.clone(), model.clone()).await?;
    let context = ControlledQualificationContext::create(root)?;
    let shadow = cell.shadow_owner(files(root, NativeMemoryShadowStartV1::Bootstrap)?,
        profile(&model)?, context.clone()).await?;
    let query = MemoryCellQueryV1 {
        request_id: StableId::new("controlled:pretrained-shadow:1")?,
        key: document.key.clone(), deadline_unix_ms: now_ms()? + 180_000,
    };
    retain(&root.join("read-query.json"), &query)?;
    anyhow::ensure!(cell.backend_dispatch_attempts() == 0, "registration dispatched a model");
    let result = shadow.read(query.clone()).await?;
    retain(&root.join("raw-execution.json"), result.execution())?;
    retain(&root.join("source-use.json"), result.source())?;
    shadow.revalidate_delivery(&result).await?;
    retain(&root.join("read-evidence.json"), &read_evidence(root, &model, &context, &result)?)?;
    anyhow::ensure!(result.execution().question == document.key.question()?, "actual typed question differs");
    let completed_calls = cell.backend_dispatch_attempts();
    anyhow::ensure!(completed_calls == 1, "unexpected actual backend callback count");
    drop(shadow);
    let before = journal_evidence(root, &model, &context, &result)?;
    retain(&root.join("anchors-after-read.json"), &before)?;

    // A rejected admission poisons only this owner instance. Never call delivery
    // on that poisoned instance: it would cancel the shared native cell.
    let replay_owner = cell.shadow_owner(files(root, NativeMemoryShadowStartV1::Recover)?,
        profile(&model)?, context.clone()).await?;
    let replay = replay_owner.read(query).await.err().ok_or_else(|| anyhow::anyhow!("spent nonce replay admitted"))?;
    retain(&root.join("replay-refusal.json"), &serde_json::json!({
        "error": replay.to_string(), "error_kind": format!("{replay:?}"),
        "backend_dispatches_before": completed_calls, "backend_dispatches_after": cell.backend_dispatch_attempts(),
    }))?;
    anyhow::ensure!(matches!(replay, NativeMemoryError::Source(MemoryCellSourceError::Replay)),
        "nonce was refused for a reason other than durable replay");
    anyhow::ensure!(cell.backend_dispatch_attempts() == completed_calls, "nonce replay dispatched a backend");
    drop(replay_owner);

    let recovered = cell.shadow_owner(files(root, NativeMemoryShadowStartV1::Recover)?,
        profile(&model)?, context.clone()).await?;
    recovered.revalidate_delivery(&result).await?;
    retain(&root.join("delivery-before-tombstone.json"), &serde_json::json!({
        "delivery_allowed": true, "same_process_owner_recovered": true,
        "backend_dispatches": cell.backend_dispatch_attempts(), "context_provider_calls": context.calls(),
    }))?;
    let withdrawal_reason = "controlled shadow source withdrawal";
    let withdrawal_source = source(withdrawal_reason.as_bytes().to_vec(),
        "qualification:pretrained-shadow-withdrawal")?;
    let withdrawal = host.forget_with_kg(&access, &claim.production.write.memory.id.memory_id,
        claim.production.write.memory.id.revision, &withdrawal_source, &ForgetMemoryDraft {
            scope: CognitiveScope::AgentPrivate, reason: withdrawal_reason.to_string(),
            valid_from_unix_seconds: withdrawal_source.observed_at_unix_seconds, citations: vec![],
        }).await?;
    retain(&root.join("source-tombstone.json"), &withdrawal)?;
    anyhow::ensure!(!authority_withdrawn.load(Ordering::SeqCst), "writer authority unexpectedly withdrawn");
    let denied = recovered.revalidate_delivery(&result).await.err()
        .ok_or_else(|| anyhow::anyhow!("tombstoned source escaped delivery fence"))?;
    retain(&root.join("delivery-after-tombstone.json"), &serde_json::json!({
        "delivery_allowed": false, "error": denied.to_string(), "error_kind": format!("{denied:?}"),
        "writer_authority_withdrawn": authority_withdrawn.load(Ordering::SeqCst),
        "backend_dispatches_before": completed_calls, "backend_dispatches_after": cell.backend_dispatch_attempts(),
    }))?;
    anyhow::ensure!(matches!(denied, NativeMemoryError::Source(MemoryCellSourceError::Invalid("current source revision or typed identity"))),
        "delivery refusal did not identify the changed source head");
    anyhow::ensure!(cell.backend_dispatch_attempts() == completed_calls, "withdrawal dispatched another backend");
    drop(recovered);
    let after = journal_evidence(root, &model, &context, &result)?;
    retain(&root.join("anchors-after-withdrawal.json"), &after)?;
    anyhow::ensure!(before == after, "replay/recovery/withdrawal changed model journal or witness");
    let execution = result.execution();
    let report = serde_json::json!({
        "schema": "hepta.memory-cell.controlled-pretrained-shadow-qualification.v1",
        "engineering_pass": true, "context_provider": PROVIDER, "context_provider_calls": context.calls(),
        "actual_backend_dispatches": cell.backend_dispatch_attempts(), "actual_decoder_queries": execution.decoder_queries,
        "actual_feature_forward_calls": execution.feature_forward_calls, "extra_training_updates": 0,
        "raw_text": execution.text, "prompt_token_ids": execution.prompt_token_ids, "generated_token_ids": execution.generated_token_ids,
        "exact_correct": execution.text.trim() == document.value, "denominator": 1, "parameter_success_gate": null,
        "neuron_runtime_tick_shadow": true, "actual_python_request_v2": true,
        "same_process_owner_recoveries": 2, "nonce_replay_refused": true, "tombstone_delivery_refused": true,
        "source_supported_delivery_before_tombstone": true, "current_support_after_tombstone": false,
        "shadow_profile_digest": registered.semantic_digest()?.to_string(), "anchors": after,
        "calibration": null, "abstain": result.observation().abstain, "authority_grants_any": result.observation().authority.grants_any(),
        "production_context_provider": false, "production_qualified": false, "default_daemon_installed": false,
        "v2_control_socket_exercised": false, "cross_process_recovery": false, "physical_unlearning": false,
        "previously_exposed_case": true, "confirmation": false,
    });
    retain(&root.join("report.json"), &report)?;
    println!("{report}");
    Ok(())
}
