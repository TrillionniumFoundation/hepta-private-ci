use super::*;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn original_sql_budget_counts_utf8_bytes_and_rejects_each_complete_read_limit()
    -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let home = tempfile::TempDir::new()?;
    let fleet_path = home.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cee")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    // The existing local qualification owner, never production authority.
    let handle = store.acquire_local_lease_bound("lease:budget", 1, 1, 1, "fixture:budget", u64::MAX / 2)
        .await?.into_handle();
    let scope = Sha256Digest::for_bytes(b"budget scope");
    let mut sizes = Vec::new();
    for (id, payload) in [("budget:one", "abc"), ("budget:two", "原始文"), ("budget:tri", "abc")] {
        let intent = OperationIntentV1::new(StableId::new(id)?, StableId::new(owner.as_str())?,
            StableId::new("destination:budget")?, Digest32::of_bytes(payload.as_bytes()),
            Digest32::of_bytes(b"budget scope"), Generation::new(1)?, None)?;
        handle.admit_operation(intent, "budget", payload).await?;
        let mut transaction = store.pool.begin().await?;
        let size = preflight_bounded(&mut transaction, &handle, &scope, ScopeLimits {
            operations: 3, transitions: 3, bytes: MAX_SCOPE_BYTES,
        }).await?;
        sizes.push(size.bytes);
        transaction.commit().await?;
    }
    // Equal character counts have different UTF-8 byte counts. Event and
    // outbox each retain the original payload once, hence the exact delta.
    assert_eq!(sizes[1] - sizes[0], sizes[2] - sizes[1] + 2 * ("原始文".len() - "abc".len()));
    let mut transaction = store.pool.begin().await?;
    assert_eq!(preflight_bounded(&mut transaction, &handle, &scope, ScopeLimits {
        operations: 3, transitions: 3, bytes: sizes[2],
    }).await?.operations, 3);
    for limits in [
        ScopeLimits { operations: 2, transitions: 3, bytes: sizes[2] },
        ScopeLimits { operations: 3, transitions: 2, bytes: sizes[2] },
        ScopeLimits { operations: 3, transitions: 3, bytes: sizes[2] - 1 },
    ] {
        assert!(preflight_bounded(&mut transaction, &handle, &scope, limits).await.is_err());
    }
    transaction.commit().await?;
    Ok(())
}
