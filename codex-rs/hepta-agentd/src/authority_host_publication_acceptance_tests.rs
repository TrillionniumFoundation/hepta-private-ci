//! Synthetic profile data and actual Root-owned storage negative controls.
//! These tests do not create a live publication acceptance or completed C.

use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;

fn original_scope() -> anyhow::Result<(
    tempfile::TempDir,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    PublicationRefusalBinding,
    ReservedPublicationProfile,
)> {
    let (fixture_dir, _, coordinator) =
        crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
    let initial = coordinator.snapshot().clone();
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"publication-acceptance-test-original-rule"),
    )?;
    let (mut binding, reserved) = fixture::profile()?;
    let mut profile = reserved
        .original_for_version(PublicationVersion::DurableV2)?
        .clone();
    profile.learning_operation = initial.request.operation_id.to_string();
    profile.initial = initial.head_digest.to_string();
    profile.scope = scope.binding().to_string();
    profile.binding = profile.digest()?;
    binding.learning_operation = profile.learning_operation.clone();
    binding.initial = profile.initial.clone();
    binding.scope = profile.scope.clone();
    Ok((
        fixture_dir,
        initial,
        scope,
        binding,
        ReservedPublicationProfile::retain_original(profile)?,
    ))
}

#[test]
fn publication_first_transition_rejects_already_target_and_missing_prepare() -> anyhow::Result<()> {
    let (_, reserved) = fixture::profile()?;
    let intent = &reserved
        .original_for_version(PublicationVersion::DurableV2)?
        .intent;
    let prepared = CurrentHead {
        schema_version: 1,
        current: intent.previous.clone(),
        prepared: Some(intent.clone()),
        published: None,
        initial: None,
    };
    let expected = CurrentHead {
        current: intent.target.clone(),
        prepared: None,
        ..prepared.clone()
    };
    // Only the data precondition succeeds. No signed Published or acceptance
    // is produced from these synthetic comparison inputs.
    PublicationAcceptance::require_first_transition(intent, &prepared, &expected)?;
    assert!(PublicationAcceptance::require_first_transition(intent, &expected, &expected).is_err());
    let mut missing = prepared.clone();
    missing.prepared = None;
    assert!(PublicationAcceptance::require_first_transition(intent, &missing, &expected).is_err());
    let mut substituted = prepared.clone();
    substituted
        .prepared
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("prepared fixture missing"))?
        .operation_id
        .push_str("-other");
    assert!(
        PublicationAcceptance::require_first_transition(intent, &substituted, &expected).is_err()
    );
    assert!(PublicationAcceptance::require_first_transition(intent, &prepared, &prepared).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_completed_publication_missing_acceptance_cannot_be_backfilled() -> anyhow::Result<()> {
    let (_fixture, initial, scope, binding, original) = original_scope()?;
    let (directory, root) = root()?;
    let held = initialize(Arc::clone(&root), binding, &original)?;
    let before = held.store.load(&held.owner)?;
    assert_eq!(before.phase, Phase::Ready);
    assert_eq!(before.publication, None);
    let primary_path = directory.path().join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(PRIMARY.as_bytes()),
    ));
    let primary_before = std::fs::read(&primary_path)?;
    assert!(
        PublicationRefusal::with_completed_history::<()>(
            Arc::clone(&root),
            directory.path(),
            &initial,
            &scope,
            end(),
            |_| panic!("missing first fact cannot enter a completed recipient context"),
        )
        .is_err()
    );
    let after = held.store.load(&held.owner)?;
    assert_eq!(after.phase, Phase::Armed);
    assert_eq!(after.attempt, before.attempt + 1);
    assert_eq!(after.publication, None);
    assert_eq!(after.original, before.original);
    assert_eq!(std::fs::read(&primary_path)?, primary_before);
    drop(held);
    drop(root);
    let reopened = RootAuthorityDirectory::open(directory.path())?;
    assert!(
        PublicationRefusal::with_completed_history::<()>(
            Arc::clone(&reopened),
            directory.path(),
            &initial,
            &scope,
            end(),
            |_| panic!("a fresh handle must not backfill the first acceptance"),
        )
        .is_err()
    );
    let store = HostAuthorityFrontierStore::<RefusalRecord>::open(reopened, after.binding.owner())?;
    assert_eq!(store.load(&after.binding.owner())?, after);
    assert_eq!(std::fs::read(&primary_path)?, primary_before);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_completed_publication_missing_lock_is_not_repaired() -> anyhow::Result<()> {
    let (_fixture, initial, scope, binding, original) = original_scope()?;
    let (directory, root) = root()?;
    let held = initialize(Arc::clone(&root), binding, &original)?;
    let owner = held.owner.clone();
    drop(held);
    let name = format!("frontier-v1-{}.json", Digest32::of_bytes(owner.as_bytes()));
    let primary = directory.path().join(&name);
    let lock = directory.path().join(format!("{name}.lock"));
    let before = std::fs::read(&primary)?;
    assert!(lock.is_file());
    std::fs::remove_file(&lock)?;
    assert!(
        PublicationRefusal::with_completed_history::<()>(
            root,
            directory.path(),
            &initial,
            &scope,
            end(),
            |_| panic!("missing original lock cannot enter history"),
        )
        .is_err()
    );
    assert!(!lock.exists());
    assert_eq!(std::fs::read(&primary)?, before);
    Ok(())
}
