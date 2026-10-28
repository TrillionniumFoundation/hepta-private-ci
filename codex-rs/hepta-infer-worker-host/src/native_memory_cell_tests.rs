use super::*;
use crate::native_app_server::NativeAdmission;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

fn request() -> MemoryRequestV1 {
    MemoryRequestV1 {
        schema: "hepta.memory.request.v1".to_string(),
        query_id: ContractIdV1::new("memory-query").unwrap(),
        scope: ContractIdV1::new("owner-scope").unwrap(),
        entity: ContractIdV1::new("sensor-7").unwrap(),
        text: "What is the current reading?".to_string(),
        at: 20,
        since: 10,
        max_hops: 3,
        max_cells: 3,
    }
}

fn driver(directory: &Path) -> AppServerModelDriver {
    AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: directory.join("absent.sock"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "provider-model".to_string(),
        timeout: Duration::from_secs(5),
    })
    .unwrap()
}

#[test]
fn cli_request_is_bounded_strict_data_and_cannot_select_operation_or_authority() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("request.json");
    let expected = request();
    std::fs::write(&path, serde_json::to_vec(&expected).unwrap()).unwrap();
    assert_eq!(load_native_memory_request_v1(&path).unwrap(), expected);
    for key in ["operation", "source_cut", "authority", "model_digest"] {
        let mut malicious = serde_json::to_value(&expected).unwrap();
        malicious[key] = serde_json::json!("caller choice");
        std::fs::write(&path, serde_json::to_vec(&malicious).unwrap()).unwrap();
        assert!(load_native_memory_request_v1(&path).is_err(), "{key}");
    }
    std::fs::write(&path, vec![b' '; 65_537]).unwrap();
    assert!(load_native_memory_request_v1(&path).is_err());
    assert!(load_native_memory_request_v1(Path::new("relative.json")).is_err());
}

#[tokio::test]
async fn changed_memory_request_cannot_reuse_durable_inference_admission() {
    let directory = tempfile::tempdir().unwrap();
    let first = driver(directory.path())
        .with_memory_request(request())
        .unwrap();
    let mut changed = request();
    changed.entity = ContractIdV1::new("another-sensor").unwrap();
    let second = driver(directory.path())
        .with_memory_request(changed)
        .unwrap();
    let path = directory.path().join("control.journal");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let admission = || NativeAdmission {
        request_id: "same-run".to_string(),
        maximum_in_flight: 1,
    };
    assert!(
        first
            .run(
                &mut control,
                admission(),
                "prompt".to_string(),
                None,
                &CancellationToken::new()
            )
            .await
            .is_err()
    );
    let recorded = control.native_record("same-run").unwrap().clone();
    assert!(
        second
            .run(
                &mut control,
                admission(),
                "prompt".to_string(),
                None,
                &CancellationToken::new()
            )
            .await
            .is_err()
    );
    assert_eq!(control.native_record("same-run"), Some(&recorded));
    assert_ne!(
        first.bind_memory_admission("base".to_string()).unwrap(),
        second.bind_memory_admission("base".to_string()).unwrap()
    );
    assert_eq!(
        driver(directory.path())
            .bind_memory_admission("base".to_string())
            .unwrap(),
        "base"
    );
    assert!(
        driver(directory.path())
            .with_memory_request(request())
            .unwrap()
            .with_memory_request(request())
            .is_err()
    );
}
