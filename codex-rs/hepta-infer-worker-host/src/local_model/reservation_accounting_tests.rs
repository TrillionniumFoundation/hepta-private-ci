use super::*;

fn resource_manager() -> ResourceManager {
    ResourceManager {
        inner: Arc::new(Mutex::new(ResourceState {
            worker_id: "worker".to_string(),
            issuer_id: "issuer".to_string(),
            authority_epoch: 1,
            device_id: "device".to_string(),
            device_lease_id: "lease".to_string(),
            generation: 1,
            maximum_memory: 1_024,
            maximum_models: 2,
            maximum_concurrency: 2,
            maximum_total_usage: 1_000,
            aggregate_memory: 0,
            active_requests: 0,
            observed_usage: 0,
            usage_unknown: false,
            fenced: false,
            models: BTreeMap::new(),
        })),
    }
}

#[test]
fn observed_load_bytes_are_retained_and_released_exactly() -> Result<(), LocalModelError> {
    let resources = resource_manager();
    resources.reserve_load("model", 512)?.commit(128)?;

    let loaded = resources.snapshot()?;
    assert_eq!(loaded.aggregate_memory_bytes, 128);
    assert_eq!(
        loaded.models,
        vec![ModelResourceSnapshot {
            model_id: "model".to_string(),
            memory_bytes: 128,
            state: ModelResourceState::Ready,
        }]
    );
    assert!(!loaded.fenced);

    resources.begin_unload("model")?.complete(128)?;
    let unloaded = resources.snapshot()?;
    assert_eq!(unloaded.aggregate_memory_bytes, 0);
    assert!(unloaded.models.is_empty());
    assert_eq!(unloaded.active_requests, 0);
    assert!(!unloaded.fenced);
    Ok(())
}

#[test]
fn oversized_load_observation_keeps_the_original_reservation() -> Result<(), LocalModelError> {
    let resources = resource_manager();
    assert!(matches!(
        resources.reserve_load("model", 512)?.commit(513),
        Err(LocalModelError::DriverAttestation)
    ));

    let rejected = resources.snapshot()?;
    assert_eq!(rejected.aggregate_memory_bytes, 512);
    assert_eq!(
        rejected.models,
        vec![ModelResourceSnapshot {
            model_id: "model".to_string(),
            memory_bytes: 512,
            state: ModelResourceState::RepairRequired,
        }]
    );
    assert!(rejected.fenced);
    Ok(())
}
