use super::*;

#[tokio::test]
async fn replaced_lock_fences_old_host_before_any_mutation() -> FixtureResult<()> {
    for checkpoint_lock in [false, true] {
        let (_root, database, checkpoint, host, first) = initialized_host().await?;
        let protected = if checkpoint_lock {
            &checkpoint
        } else {
            &database
        };
        let name = protected
            .file_name()
            .ok_or("missing file name")?
            .to_str()
            .ok_or("file name")?;
        let lock = protected.with_file_name(format!(".{name}.owner.lock"));
        std::fs::rename(&lock, lock.with_extension("retired"))?;
        let successor = AuthBusAuthorityHost::open(&database, checkpoint.clone(), OWNER_ID).await?;
        let before = host.store.authority_frontier_digest().await?;
        assert!(matches!(
            host.enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:stale-lock", 94)?
            )
            .await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert_eq!(host.store.authority_frontier_digest().await?, before);
        assert_eq!(host.checkpoint.read()?, first);
        successor
            .enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:current-lock", 95)?,
            )
            .await?;
        assert_eq!(
            successor.checkpoint.read()?.generation,
            first.generation + 1
        );
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
    }
    Ok(())
}

#[tokio::test]
async fn deleted_lock_cannot_be_silently_recreated_by_a_stale_handle() -> FixtureResult<()> {
    for checkpoint_lock in [false, true] {
        let (_root, database, checkpoint, host, first) = initialized_host().await?;
        let protected = if checkpoint_lock {
            &checkpoint
        } else {
            &database
        };
        let name = protected
            .file_name()
            .ok_or("missing file name")?
            .to_str()
            .ok_or("file name")?;
        let lock = protected.with_file_name(format!(".{name}.owner.lock"));
        std::fs::remove_file(&lock)?;
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert!(!lock.exists());
        assert_eq!(host.checkpoint.read()?, first);
        let reopened = AuthBusAuthorityHost::open(&database, checkpoint, OWNER_ID).await?;
        reopened.sync_checkpoint().await?;
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
    }
    Ok(())
}

#[tokio::test]
async fn lock_permission_and_link_drift_reject_before_writing() -> FixtureResult<()> {
    for drift in ["hardlink", "file-mode", "directory-mode"] {
        let (_root, database, checkpoint, host, first) = initialized_host().await?;
        let lock = database.with_file_name(".authbus.sqlite.owner.lock");
        let alias = lock.with_extension("alias");
        let parent = database.parent().ok_or("database parent")?;
        match drift {
            "hardlink" => std::fs::hard_link(&lock, &alias)?,
            "file-mode" => std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o644))?,
            "directory-mode" => {
                std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o755))?
            }
            _ => unreachable!(),
        }
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        if alias.exists() {
            std::fs::remove_file(alias)?;
        }
        std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o600))?;
        std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700))?;
        assert_eq!(host.checkpoint.read()?, first);
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        AuthBusAuthorityHost::open(&database, checkpoint, OWNER_ID)
            .await?
            .sync_checkpoint()
            .await?;
    }
    Ok(())
}

#[tokio::test]
async fn lock_replacement_during_a_mutation_cannot_acknowledge_unpublished_state()
-> FixtureResult<()> {
    let (_root, database, checkpoint, host, first) = initialized_host().await?;
    let lock = database.with_file_name(".authbus.sqlite.owner.lock");
    let spec = issuer_spec("issuer:interrupted-lock", 96)?;
    let result = host
        .run_mutation(|store| async move {
            std::fs::rename(&lock, lock.with_extension("retired")).map_err(storage)?;
            store.enroll_issuer(IssuerPurpose::Message, spec).await
        })
        .await;
    assert!(matches!(
        result,
        Err(AuthBusAuthorityError::UnsafeCheckpoint)
    ));
    assert_eq!(host.checkpoint.read()?, first);
    let reopened = AuthBusAuthorityHost::open(&database, checkpoint, OWNER_ID).await?;
    let recovered = reopened.checkpoint.read()?;
    assert_eq!(recovered.generation, first.generation + 1);
    assert_eq!(
        reopened.store.authority_checkpoint().await?,
        Some(recovered)
    );
    assert_eq!(
        reopened
            .store
            .issuer_record(
                IssuerPurpose::Message,
                &id("issuer:interrupted-lock")?,
                Generation::new(1)?
            )
            .await?
            .state,
        IssuerLifecycleState::Active
    );
    Ok(())
}
