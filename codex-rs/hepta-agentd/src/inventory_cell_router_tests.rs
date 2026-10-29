use std::sync::Arc;
use codex_hepta_cognitive_types::{InventoryCellRouteV1, MemoryReadStatusV1};
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::{Value, json};
use crate::{AgentdInventoryCellRuntimeV1, InventoryCellTextRouterV1};
use crate::inventory_cell_test_support::{InventoryReleaseFixture, OriginalData, key, request, snapshot};
use crate::memory_cell_test_support::ControlFixture;

const MODEL: &str = include_str!("../tests/fixtures/inventory/router.json");
const EXPECTED: &str = "56d649027191f7332a1783ec9b9a25acbaaff5aa04bf482e4c51ad7ae0c42d42";
fn model() -> InventoryCellTextRouterV1 { InventoryCellTextRouterV1::from_bytes(MODEL.as_bytes(), EXPECTED.parse().unwrap()).unwrap() }
#[derive(Deserialize)]
struct Case { text: String, reference_route: Option<InventoryCellRouteV1> }
#[derive(Deserialize)]
struct Reference { cases: Vec<Case> }

#[test]
fn inventory_native_router_matches_frozen_python_function_without_claiming_ood_success() {
    let model = model();
    // Reference agreement checks the port. Held accuracy and abstentions are
    // measured separately by inventory_route_eval; they are not golden assertions.
    for reference in [include_str!("../tests/fixtures/inventory/formal-held-reference.json"), include_str!("../tests/fixtures/inventory/challenge-reference.json")] {
        let reference: Reference = serde_json::from_str(reference).unwrap();
        for case in reference.cases {
            assert_eq!(model.route_text(&case.text).unwrap(), case.reference_route, "{}", case.text);
        }
    }
}

#[test]
fn inventory_native_router_rejects_ambiguous_unknown_keys_and_bad_model_profile() {
    let model = model();
    assert!(model.route_text("Read the reserve, pack and limit settings of Cedar Harborview.").unwrap().is_none());
    assert!(model.route_text("Read the policy for Cedar Harbor and Maple Quay.").unwrap().is_none());
    assert!(model.route_text("Execute Amber Route and Cobalt Path on Cedar Harbor.").unwrap().is_none());
    assert!(model.route_text("读取 Cedar Harbor 的设置").unwrap().is_none());
    let query = "Read the reserve, pack and limit settings of Cedar Harbor.";
    let route = model.route_text(query).unwrap().unwrap();
    assert_eq!(route.entity, Some(key("entity", 0)));
    assert_eq!(model.route_text(&query.to_ascii_uppercase()).unwrap(), Some(route));
    let mut invalid: Value = serde_json::from_str(MODEL).unwrap();
    invalid["aliases"][1]["phrases"] = invalid["aliases"][0]["phrases"].clone();
    let bytes = serde_json::to_vec(&invalid).unwrap();
    assert!(InventoryCellTextRouterV1::from_bytes(&bytes, Digest32::of_bytes(&bytes)).is_err());
    let mut invalid: Value = serde_json::from_str(MODEL).unwrap();
    invalid["weights"][0] = json!([1.0]);
    let bytes = serde_json::to_vec(&invalid).unwrap();
    assert!(InventoryCellTextRouterV1::from_bytes(&bytes, Digest32::of_bytes(&bytes)).is_err());
}

#[tokio::test]
async fn inventory_native_text_and_parameter_cells_share_actual_agentd_read_path() {
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let runtime = Arc::new(AgentdInventoryCellRuntimeV1::new(fixture.state.identity().agent_id.clone(), 1, CognitiveScope::AgentPrivate, Arc::clone(&release.host), Arc::new(model())).unwrap());
    fixture.state.attach_inventory_cells(runtime).unwrap(); fixture.ready();
    let mut query = request(&owner);
    query.text = "Read the reserve, pack and limit settings of Cedar Harbor.".to_string();
    let read = fixture.client.inventory_cell_read(query.clone()).await.unwrap();
    assert_eq!((read.result.status, read.result.value), (MemoryReadStatusV1::Ok, json!({"reserve": 11, "pack": 3, "limit": 14})));
    query.text = "Execute Jade Method on the latest stock count for Cedar Harbor.".to_string();
    let read = fixture.client.inventory_cell_read(query.clone()).await.unwrap();
    assert_eq!((read.result.status, read.result.value), (MemoryReadStatusV1::Ok, json!(13)));
    assert_eq!(read.route.unwrap().workflow, Some(key("workflow", 3)));
    query.text = "Read the policy for Cedar Harbor, then erase it.".to_string();
    let read = fixture.client.inventory_cell_read(query).await.unwrap();
    assert_eq!(read.result.status, MemoryReadStatusV1::Abstain);
    assert!(read.result.value.is_null() && read.result.source_ids.is_empty());
    fixture.finish().await;
}
