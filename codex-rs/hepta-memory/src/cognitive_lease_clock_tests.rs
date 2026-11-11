use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::LocalLeaseAcquire;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseOutboxError;

fn fixture() -> (TempDir, HeptaFleetRoot) {
    let temp = TempDir::new().expect("temporary fleet");
    let root = temp.path().join("fleet");
    std::fs::create_dir(&root).expect("fleet directory");
    let fleet = HeptaFleetRoot::parse(root.canonicalize().expect("canonical fleet"))
        .expect("fleet root");
    (temp, fleet)
}

#[tokio::test]
async fn qualification_clock_is_monotonic_and_bound_to_one_owner() {
    let (_temp, fleet) = fixture();
    let first = AgentId::parse("00000000-0000-4000-8000-000000000961").expect("first owner");
    let second = AgentId::parse("00000000-0000-4000-8000-000000000962").expect("second owner");
    let (store, clock) = CognitiveStore::open_new_with_qualification_lease_clock(
        &fleet.layout().agent(&first),
    )
    .await
    .expect("first new owner");
    let (other, other_clock) = CognitiveStore::open_new_with_qualification_lease_clock(
        &fleet.layout().agent(&second),
    )
    .await
    .expect("second new owner");
    let expires_at = clock.now_unix_seconds().expect("first clock") + 1;
    let other_expires_at = other_clock.now_unix_seconds().expect("second clock") + 1;
    let LocalLeaseAcquire::Acquired(lease) = store
        .acquire_local_lease_bound("lease:clock", 1, 1, 1, "clock-fence", expires_at)
        .await
        .expect("first live lease")
    else {
        panic!("new owner must acquire a lease")
    };
    let LocalLeaseAcquire::Acquired(other_lease) = other
        .acquire_local_lease_bound("lease:clock", 1, 1, 1, "clock-fence", other_expires_at)
        .await
        .expect("second live lease")
    else {
        panic!("new owner must acquire a lease")
    };
    lease.admit("live", "topic", "payload").await.expect("live admission");
    let clone = store.clone();
    clock.advance_to(expires_at).expect("expiry boundary");
    assert!(clock.advance_to(expires_at - 1).is_err());
    assert_eq!(clock.now_unix_seconds().expect("clock"), expires_at);
    assert_eq!(
        clone.inspect_local_lease_head("lease:clock").await.expect("shared clock").disposition,
        LocalLeaseHeadDisposition::ExpiredActive,
    );
    assert!(matches!(
        lease.admit("expired", "topic", "payload").await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    other_lease.admit("still-live", "topic", "payload").await.expect("independent owner");
    assert_eq!(
        other.inspect_local_lease_head("lease:clock").await.expect("other clock").disposition,
        LocalLeaseHeadDisposition::Active,
    );
    drop(lease);
    drop(clone);
    store.close().await;
    assert!(clock.now_unix_seconds().is_err(), "controller must not retain the owner");
    assert!(other_clock.now_unix_seconds().is_ok());
}

#[tokio::test]
async fn qualification_clock_refuses_existing_or_active_store() {
    let (_temp, fleet) = fixture();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000963").expect("owner");
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("ordinary owner");
    assert!(matches!(
        CognitiveStore::open_new_with_qualification_lease_clock(&layout).await,
        Err(CognitiveStoreError::Unavailable(_))
    ));
    store.close().await;
    assert!(matches!(
        CognitiveStore::open_new_with_qualification_lease_clock(&layout).await,
        Err(CognitiveStoreError::Invalid(_))
    ));
}
