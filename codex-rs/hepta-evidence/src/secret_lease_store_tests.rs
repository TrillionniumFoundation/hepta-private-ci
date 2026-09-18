use codex_hepta_contracts::SecretLeaseOperation;
use codex_hepta_contracts::SecretLeaseRecord;
use codex_hepta_contracts::SecretLeaseState;
use codex_hepta_contracts::SecretLeaseStoreError;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn requesting() -> SecretLeaseRecord {
    SecretLeaseRecord::requesting(
        "lease:database:reader:one".into(),
        "provider:heptabao".into(),
        "team/one".into(),
        "database/creds/reader".into(),
        Sha256Digest::for_bytes(b"logical-request"),
        "operation:issue:one".into(),
        Sha256Digest::for_bytes(b"issue-request"),
    )
    .unwrap()
}

fn active(previous: &SecretLeaseRecord) -> SecretLeaseRecord {
    SecretLeaseRecord {
        schema_version: previous.schema_version,
        lease_key: previous.lease_key.clone(),
        provider_id: previous.provider_id.clone(),
        provider_namespace: previous.provider_namespace.clone(),
        provider_path: previous.provider_path.clone(),
        request_sha256: previous.request_sha256.clone(),
        provider_lease_id: Some("database/creds/reader/provider-lease-one".into()),
        state: SecretLeaseState::Active,
        renewable: true,
        generation: 1,
        issued_at_ms: Some(1_000),
        expires_at_ms: Some(61_000),
        revision: previous.revision + 1,
        pending_operation: None,
        pending_operation_id: None,
        pending_request_sha256: None,
        last_error_code: None,
    }
}

#[tokio::test]
async fn create_is_exact_idempotent_and_survives_reopen() {
    let temp = TempDir::new().unwrap();
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let record = requesting();

    store.create_secret_lease_record(&record).await.unwrap();
    store.create_secret_lease_record(&record).await.unwrap();
    assert_eq!(
        store
            .load_secret_lease_record(&record.lease_key)
            .await
            .unwrap(),
        Some(record.clone())
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert_eq!(
        reopened
            .load_secret_lease_record(&record.lease_key)
            .await
            .unwrap(),
        Some(record)
    );
}

#[tokio::test]
async fn changed_create_conflicts_and_cas_rejects_stale_revision() {
    let temp = TempDir::new().unwrap();
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let record = requesting();
    store.create_secret_lease_record(&record).await.unwrap();

    let changed = SecretLeaseRecord::requesting(
        record.lease_key.clone(),
        record.provider_id.clone(),
        record.provider_namespace.clone(),
        "database/creds/other".into(),
        Sha256Digest::for_bytes(b"other-logical-request"),
        "operation:issue:other".into(),
        Sha256Digest::for_bytes(b"other-issue"),
    )
    .unwrap();
    assert_eq!(
        store.create_secret_lease_record(&changed).await,
        Err(SecretLeaseStoreError::Conflict)
    );

    let active = active(&record);
    store
        .compare_and_swap_secret_lease_record(record.revision, &active)
        .await
        .unwrap();

    let renewing = SecretLeaseRecord {
        state: SecretLeaseState::Renewing,
        revision: active.revision + 1,
        pending_operation: Some(SecretLeaseOperation::Renew),
        pending_operation_id: Some("operation:renew:one".into()),
        pending_request_sha256: Some(Sha256Digest::for_bytes(b"renew-request")),
        ..active.clone()
    };
    assert_eq!(
        store
            .compare_and_swap_secret_lease_record(record.revision, &renewing)
            .await,
        Err(SecretLeaseStoreError::StaleRevision)
    );
}

#[tokio::test]
async fn concurrent_handles_linearize_one_transition() {
    let temp = TempDir::new().unwrap();
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let record = requesting();
    first.create_secret_lease_record(&record).await.unwrap();
    let active = active(&record);

    let left = first.compare_and_swap_secret_lease_record(record.revision, &active);
    let right = second.compare_and_swap_secret_lease_record(record.revision, &active);
    let (left, right) = tokio::join!(left, right);
    let successes = usize::from(left.is_ok()) + usize::from(right.is_ok());
    assert_eq!(successes, 1);
    let failures = [left, right]
        .into_iter()
        .filter_map(Result::err)
        .collect::<Vec<_>>();
    assert_eq!(failures, vec![SecretLeaseStoreError::StaleRevision]);
}
