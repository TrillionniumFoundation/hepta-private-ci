use super::*;
use crate::durable::owner::DurableCompactionStoreV1 as OwnedStore;
use crate::owner_fence::OwnerWriteFenceV2;

#[derive(Clone, Copy)]
struct TestLease {
    token: &'static str,
    epoch: u64,
    expires: u64,
}

fn first_lease() -> TestLease {
    TestLease {
        token: "lease:contracts:one",
        epoch: 1,
        expires: NOW + 600,
    }
}

async fn open_owner(
    url: &str,
    fixture: &ProductTrustFixture,
    lease: TestLease,
    now: u64,
) -> Result<MemoryCheckpointCoordinatorV2, CompactionCoordinatorErrorV2> {
    MemoryCheckpointCoordinatorV2::open(
        url,
        fixture.registry.owner_id().as_str(),
        fixture.root.verifying_key().to_bytes(),
        &fixture.manifest_bytes,
        lease.token,
        lease.epoch,
        lease.expires,
        now,
    )
    .await
}

async fn open_store(
    url: &str,
    fixture: &ProductTrustFixture,
    lease: TestLease,
    manifest: Digest32,
    now: u64,
) -> Result<OwnedStore, DurableCompactionError> {
    OwnedStore::open(
        url,
        fixture.registry.owner_id().as_str(),
        OwnerWriteFenceV2 {
            root_key_digest: Digest32::of_bytes(&fixture.root.verifying_key().to_bytes()),
            lease_token_digest: Digest32::of_bytes(lease.token.as_bytes()),
            lease_epoch: lease.epoch,
            minimum_expiry_unix_seconds: lease.expires,
        },
        manifest,
        now,
    )
    .await
}

fn assert_storage_conflict<T>(result: Result<T, DurableCompactionError>) {
    assert!(matches!(result, Err(DurableCompactionError::Conflict(_))));
}

fn successor_bytes(fixture: &ProductTrustFixture) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut manifest = fixture.registry.manifest().clone();
    manifest.sequence += 1;
    manifest.predecessor_manifest_digest = Some(fixture.registry.manifest_digest());
    manifest.signature = fixture.root.sign(&manifest.signing_bytes()?).to_bytes();
    Ok(manifest.encode()?)
}

#[test]
fn evaluator_subject_remains_distinct_from_its_signing_key()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:subject:owner");
    let mut fixture = ProductTrustFixture::new(&owner);
    assert_ne!(
        fixture.evaluator.evaluator_id,
        fixture.evaluator.enrollment.key_id
    );
    let accepted =
        try_sealed_publication(&fixture, &["memory:subject"], 1, 1, None, "subject-valid")?;
    assert_eq!(
        accepted.proof().proof.evaluator_id,
        fixture.evaluator.evaluator_id
    );
    fixture.evaluator.evaluator_id = id("evaluator:unregistered-subject");
    assert!(
        try_sealed_publication(&fixture, &["memory:subject"], 1, 1, None, "subject-invalid",)
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn durable_cas_requires_actual_genesis_and_exact_predecessor()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:lineage:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new()?;
    let url = database_url(&temp);
    let coordinator = open_owner(&url, &fixture, first_lease(), NOW).await?;
    let missing = sealed_publication(
        &fixture,
        &["memory:lineage"],
        1,
        2,
        Some(digest("absent-predecessor")),
        "missing-genesis",
    );
    assert!(matches!(
        coordinator
            .publish_verified_checkpoint("missing-genesis", &missing, NOW + 500, NOW)
            .await,
        Err(CompactionCoordinatorErrorV2::Durable(
            DurableCompactionError::Conflict(_)
        )),
    ));
    assert!(
        coordinator
            .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW)
            .await?
            .is_none()
    );
    let first = sealed_publication(&fixture, &["memory:lineage"], 1, 1, None, "actual-genesis");
    let first_digest = first.candidate().checkpoint().checkpoint_digest;
    coordinator
        .publish_verified_checkpoint("actual-genesis", &first, NOW + 500, NOW)
        .await?;
    let wrong = sealed_publication(
        &fixture,
        &["memory:lineage"],
        1,
        2,
        Some(digest("wrong-predecessor")),
        "wrong-successor",
    );
    assert!(matches!(
        coordinator
            .publish_verified_checkpoint("wrong-successor", &wrong, NOW + 500, NOW)
            .await,
        Err(CompactionCoordinatorErrorV2::Durable(
            DurableCompactionError::Conflict(_)
        )),
    ));
    let current = coordinator
        .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW)
        .await?
        .ok_or("genesis disappeared after rejected successor")?;
    assert_eq!(current.checkpoint_digest(), first_digest);
    let second = sealed_publication(
        &fixture,
        &["memory:lineage"],
        1,
        2,
        Some(first_digest),
        "actual-successor",
    );
    coordinator
        .publish_verified_checkpoint("actual-successor", &second, NOW + 500, NOW)
        .await?;
    let current = coordinator
        .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW)
        .await?
        .ok_or("successor missing")?;
    assert_eq!(current.generation(), 2);
    assert_eq!(
        current.checkpoint_digest(),
        second.candidate().checkpoint().checkpoint_digest
    );
    Ok(())
}

#[tokio::test]
async fn outbox_and_revocation_writes_reject_replaced_owner()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:replacement:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new()?;
    let url = database_url(&temp);
    let lease = first_lease();
    let coordinator = open_owner(&url, &fixture, lease, NOW).await?;
    let first = sealed_publication(&fixture, &["memory:replacement"], 1, 1, None, "replacement");
    let checkpoint = first.candidate().checkpoint().checkpoint_digest;
    coordinator
        .publish_verified_checkpoint("replacement", &first, NOW + 500, NOW)
        .await?;
    let stale = open_store(
        &url,
        &fixture,
        lease,
        fixture.registry.manifest_digest(),
        NOW,
    )
    .await?;
    let event = stale
        .claim_next_outbox(NOW, "original-claim")
        .await?
        .ok_or("publication outbox missing")?;
    let next_lease = TestLease {
        token: "lease:contracts:two",
        epoch: 2,
        expires: NOW + 1200,
    };
    let successor = open_owner(&url, &fixture, next_lease, NOW + 601).await?;
    let current = open_store(
        &url,
        &fixture,
        next_lease,
        fixture.registry.manifest_digest(),
        NOW + 601,
    )
    .await?;
    assert_storage_conflict(stale.claim_next_outbox(NOW + 602, "stale-claim").await);
    assert_storage_conflict(stale.complete_outbox(&event, NOW + 602).await);
    assert_storage_conflict(stale.reconcile_claims(NOW + 602).await);
    assert_storage_conflict(
        stale
            .revoke_trust(
                CompactionTrustRoleV1::Evaluator,
                &fixture.evaluator.enrollment.key_id,
                1,
                NOW + 602,
            )
            .await,
    );
    assert_storage_conflict(
        stale
            .revoke_checkpoint(checkpoint, digest("stale-reason"), NOW + 602)
            .await,
    );
    // These valid writes/readbacks would fail if a rejected stale call had
    // consumed the claim, reconciled it, revoked the checkpoint or revoked trust.
    current.complete_outbox(&event, NOW + 603).await?;
    assert_eq!(current.reconcile_claims(NOW + 603).await?, 0);
    let recovered = successor
        .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW + 603)
        .await?
        .ok_or("checkpoint changed during rejected writes")?;
    assert_eq!(recovered.checkpoint_digest(), checkpoint);
    current
        .revoke_trust(
            CompactionTrustRoleV1::Evaluator,
            &fixture.evaluator.enrollment.key_id,
            1,
            NOW + 604,
        )
        .await?;
    current
        .revoke_checkpoint(checkpoint, digest("current-reason"), NOW + 604)
        .await?;
    Ok(())
}

#[tokio::test]
async fn manifest_successor_fences_an_earlier_store_snapshot()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:manifest:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new()?;
    let url = database_url(&temp);
    let lease = first_lease();
    let mut coordinator = open_owner(&url, &fixture, lease, NOW).await?;
    let stale = open_store(
        &url,
        &fixture,
        lease,
        fixture.registry.manifest_digest(),
        NOW,
    )
    .await?;
    let bytes = successor_bytes(&fixture)?;
    let digest = coordinator
        .install_successor_manifest(&bytes, NOW + 1)
        .await?;
    assert_ne!(digest, fixture.registry.manifest_digest());
    assert_storage_conflict(stale.claim_next_outbox(NOW + 1, "stale-manifest").await);
    assert_storage_conflict(stale.reconcile_claims(NOW + 1).await);
    let current = open_store(&url, &fixture, lease, digest, NOW + 1).await?;
    assert!(
        current
            .claim_next_outbox(NOW + 1, "current-manifest")
            .await?
            .is_none()
    );
    Ok(())
}

#[tokio::test]
async fn logical_lease_deadline_is_exclusive_for_final_writes()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:expiry:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new()?;
    let url = database_url(&temp);
    let lease = first_lease();
    let _coordinator = open_owner(&url, &fixture, lease, NOW).await?;
    let store = open_store(
        &url,
        &fixture,
        lease,
        fixture.registry.manifest_digest(),
        NOW,
    )
    .await?;
    assert!(
        store
            .claim_next_outbox(lease.expires - 1, "before-expiry")
            .await?
            .is_none()
    );
    assert_storage_conflict(store.claim_next_outbox(lease.expires, "at-expiry").await);
    assert_storage_conflict(store.reconcile_claims(lease.expires).await);
    Ok(())
}

#[tokio::test]
async fn refused_owner_acquisition_cannot_activate_a_signed_successor()
-> Result<(), Box<dyn std::error::Error>> {
    let owner = id("agent:bootstrap:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new()?;
    let url = database_url(&temp);
    let mut coordinator = open_owner(&url, &fixture, first_lease(), NOW).await?;
    let next = successor_bytes(&fixture)?;
    let result = MemoryCheckpointCoordinatorV2::open_with_manifest_chain(
        &url,
        owner.as_str(),
        fixture.root.verifying_key().to_bytes(),
        &[fixture.manifest_bytes.clone(), next.clone()],
        "lease:unavailable:second",
        2,
        NOW + 1200,
        NOW + 1,
    )
    .await;
    assert!(matches!(
        result,
        Err(CompactionCoordinatorErrorV2::Durable(
            DurableCompactionError::Conflict(_)
        )),
    ));
    assert_eq!(
        coordinator.active_registry_digest(),
        fixture.registry.manifest_digest()
    );
    assert!(
        coordinator
            .claim_next_outbox(NOW + 1, "original-owner")
            .await?
            .is_none()
    );
    let next_digest = coordinator
        .install_successor_manifest(&next, NOW + 2)
        .await?;
    assert_ne!(next_digest, fixture.registry.manifest_digest());
    assert!(
        coordinator
            .claim_next_outbox(NOW + 2, "successor-owner")
            .await?
            .is_none()
    );
    Ok(())
}
