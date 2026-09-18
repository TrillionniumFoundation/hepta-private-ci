use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::DurableInferenceControlStore;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn fixture(label: &str) -> (AppServerModelDriver, PathBuf) {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("hepta-native-host-{label}-{nonce}.journal"));
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: path.with_extension("nonexistent-socket"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "model".to_string(),
        timeout: Duration::from_secs(5),
    })
    .unwrap();
    (driver, path)
}

fn request(driver: &AppServerModelDriver, request_id: &str) -> NativeRequest {
    NativeRequest {
        request_id: request_id.to_string(),
        principal_id: driver.config.agent_id.to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: digest(
            &serde_json::to_vec(&(
                "hepta.native-request.v1",
                "prompt",
                Option::<String>::None,
                &driver.config.agentd_socket,
                driver.config.timeout.as_millis(),
            ))
            .unwrap(),
        ),
    }
}

fn admission() -> NativeAdmission {
    NativeAdmission {
        request_id: "r1".to_string(),
        maximum_in_flight: 1,
    }
}

#[tokio::test]
async fn reopened_dispatch_and_completed_duplicate_never_connect_to_provider() {
    let (driver, path) = fixture("reopen");
    let mut setup = DurableInferenceControl::open(&path, 8).unwrap();
    setup.reserve_native(request(&driver, "r1"), 1).unwrap();
    setup
        .dispatch_native(
            "r1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "a".repeat(64),
            },
        )
        .unwrap();
    drop(setup);

    let store = DurableInferenceControlStore::open(&path, 8).unwrap();
    let cancellation = CancellationToken::new();
    // The nonexistent socket makes any accidental second dispatch fail.
    let unknown = driver
        .run(
            &store,
            admission(),
            "prompt".to_string(),
            None,
            &cancellation,
        )
        .await
        .unwrap();
    assert_eq!(unknown.status, NativeRunStatus::Indeterminate);
    assert_eq!(unknown.observed_output_tokens, None);
    assert!(!unknown.terminal_observed);
    assert_eq!(
        store.native_record("r1").unwrap().unwrap().state,
        NativeReservationState::Indeterminate
    );
    assert_eq!(
        driver
            .run(
                &store,
                admission(),
                "prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .unwrap(),
        unknown
    );
    assert!(
        driver
            .run(
                &store,
                admission(),
                "changed prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .is_err()
    );
    let terminal = NativeRunOutput {
        turn_id: "turn-1".to_string(),
        status: NativeRunStatus::Failed,
        terminal_observed: true,
        observed_output_tokens: Some(17),
        stop_reason: Some("observed terminal failure".to_string()),
        ..unknown
    };
    store
        .with_control(|control| control.settle_native("r1", terminal.clone()).map(|_| ()))
        .unwrap();
    assert_eq!(
        driver
            .run(
                &store,
                admission(),
                "prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .unwrap(),
        terminal
    );
    drop(store);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pre_dispatch_cancellation_and_connection_failure_release_without_usage_claims() {
    for cancelled in [true, false] {
        let (driver, path) = fixture(if cancelled { "cancel" } else { "connection" });
        let store = DurableInferenceControlStore::open(&path, 8).unwrap();
        let cancellation = CancellationToken::new();
        if cancelled {
            cancellation.cancel();
        }
        assert!(
            driver
                .run(
                    &store,
                    admission(),
                    "prompt".to_string(),
                    None,
                    &cancellation
                )
                .await
                .is_err()
        );
        let stopped = store.native_record("r1").unwrap().unwrap();
        assert_eq!(stopped.state, NativeReservationState::Released);
        assert_eq!(stopped.observation, None);
        assert!(stopped.pre_dispatch_stop.is_some());
        assert!(
            driver
                .run(
                    &store,
                    admission(),
                    "prompt".to_string(),
                    None,
                    &CancellationToken::new()
                )
                .await
                .is_err()
        );
        assert_eq!(store.native_record("r1").unwrap(), Some(stopped));
        drop(store);
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn store_releases_writer_lock_between_state_transactions() {
    let (driver, path) = fixture("short-lock");
    let store = DurableInferenceControlStore::open(&path, 8).unwrap();
    store
        .with_control(|control| control.reserve_native(request(&driver, "r1"), 2).map(|_| ()))
        .unwrap();

    // A second owner can acquire the exact same journal immediately while the
    // first request is still in-flight. Provider work therefore cannot inherit
    // a process-lifetime journal lock from the store handle.
    let mut concurrent = DurableInferenceControl::open(&path, 8).unwrap();
    concurrent
        .reserve_native(request(&driver, "r2"), 2)
        .unwrap();
    drop(concurrent);

    assert_eq!(
        store.native_record("r1").unwrap().unwrap().state,
        NativeReservationState::Reserved
    );
    assert_eq!(
        store.native_record("r2").unwrap().unwrap().state,
        NativeReservationState::Reserved
    );
    drop(store);
    std::fs::remove_file(path).unwrap();
}
