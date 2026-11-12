//! Real Root/Registry/CAS qualification, separately selected under the
//! existing protected-bind harness. Synthetic metadata is not an A/B/C run.

use super::super::RootResidentLearningProfileV3;
use super::super::RootResidentLearningRegistrationV3;
use super::super::store::ResidentCheckpointV3;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

#[path = "authority_host_learning_resident_metadata_tests.rs"]
mod metadata;
#[path = "authority_host_learning_resident_root_support_tests.rs"]
mod support;

use metadata::ResidentMetadata;
use metadata::digest;
use support::ResidentRootFixture;

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_formatter_and_original_registration_pin_both_scopes() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let canonical = RootResidentLearningProfileV3::admission_binding(
        &metadata.initial, &metadata.scope, &metadata.verifier,
    )?;
    assert_eq!(canonical, fixture.profile.intent.grant.binding);
    let changed_scope = FrozenLearningScopeV2::freeze(
        &metadata.initial.request, &metadata.initial.owners, LearningUpdateScopeV2::Cell,
        digest("different-resident-frozen-rule"),
    )?;
    let changed = RootResidentLearningProfileV3::admission_binding(
        &metadata.initial, &changed_scope, &metadata.verifier,
    )?;
    assert_ne!(changed, canonical);
    assert!(RootResidentLearningProfileV3::new(
        metadata.initial.clone(), changed_scope, &metadata.verifier,
        fixture.profile.intent.clone(), fixture.profile.lease.clone(),
    ).is_err());
    let other_verifier = metadata.other_evidence_scope()?;
    assert_eq!(other_verifier.objective_digest(), metadata.verifier.objective_digest());
    assert_ne!(other_verifier.scope_digest(), metadata.verifier.scope_digest());
    // The original initial trust is retained. A real changed-scope verifier
    // also has a different trust digest; do not forge an impossible verifier.
    assert!(RootResidentLearningProfileV3::admission_binding(
        &metadata.initial, &metadata.scope, &other_verifier,
    ).is_err());
    assert!(fixture.profile.require_verifier(&other_verifier).is_err());
    let mut request = metadata.initial.request.clone();
    request.envelope.expiry_unix_seconds += 1;
    let changed_initial = LearningIterationCoordinatorV1::new(
        request, metadata.initial.owners.clone(),
    )?.snapshot().clone();
    let changed_rule_scope = FrozenLearningScopeV2::freeze(
        &changed_initial.request, &changed_initial.owners, LearningUpdateScopeV2::Cell,
        digest("resident-fixture-frozen-rule"),
    )?;
    assert!(RootResidentLearningProfileV3::new(
        changed_initial, changed_rule_scope, &metadata.verifier,
        fixture.profile.intent.clone(), fixture.profile.lease.clone(),
    ).is_err());
    Ok(())
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_reissued_intent_cannot_create_another_operation_namespace() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let registration = fixture.registration.as_ref().expect("original registration");
    let authority = &registration.owner.authority;
    let reissued = authority.issuer.issue(&fixture.profile.intent.grant.binding)?
        .ok_or_else(|| anyhow::anyhow!("explicit original reissued intent"))?;
    let rebound = RootResidentLearningProfileV3::new(
        metadata.initial, metadata.scope, &metadata.verifier,
        reissued, fixture.profile.lease.clone(),
    )?;
    assert_eq!(fixture.profile.owner_id(), rebound.owner_id());
    assert_ne!(fixture.profile.binding(), rebound.binding());
    let root = RootAuthorityDirectory::open(&fixture.config.state_dir)?;
    assert!(RootResidentLearningRegistrationV3::register_original_root(
        Arc::clone(&root), Arc::clone(&authority.issuer), Arc::clone(&authority.registry),
        rebound.clone(),
    ).is_err());
    assert!(ResidentCheckpointV3::recover(root, rebound).is_err());
    assert!(registration.owner.checkpoint.read()?.snapshot.is_none());
    Ok(())
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_only_actual_vacant_cas_creates_one_live_continuation() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let original = &fixture.registration.as_ref().expect("original registration").owner;
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async {
        let cancellation = CancellationToken::new();
        assert!(original.read(&cancellation).await?.0.snapshot.is_none());
        let continuation = original.admit(&cancellation).await?
            .ok_or_else(|| anyhow::anyhow!("actual first CAS did not admit"))?;
        let gate = Arc::clone(&continuation.gate);
        assert_eq!(original.read(&cancellation).await?.0.snapshot, Some(metadata.initial.clone()));
        assert!(original.admit(&cancellation).await?.is_none());
        gate.begin(&metadata.initial, LearningIterationStageV1::Experience).await?;
        gate.require_current(&metadata.initial, &metadata.scope).await?;
        let pending = original.read(&cancellation).await?.0;
        assert!(pending.dispatch_pending);
        drop(continuation);
        assert!(gate.training_cancellation().load(std::sync::atomic::Ordering::Acquire));
        assert!(gate.require_current(&metadata.initial, &metadata.scope).await.is_err());
        assert!(original.admit(&cancellation).await?.is_none());
        assert_eq!(original.read(&cancellation).await?.0.snapshot, pending.snapshot);
        Ok::<_, anyhow::Error>(())
    })
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_same_epoch_grant_revocation_fences_the_pending_effect() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let original = &fixture.registration.as_ref().expect("original registration").owner;
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async {
        let continuation = original.admit(&CancellationToken::new()).await?
            .ok_or_else(|| anyhow::anyhow!("actual first CAS"))?;
        continuation.gate.begin(&metadata.initial, LearningIterationStageV1::Experience).await?;
        let before = original.authority.registry.frontier()?;
        let revoked = original.authority.issuer.revoke(&fixture.profile.intent.grant.grant_id)?;
        assert_eq!(revoked.authority_epoch, fixture.profile.intent.grant.authority_epoch);
        assert_eq!(original.authority.registry.frontier()?.authority_epoch, before.authority_epoch);
        assert!(revoked.revoked_grant_ids.contains(&fixture.profile.intent.grant.grant_id));
        assert!(continuation.gate.require_current(&metadata.initial, &metadata.scope).await.is_err());
        assert!(continuation.gate.training_cancellation().load(std::sync::atomic::Ordering::Acquire));
        assert!(original.checkpoint.read()?.dispatch_pending);
        Ok::<_, anyhow::Error>(())
    })
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_exact_lease_revocation_fences_without_restarting_dispatch() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let original = &fixture.registration.as_ref().expect("original registration").owner;
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async {
        let cancellation = CancellationToken::new();
        let continuation = original.admit(&cancellation).await?
            .ok_or_else(|| anyhow::anyhow!("actual first CAS"))?;
        continuation.gate.begin(&metadata.initial, LearningIterationStageV1::Experience).await?;
        original.authority.registry.revoke(
            &fixture.profile.lease.lease_id, fixture.profile.lease.revision,
            *digest("resident-original-lease-withdrawal").as_array(),
        )?;
        assert!(continuation.gate.require_current(&metadata.initial, &metadata.scope).await.is_err());
        assert!(original.admit(&cancellation).await.is_err());
        assert!(original.checkpoint.read()?.dispatch_pending);
        Ok::<_, anyhow::Error>(())
    })
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let mut fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async {
        let original = &fixture.registration.as_ref().expect("original registration").owner;
        // Actual Root CAS occurred, but no token or admission reply was retained.
        let unobserved = original.admit(&CancellationToken::new()).await?;
        assert!(unobserved.is_some());
        drop(unobserved);
        Ok::<_, anyhow::Error>(())
    })?;
    fixture.recover()?;
    runtime.block_on(async {
        let recovered = &fixture.registration.as_ref().expect("readback registration").owner;
        assert!(recovered.authority.readonly());
        assert_eq!(
            recovered.read(&CancellationToken::new()).await?.0.snapshot,
            Some(metadata.initial.clone()),
        );
        assert!(recovered.admit(&CancellationToken::new()).await.is_err());
        assert!(!recovered.checkpoint.read()?.dispatch_pending);
        Ok::<_, anyhow::Error>(())
    })?;
    fixture.registration.take();
    assert!(crate::register_host_resident_learning_v3(
        &fixture.config_file, fixture.profile.clone(),
    ).is_err());
    fixture.recover()?;
    Ok(())
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial, metadata.scope, &metadata.verifier,
    )?;
    super::super::transport::test_support::queued_admit_cancellation(
        fixture.profile.clone(), metadata.verifier,
    )?;
    assert!(fixture.registration.as_ref().expect("original registration")
        .owner.checkpoint.read()?.snapshot.is_none());
    Ok(())
}

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn resident_root_structured_uncertain_allows_only_same_operation_readback() -> anyhow::Result<()> {
    let metadata = ResidentMetadata::new()?;
    let fixture = ResidentRootFixture::new(
        metadata.initial.clone(), metadata.scope.clone(), &metadata.verifier,
    )?;
    let (completed, signatures) = metadata.completed_metadata()?;
    super::super::transport::test_support::uncertain_then_readback(
        fixture.profile, metadata.verifier, completed, signatures,
    )
}
