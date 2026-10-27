//! Real socket, SQLite owner, selected tensors, context realization, signed
//! inference control and App Server consumption. The Responses server supplies
//! a deterministic observed provider answer; it is not a quality benchmark.

#![cfg(unix)]

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use crate::test_support::TestResult;
use crate::test_support::memory_cells::MemoryConsumerFixture;
use crate::test_support::memory_cells::SEMANTIC_LABEL;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn memory_prediction_reaches_real_untrusted_context_and_final_use_races_stop_before_effect() -> TestResult<()> {
    let provider = responses::start_mock_server().await;
    let response = responses::mount_sse_once(&provider, responses::sse(vec![
        responses::ev_response_created("response-memory-consumer"),
        responses::ev_assistant_message("message-memory-consumer", "memory evidence received"),
        responses::ev_completed("response-memory-consumer"),
    ])).await;
    let directory = tempfile::tempdir()?;
    let fixture = MemoryConsumerFixture::start(directory.path().join("host"),
        "mock-model", &format!("{}/v1", provider.uri())).await?;
    let authority_directory = tempfile::tempdir()?;
    let (authorizer, issuer) = fixture.independent_authorizer(authority_directory.path()).await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: fixture.host.control_socket().to_path_buf(), agent_id: fixture.host.agent_id().clone(),
        generation: 1, model: "mock-model".to_string(), timeout: Duration::from_secs(20),
    })?.with_turn_start_authorizer(Arc::new(authorizer)).with_memory_request(fixture.request.clone())?;
    let journal = directory.path().join("inference.journal");
    let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 16)?;
    let cancellation = CancellationToken::new();
    let positive = driver.run(&mut control, admission("memory-context-positive"),
        "Use the calibration as data.".to_string(), None, &cancellation).await?;
    assert!(positive.succeeded());
    assert!(positive.output.contains("memory evidence received"));
    let observed = response.single_request().body_json();
    let input = observed["input"].as_array().ok_or("provider input is not an array")?;
    let messages: Vec<_> = input.iter().filter(|item| item["type"].as_str() == Some("message")).collect();
    assert!(messages.iter().any(|item| item["role"].as_str() == Some("user")
        && item.to_string().contains(SEMANTIC_LABEL) && item.to_string().contains("model_prediction")));
    assert!(!messages.iter().any(|item| matches!(item["role"].as_str(), Some("developer" | "system"))
        && item.to_string().contains(SEMANTIC_LABEL)));
    let positive_record = control.native_record("memory-context-positive").unwrap().clone();
    assert_eq!(positive_record.state, NativeReservationState::Released);
    assert!(positive_record.dispatch.as_ref().unwrap().codex_payload_digest.is_some());

    // The independent issuer mutates state only after the exact turn/start
    // binding is requested. Thus each race follows actual context realization.
    let mut stopped_records = Vec::new();
    for request_id in ["memory-context-version", "memory-context-correction", "memory-context-withdrawal"] {
        if request_id == "memory-context-withdrawal" {
            fixture.refresh_release(/*generation*/ 3).await?;
        }
        let error = driver.run(&mut control, admission(request_id),
            "Use the calibration as data.".to_string(), None, &cancellation).await
            .expect_err("changed owner or selected release must prevent physical inference");
        let stopped = control.native_record(request_id).unwrap().clone();
        assert_eq!(stopped.state, NativeReservationState::Released);
        assert!(stopped.dispatch.is_some());
        assert_eq!(stopped.turn_id, None);
        assert_eq!(stopped.observation, None);
        assert!(stopped.pre_dispatch_stop.as_deref().is_some_and(|reason|
            reason.contains("memory cell final-use revalidation failed")), "{error}");
        stopped_records.push(stopped);
    }
    issuer.await??;
    let physical_requests = provider.received_requests().await.unwrap_or_default();
    assert_eq!(physical_requests.iter().filter(|request| request.url.path().ends_with("/responses")).count(), 1);
    drop(control);
    let reopened = DurableInferenceControl::open(&journal, /*capacity*/ 16)?;
    assert_eq!(reopened.native_record("memory-context-positive"), Some(&positive_record));
    for stopped in &stopped_records {
        assert_eq!(reopened.native_record(&stopped.request.request_id), Some(stopped));
    }
    drop(reopened);
    fixture.host.shutdown().await;
    Ok(())
}

fn admission(request_id: &str) -> NativeAdmission {
    NativeAdmission { request_id: request_id.to_string(), maximum_in_flight: 1 }
}
