//! Explicit real-decoder qualification using a previously trained checkpoint.
//! Source bytes and pins come from the independent CI driver; no training or
//! expected-answer substitution happens here. Owner/clock issuers are fixtures.

use std::path::PathBuf;

use codex_hepta_memory::MemoryCellDocumentV1;
use codex_hepta_types::Digest32;
use std::assert_eq;

use super::current_tests::factory_fixture_with_document;
use super::current_tests::registered_source;
use super::*;
use crate::NativeMemoryShadowStartV1;
use crate::native_memory_shadow_namespace::tests::files;
use crate::native_memory_shadow_namespace::tests::profile;

fn required_artifact(name: &str) -> PathBuf {
    let path = PathBuf::from(
        std::env::var_os(name)
            .unwrap_or_else(|| panic!("{name} must explicitly name a trained artifact")),
    );
    assert!(
        path.is_absolute() && path.is_file(),
        "{name} must be an absolute existing file"
    );
    path
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires explicitly supplied real trained artifacts; run the current-factory CI driver"]
async fn pretrained_current_factory_executes_one_exact_decoder_and_fences_delivery() {
    let config_path = required_artifact("HEPTA_NATIVE_MEMORY_CURRENT_MODEL_CONFIG");
    let source_path = required_artifact("HEPTA_NATIVE_MEMORY_CURRENT_SOURCE_DOCUMENT");
    let config_bytes = std::fs::read(config_path).unwrap();
    let model: NativeMemoryModelConfigV1 = serde_json::from_slice(&config_bytes).unwrap();
    model.validate().unwrap();
    assert_eq!(model.output_width, 5);
    std::fs::create_dir(&model.receipt_directory)
        .expect("receipt_directory must be an independent new directory with an existing parent");
    let document_bytes = std::fs::read(source_path).unwrap();
    let source_hash = Digest32::of_bytes(&document_bytes).to_string();
    let document: MemoryCellDocumentV1 = serde_json::from_slice(&document_bytes).unwrap();
    document.validate().unwrap();
    let mut f = factory_fixture_with_document(document_bytes).await;
    assert_eq!(
        f.source.claim.production.source_content_sha256.as_str(),
        source_hash
    );
    f.source.config = model.clone();
    let runtime = CancellationToken::new();
    let _lifetime = f
        .registration
        .attach(&f.current.objective.state, Arc::clone(&f.writer), &runtime)
        .unwrap();
    let host = f.registration.host().unwrap();
    let mut query = f.current.query("pretrained-current-factory");
    query.key = document.key.clone();
    query.deadline_unix_ms = f.current.objective.record.admission.deadline_unix_micros / 1000;
    let prepared = host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "pretrained-current-factory");
    let mut shadow_profile = profile(&model);
    // Existing pretrained shadow envelope, configured rather than calibrated.
    shadow_profile.limits.p95_latency_micros = 120_000_000;
    shadow_profile.limits.p99_latency_micros = 120_000_000;
    shadow_profile.limits.transient_allocation_bytes = 4_u64 << 30;
    let shadow = host
        .open_shadow(
            prepared,
            &signed,
            registered_source(&f),
            files(
                &model.receipt_directory,
                NativeMemoryShadowStartV1::Bootstrap,
            ),
            shadow_profile,
        )
        .await
        .unwrap();
    let mut different_query = query.clone();
    different_query.request_id =
        crate::native_memory_current_test_support::id("ungranted-current-query");
    assert!(shadow.read(different_query).await.is_err());
    let result = shadow.read(query.clone()).await.unwrap();
    shadow.revalidate_delivery(&result).await.unwrap();
    let execution = result.execution();
    assert_eq!(
        (execution.decoder_queries, execution.feature_forward_calls),
        (1, 1)
    );
    assert_eq!(
        (
            execution.adapter_enabled,
            execution.base_unchanged,
            execution.adapter_unchanged
        ),
        (true, true, true)
    );
    assert_eq!(
        (
            execution.facts_received,
            execution.retrieval_received,
            execution.answer_postprocessed
        ),
        (false, false, false)
    );
    assert_eq!(&execution.pins, &model.pins);
    assert_eq!(execution.question, document.key.question().unwrap());
    assert!(!execution.prompt_token_ids.is_empty() && !execution.generated_token_ids.is_empty());
    assert_eq!(
        result.source().binding.source_content_sha256.as_str(),
        source_hash
    );
    assert_eq!(
        result.source().execution_digest,
        Digest32::of_bytes(&serde_json::to_vec(execution).unwrap())
    );
    assert_eq!(result.observation().tick_id, query.request_id);
    assert!(result.observation().abstain && !result.observation().authority.grants_any());
    assert_ne!(
        result.observation().checkpoint_after,
        result.observation().checkpoint_before
    );
    let process_directories = std::fs::read_dir(&model.receipt_directory)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    assert_eq!(
        process_directories,
        vec![model.receipt_directory.join(&execution.request_sha256)]
    );
    let raw_request: serde_json::Value = serde_json::from_slice(
        &std::fs::read(process_directories[0].join("request.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(raw_request["schema"], "hepta.memory-cell.native-request.v2");
    assert_eq!(raw_request["source_root"], source_hash);
    assert_eq!(
        raw_request["tick_binding"]["subject_id"],
        f.current.objective.state.identity().agent_id.as_str()
    );
    assert_eq!(
        raw_request["tick_binding"]["objective_digest"],
        f.current
            .objective
            .record
            .snapshot
            .objective_digest
            .to_string()
    );
    assert_eq!(raw_request["query_digest"], execution.query_digest);
    assert_eq!(
        raw_request["source_binding_digest"],
        execution.source_binding_digest
    );
    let process: serde_json::Value = serde_json::from_slice(
        &std::fs::read(process_directories[0].join("process.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        (
            process["exit_code"].clone(),
            process["timed_out"].clone(),
            process["owner_cancelled"].clone()
        ),
        (
            serde_json::json!(0),
            serde_json::json!(false),
            serde_json::json!(false)
        )
    );
    runtime.cancel();
    assert!(shadow.revalidate_delivery(&result).await.is_err());
    assert!(shadow.read(query.clone()).await.is_err());
    assert!(host.prepare_read("run.current", query).is_err());
    assert_eq!(
        std::fs::read_dir(&model.receipt_directory)
            .unwrap()
            .filter(|entry| entry.as_ref().unwrap().path().is_dir())
            .count(),
        1
    );
    let report = serde_json::json!({
        "schema": "hepta.memory-cell.current-factory-pretrained.v1",
        "engineering_pass": true, "extra_training_updates": 0,
        "configuration_sha256": Digest32::of_bytes(&config_bytes).to_string(),
        "source_document_sha256": source_hash, "actual_decoder_queries": execution.decoder_queries,
        "actual_feature_forward_calls": execution.feature_forward_calls, "completed_worker_processes": 1,
        "exact_query_substitution_refused": true, "cancelled_runtime_delivery_refused": true,
        "actual_current_owner_factory": true, "default_daemon_process_exercised": false,
        "authority_and_clock": "test-controlled real durable owners", "production_qualified": false,
        "raw_text": execution.text, "exact_correct": execution.text.trim() == document.value,
        "previously_exposed_case": true, "denominator": 1, "calibration": null,
        "source_use": result.source(), "execution": execution,
        "shadow_checkpoint_after": result.observation().checkpoint_after.to_string(),
        "abstain": result.observation().abstain, "authority_grants_any": result.observation().authority.grants_any(),
    });
    std::fs::write(
        model.receipt_directory.join("current-factory-report.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
}
