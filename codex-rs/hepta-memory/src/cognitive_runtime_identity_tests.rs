use std::sync::Arc;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveRuntime;
use crate::CognitiveStore;
use crate::CognitiveUnavailableReason;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[tokio::test]
async fn capability_identity_is_not_equal_database_paths_or_equal_contents() {
    let temp = TempDir::new().expect("temp");
    let store = Arc::new(
        CognitiveStore::open(&layout(&temp, &agent_id(1)))
            .await
            .expect("store"),
    );
    let installed = CognitiveRuntime::Available(Arc::clone(&store));
    assert_eq!(installed, installed.clone());
    let separate_handle = Arc::new(
        CognitiveStore::open(&layout(&temp, &agent_id(1)))
            .await
            .expect("second handle"),
    );
    assert_eq!(store.path(), separate_handle.path());
    assert_ne!(installed, CognitiveRuntime::Available(separate_handle));
    assert_ne!(installed, CognitiveRuntime::Absent);
    assert_ne!(
        installed,
        CognitiveRuntime::Unavailable(CognitiveUnavailableReason::StorageUnavailable)
    );
}

#[tokio::test]
async fn federated_identity_includes_consumer_enrollment_and_omission_coverage() {
    let temp = TempDir::new().expect("temp");
    let store = Arc::new(
        CognitiveStore::open(&layout(&temp, &agent_id(1)))
            .await
            .expect("store"),
    );
    let runtime = CognitiveRuntime::Available(Arc::clone(&store));
    let consumer = agent_id(1);
    let owners = vec![layout(&temp, &agent_id(2)), layout(&temp, &agent_id(3))];
    let installed = runtime
        .clone()
        .with_federation_sources(consumer.clone(), owners.clone());
    let mut reversed = owners.clone();
    reversed.reverse();
    assert_eq!(
        installed,
        runtime
            .clone()
            .with_federation_sources(consumer.clone(), reversed)
    );
    assert_eq!(installed, installed.clone());
    assert_ne!(
        installed,
        runtime
            .clone()
            .with_federation_sources(agent_id(4), owners.clone())
    );
    assert_ne!(
        installed,
        runtime.with_federation_sources(consumer.clone(), vec![owners[0].clone()])
    );
    let changed_coverage = CognitiveRuntime::AvailableFederatedV2 {
        store,
        consumer_agent_id: consumer,
        owner_layouts: Arc::new(owners),
        omitted_owner_candidates: 1,
    };
    assert_ne!(installed, changed_coverage);
}

#[test]
fn unavailable_reasons_are_not_collapsed_into_absence() {
    let absent = CognitiveRuntime::Absent;
    let unavailable = CognitiveRuntime::Unavailable(CognitiveUnavailableReason::AccessDenied);
    assert_eq!(absent, CognitiveRuntime::default());
    assert_eq!(unavailable, unavailable.clone());
    assert_ne!(absent, unavailable);
    assert_ne!(
        unavailable,
        CognitiveRuntime::Unavailable(CognitiveUnavailableReason::CorruptStore)
    );
}
