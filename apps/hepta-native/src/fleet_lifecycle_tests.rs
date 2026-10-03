use super::*;

fn pending() -> PendingLifecycle {
    PendingLifecycle {
        schema_version: 1,
        endpoint_id: "runtime.fleet".into(),
        owner_epoch: "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12".into(),
        agent_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".into(),
        request_id: 109,
        operation: FleetLifecycleOperation::Restart,
        accepted_state_digest: "1".repeat(64),
    }
}

#[test]
fn original_intent_survives_reopen_and_blocks_duplicate_effects() {
    let temp = crate::private_state_test_support::private_tempdir();
    let root = PrivateStateRoot::open(temp.path()).unwrap();
    let mut store = PendingLifecycleStore::open(root.clone()).unwrap();
    assert!(PendingLifecycleStore::open(root.clone()).is_err());
    store.reserve(pending()).unwrap();
    drop(store);
    let mut recovered = PendingLifecycleStore::open(root.clone()).unwrap();
    assert_eq!(recovered.pending().unwrap().request_id, 109);
    assert!(recovered.reserve(pending()).is_err());
    assert_eq!(
        recovered.pending().unwrap().receipt_request(110)["method"]["mutation_request_id"],
        109
    );
    recovered.clear_terminal().unwrap();
    drop(recovered);
    assert!(
        PendingLifecycleStore::open(root)
            .unwrap()
            .pending()
            .is_none()
    );
}

#[test]
fn only_exact_terminal_original_receipt_can_clear_intent() {
    let pending = pending();
    let status = serde_json::json!({"type":"ordinary_mutation_status","status":{
        "request_id":109,"agent_id":pending.agent_id,"supervisor_epoch":pending.owner_epoch,
        "accepted_state_digest":pending.accepted_state_digest,"operation":"restart","phase":"committed"}});
    assert!(pending.receipt_terminal(&status).unwrap());
    for field in [
        "request_id",
        "agent_id",
        "supervisor_epoch",
        "accepted_state_digest",
        "operation",
    ] {
        let mut foreign = status.clone();
        foreign["status"][field] = serde_json::json!("foreign");
        assert!(pending.receipt_terminal(&foreign).is_err());
    }
    let mut incomplete = status;
    incomplete["status"]["phase"] = "prepared".into();
    assert!(!pending.receipt_terminal(&incomplete).unwrap());
    assert!(
        !pending
            .receipt_terminal(&serde_json::json!({"type":"ordinary_mutation_status","status":null}))
            .unwrap()
    );
}

#[test]
fn changed_durable_reference_fails_closed_instead_of_replaying() {
    let temp = crate::private_state_test_support::private_tempdir();
    let root = PrivateStateRoot::open(temp.path()).unwrap();
    let mut store = PendingLifecycleStore::open(root.clone()).unwrap();
    store.reserve(pending()).unwrap();
    drop(store);
    let path = temp.path().join("fleet-lifecycle-pending.json");
    let mut value: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["pending"]["request_id"] = 999.into();
    std::fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(PendingLifecycleStore::open(root).is_err());
}
