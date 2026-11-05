use super::*;
use codex_hepta_paths::HeptaFleetRoot;

#[tokio::test]
async fn canonical_windows_root_reads_retained_cold_image_without_mutating_source()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempDir::new()?;
    let owner = agent_id(198);
    let (store, access, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await?;
    let expected = store
        .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200)
        .await?;
    let canonical_fleet = temp.path().join("fleet").canonicalize()?;
    let canonical_layout = HeptaFleetRoot::parse(canonical_fleet)?
        .layout()
        .agent(&owner);
    let normalized_root =
        AbsolutePathBuf::try_from(canonical_layout.cognitive_root().to_path_buf())?;
    assert_ne!(canonical_layout.cognitive_root(), normalized_root.as_path());
    store.pool.close().await;
    let before = capture_recovery_tree(canonical_layout.cognitive_root());

    let recovered = CognitiveStore::open_read_only_recovery(
        &canonical_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
    )
    .await?;
    assert_eq!(recovered.anchor(), &anchor);
    assert_eq!(
        recovered
            .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200)
            .await?,
        expected
    );
    assert_eq!(
        capture_recovery_tree(canonical_layout.cognitive_root()),
        before
    );
    let stranger = CognitiveAccess::agent_private(agent_id(199));
    assert!(matches!(
        recovered
            .lane_c_snapshot(&stranger, &CognitiveScope::AgentPrivate, 200)
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    Ok(())
}

#[tokio::test]
async fn canonical_windows_root_recovers_and_reopens_the_original_generation_path()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempDir::new()?;
    let owner = agent_id(200);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await?;
    let canonical_fleet = temp.path().join("fleet").canonicalize()?;
    let canonical_layout = HeptaFleetRoot::parse(canonical_fleet)?
        .layout()
        .agent(&owner);
    let normalized_root =
        AbsolutePathBuf::try_from(canonical_layout.cognitive_root().to_path_buf())?;
    assert_ne!(canonical_layout.cognitive_root(), normalized_root.as_path());
    let source_path = store.path().to_path_buf();
    store.close().await;
    let source_bytes = std::fs::read(&source_path)?;

    let recovered = CognitiveStore::open_with_recovery(
        &canonical_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &recovery_authority(&owner),
        &RecoveryVerifier,
    )
    .await?;
    assert_eq!(recovered.recovery_anchor().await?, anchor);
    assert_eq!(
        recovered.path().parent(),
        Some(canonical_layout.cognitive_root())
    );
    let recovered_path = recovered.path().to_path_buf();
    assert_eq!(recovered_path.canonicalize()?, recovered_path);
    assert_ne!(recovered_path, source_path);
    assert_eq!(std::fs::read(&source_path)?, source_bytes);
    recovered.close().await;

    let reopened = CognitiveStore::open(&canonical_layout).await?;
    assert_eq!(reopened.path(), recovered_path.as_path());
    assert_eq!(reopened.recovery_anchor().await?, anchor);
    reopened.close().await;
    Ok(())
}
