use std::collections::BTreeMap;

use pretty_assertions::assert_eq;
use serde_json::{Value, json};

use crate::memory_inventory_test_support::{fixture, request};
use super::{BoundInventoryRequest, hash};

#[tokio::test]
async fn inventory_worker_contract_binds_both_keys_budget_and_complete_owner_cut() {
    let (fixture, owner) = fixture().await;
    let request = request(owner.scope().clone());
    let bound = BoundInventoryRequest::build(&request, &owner, &BTreeMap::new()).expect("owner-bound address request");
    let input: Value = serde_json::from_slice(&bound.bytes).expect("worker input");
    assert_eq!(input["registry"]["entities"], json!([{"key":"site:cedar","aliases":[]}]));
    assert_eq!(input["registry"]["workflows"], json!([{"key":"workflow:amber","aliases":[]}]));
    assert!(!String::from_utf8(bound.bytes.clone()).expect("UTF8").contains("reserve"));
    let model = hash(b"explicit wire-test model pin, not a trained router");
    let response = json!({
        "schema":"hepta.memory.inventory-address-decision.v1", "query_id":request.query_id,
        "request_digest":bound.digest,"status":"accepted","reason":null,"request":request,
        "plan":{"operation":"apply","required_cells":["event","semantic","procedure","hold"],"read_hops":3,
            "source_cut":bound.source_cut,"registry_digest":bound.registry_digest},
        "model_digest":model,"registry_digest":bound.registry_digest,"source_cut":bound.source_cut,
        "decision":{"raw_operation":"apply","score":0.9,"margin":0.5,"score_kind":"wire_test_only","capability_reason":null,
            "operation":"apply","threshold":0.6,"required_margin":0.1},"authority":false,
        "cost":{"request_body_bytes":bound.bytes.len()-1,"processing_wall_seconds":0.01,"processing_cpu_seconds":0.01},
    });
    let valid = serde_json::to_vec(&response).expect("wire response");
    let (decision, _) = bound.validate_response(&valid, model, &request).expect("typed accepted response");
    assert_eq!(decision.expect("decision").request, request);
    let mut variants = Vec::new();
    for (field, value) in [("workflow_key", json!("workflow:substituted")), ("entity_key", json!("site:substituted")), ("max_steps", json!(1))] {
        let mut changed = response.clone(); changed["request"][field] = value; variants.push(changed);
    }
    let mut changed=response.clone(); changed["source_cut"]=json!(hash(b"stale cut")); variants.push(changed);
    let mut changed=response.clone(); changed["authority"]=json!(true); variants.push(changed);
    let mut changed=response.clone(); changed["plan"]["required_cells"]=json!(["event","semantic","procedure"]); variants.push(changed);
    let mut changed=response.clone(); changed.as_object_mut().expect("object").remove("reason"); variants.push(changed);
    let mut changed=response.clone(); changed["status"]=json!("rejected"); changed["reason"]=json!("declined"); variants.push(changed);
    for variant in variants { assert!(bound.validate_response(&serde_json::to_vec(&variant).expect("malformed variant"), model, &request).is_err()); }
    let mut declined=response; declined["status"]=json!("rejected"); declined["reason"]=json!("ambiguous registry address");
    declined["request"]=Value::Null; declined["plan"]=Value::Null; declined["decision"]=Value::Null;
    assert!(bound.validate_response(&serde_json::to_vec(&declined).expect("decline"), model, &request).expect("valid abstention").0.is_none());
    fixture.finish().await;
}
