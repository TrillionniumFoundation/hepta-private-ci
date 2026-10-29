//! The real owner/worker path must consume V2 at the original turn/start fence.

use super::*;
use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use core_test_support::responses;
use std::sync::Arc;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_turn_start_consumes_explicit_pq_config_and_external_mldsa_grant() -> Result<()>
{
    let server = responses::start_mock_server().await;
    let response = responses::sse(vec![
        responses::ev_response_created("resp-pq-final-use"),
        responses::ev_assistant_message("msg-pq-final-use", "PQ final use reached the model"),
        responses::ev_completed("resp-pq-final-use"),
    ]);
    let response_mock = responses::mount_sse_once(&server, response).await;
    let directory = tempfile::tempdir()?;
    let host = CognitiveTestHost::start(
        directory.path().join("agentd"),
        codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        "mock-model",
        &format!("{}/v1", server.uri()),
        codex_utils_cargo_bin::cargo_bin("codex")?,
    )
    .await?;
    host.seed_verified_memory("pq-final-use-memory", "verified lime orchard PQ use marker")
        .await?;
    let authority_directory = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::independent_test_authorizer_v2(
        authority_directory.path(),
        /*count*/ 1,
    )
    .await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: host.control_socket().to_path_buf(),
        agent_id: host.agent_id().clone(),
        generation: 1,
        model: "mock-model".to_string(),
        timeout: Duration::from_secs(20),
    })?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal = directory.path().join("native.journal");
    let mut durable = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    let accepted = driver
        .run(
            &mut durable,
            NativeAdmission {
                request_id: "pq-final-use-accept".to_string(),
                maximum_in_flight: 1,
            },
            "answer from the verified memory".to_string(),
            Some("lime".to_string()),
            &CancellationToken::new(),
        )
        .await?;
    assert!(accepted.succeeded());
    assert!(accepted.output.contains("PQ final use reached the model"));
    let record = durable
        .native_record("pq-final-use-accept")
        .cloned()
        .ok_or("missing durable native record after PQ final use")?;
    assert_eq!(record.state, NativeReservationState::Released);
    assert!(record.dispatch.is_some());
    assert!(record.turn_id.is_some());
    assert_eq!(record.observation.as_ref(), Some(&accepted));
    assert_eq!(record.pre_dispatch_stop, None);
    assert_eq!(response_mock.requests().len(), 1);
    drop(durable);
    let reopened = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    assert_eq!(reopened.native_record("pq-final-use-accept"), Some(&record));
    issuer.await??;
    host.shutdown().await;
    Ok(())
}
