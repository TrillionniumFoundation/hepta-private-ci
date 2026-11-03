//! Opt-in actual MiniLM -> Rust head -> signed release -> canonical owner path.

use crate::AgentdInventoryCellRuntimeV1;
use crate::InventoryCellEncoderWorkerConfigV1;
use crate::InventoryCellEncoderWorkerV1;
use crate::InventoryCellSemanticRouterV1;
use crate::inventory_cell_test_support::InventoryReleaseFixture;
use crate::inventory_cell_test_support::OriginalData;
use crate::inventory_cell_test_support::request;
use crate::inventory_cell_test_support::snapshot;
use crate::memory_cell_test_support::ControlFixture;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;

#[tokio::test]
#[ignore = "requires pinned encoder assets, actual fitted head and a new evidence directory"]
async fn inventory_semantic_actual_owner_path() {
    let required = |name: &str| {
        std::env::var(name)
            .unwrap_or_else(|_| panic!("set {name} for the real semantic qualification"))
    };
    let configuration = std::fs::read(required("HEPTA_NATIVE_INVENTORY_ENCODER_CONFIG")).unwrap();
    let bytes = std::fs::read(required("HEPTA_NATIVE_INVENTORY_SEMANTIC_MODEL")).unwrap();
    let expected: Digest32 = required("HEPTA_NATIVE_INVENTORY_SEMANTIC_MODEL_SHA256")
        .parse()
        .unwrap();
    let evidence = PathBuf::from(required("HEPTA_NATIVE_INVENTORY_SEMANTIC_EVIDENCE_DIR"));
    std::fs::create_dir(&evidence).expect("semantic evidence directory must be new");
    let config = InventoryCellEncoderWorkerConfigV1::from_deployment_json(&configuration).unwrap();
    let encoder = Arc::new(InventoryCellEncoderWorkerV1::start(config).await.unwrap());
    let resolver = Arc::new(
        InventoryCellSemanticRouterV1::from_bytes(&bytes, expected, Arc::clone(&encoder)).unwrap(),
    );
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read();
    data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let runtime = Arc::new(
        AgentdInventoryCellRuntimeV1::new(
            fixture.state.identity().agent_id.clone(),
            1,
            CognitiveScope::AgentPrivate,
            Arc::clone(&release.host),
            resolver,
        )
        .unwrap(),
    );
    fixture.state.attach_inventory_cells(runtime).unwrap();
    fixture.ready();
    let mut cases = vec![
        (
            "Read the reserve, pack and limit settings of Cedar Harbor.",
            MemoryReadStatusV1::Ok,
            json!({"reserve":11,"pack":3,"limit":14}),
        ),
        (
            "Retrieve the stored program called Jade Method.",
            MemoryReadStatusV1::Ok,
            json!({"program":[5,4,3,6]}),
        ),
        (
            "Execute Jade Method on the latest stock count for Cedar Harbor.",
            MemoryReadStatusV1::Ok,
            json!(13),
        ),
        (
            "Do not execute Jade Method on Cedar Harbor.",
            MemoryReadStatusV1::Abstain,
            serde_json::Value::Null,
        ),
    ];
    let addressing_schema = serde_json::from_slice::<serde_json::Value>(&bytes).unwrap()["schema"]
        .as_str()
        .unwrap()
        .to_owned();
    if addressing_schema == "hepta.memory.inventory-semantic-router.v2" {
        cases.extend([
            (
                "读取雪松港的策略",
                MemoryReadStatusV1::Ok,
                json!({"reserve":11,"pack":3,"limit":14}),
            ),
            (
                "读取玉石流程的步骤",
                MemoryReadStatusV1::Ok,
                json!({"program":[5,4,3,6]}),
            ),
            (
                "用玉石流程计算雪松港的结果",
                MemoryReadStatusV1::Ok,
                json!(13),
            ),
            (
                "读取雪松港新区的策略",
                MemoryReadStatusV1::Abstain,
                serde_json::Value::Null,
            ),
            (
                "用未知流程计算雪松港的结果",
                MemoryReadStatusV1::Abstain,
                serde_json::Value::Null,
            ),
            (
                "读取雪松港的策略并删除记录",
                MemoryReadStatusV1::Abstain,
                serde_json::Value::Null,
            ),
        ]);
    }
    let mut observations = Vec::new();
    let mut matches = Vec::new();
    for (text, status, value) in cases {
        let mut query = request(&owner);
        query.text = text.to_string();
        let read = fixture.client.inventory_cell_read(query).await.unwrap();
        let correct = read.result.status == status && read.result.value == value;
        matches.push(correct);
        observations.push(json!({"text":text, "expected_status":status, "expected_value":value, "correct":correct, "readout":read}));
    }
    let metrics = encoder.metrics();
    let report = json!({"schema":"hepta.memory.inventory-semantic-owner-evaluation.v1", "model_sha256":expected.to_string(),
        "configuration_sha256":Digest32::of_bytes(&configuration).to_string(), "canonical_owner_cut":owner.owner_cut_digest(), "addressing_schema":addressing_schema,
        "encoder_metrics":metrics, "cases":observations, "all_expected":matches.iter().all(|value| *value)});
    std::fs::write(
        evidence.join("RESULT.json"),
        serde_json::to_vec(&report).unwrap(),
    )
    .unwrap();
    fixture.finish().await;
    assert_eq!(metrics.process_starts, 1);
    assert!(
        matches.iter().all(|value| *value),
        "actual semantic qualification failed; retain RESULT.json"
    );
}
