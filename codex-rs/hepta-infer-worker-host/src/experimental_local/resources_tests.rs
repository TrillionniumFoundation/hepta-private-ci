use super::*;

fn manager() -> ResourceManager {
    ResourceManager {
        inner: Arc::new(Mutex::new(ResourceState {
            generation: 7,
            device_epoch: 11,
            maximum_bytes: 1_024,
            maximum_concurrency: 2,
            pending_model_bytes: 0,
            committed_model_bytes: 100,
            request_bytes: 0,
            models: BTreeMap::from([(
                "handle.1".to_string(),
                ModelRecord {
                    bytes: 100,
                    active_requests: 0,
                    lifecycle: ModelLifecycle::Ready,
                },
            )]),
            requests: BTreeMap::new(),
            fenced_reason: None,
        })),
    }
}

fn handle() -> AttestedModelHandle {
    AttestedModelHandle {
        handle_id: "handle.1".to_string(),
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        runtime_digest: "3".repeat(64),
        device_uuid: "device.1".to_string(),
        device_epoch: 11,
        worker_generation: 7,
        resident_memory_bytes: 100,
        manifest_semantic_digest: "4".repeat(64),
        grant_witness_digest: "5".repeat(64),
        resource_attestation_digest: "6".repeat(64),
    }
}

#[test]
fn prepared_drop_releases_without_fencing() {
    let manager = manager();
    let reservation = manager
        .reserve_request("operation.prepared", &handle(), 20)
        .expect("reserve prepared request");
    drop(reservation);

    let snapshot = manager.snapshot().expect("snapshot");
    assert_eq!(snapshot.request_bytes, 0);
    assert_eq!(snapshot.active_or_quarantined_requests, 0);
    assert_eq!(snapshot.fenced_reason, None);
    assert_eq!(
        manager.model_lifecycle("handle.1").expect("lifecycle"),
        Some(ModelLifecycle::Ready)
    );
}

#[test]
fn running_drop_retains_resources_and_fences_generation() {
    let manager = manager();
    let reservation = manager
        .reserve_request("operation.running", &handle(), 20)
        .expect("reserve running request");
    reservation.mark_running().expect("mark running");
    drop(reservation);

    let snapshot = manager.snapshot().expect("snapshot");
    assert_eq!(snapshot.request_bytes, 20);
    assert_eq!(snapshot.active_or_quarantined_requests, 1);
    assert!(snapshot.fenced_reason.is_some());
    assert_eq!(
        manager.model_lifecycle("handle.1").expect("lifecycle"),
        Some(ModelLifecycle::RepairRequired)
    );

    manager
        .resolve_quarantine("operation.running")
        .expect("resolve exact quarantined request");
    let resolved = manager.snapshot().expect("resolved snapshot");
    assert_eq!(resolved.request_bytes, 0);
    assert_eq!(resolved.active_or_quarantined_requests, 0);
    assert!(resolved.fenced_reason.is_some());
}
