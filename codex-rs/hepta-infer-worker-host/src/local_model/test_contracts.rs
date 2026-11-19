#[test]
fn signed_grants_reject_forgery_revocation_expiry_and_replay() -> TestResult {
    let original = claims()?;
    let valid = signed(original.clone());
    let mut trusted = verifier(&original, BTreeSet::new())?;
    let mut forged = valid.clone();
    forged.signature[0] ^= 1;
    assert!(matches!(
        trusted.verify(forged),
        Err(LocalModelError::InvalidGrant(_))
    ));
    trusted.verify(valid.clone())?;
    assert!(matches!(
        trusted.verify(valid),
        Err(LocalModelError::GrantReplay)
    ));

    let mut revoked = verifier(&original, BTreeSet::from([original.grant_id.clone()]))?;
    assert!(matches!(
        revoked.verify(signed(original.clone())),
        Err(LocalModelError::GrantRevoked)
    ));

    let mut expired = original;
    expired.not_before_unix_ms = 0;
    expired.expires_at_unix_ms = 1;
    assert!(matches!(
        verifier(&expired, BTreeSet::new())?.verify(signed(expired)),
        Err(LocalModelError::GrantExpired)
    ));
    Ok(())
}

#[tokio::test]
async fn load_revalidates_the_complete_manifest_before_reserving_or_calling_driver() -> TestResult {
    let fixture = Fixture::new()?;
    let manifest = manifest(&fixture.grant)?;
    let mut changed = fixture.grant.claims().clone();
    changed.runtime_digest = "8".repeat(64);
    changed.nonce = "different".to_string();
    let grant = verified(changed)?;
    assert!(matches!(
        fixture
            .worker
            .load_model(
                OperationId::parse("wrong-runtime")?,
                manifest,
                &grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::ManifestBinding)
    ));
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    assert!(fixture.record("local-load:wrong-runtime")?.is_none());
    assert_eq!(
        fixture.worker.resources.snapshot()?.aggregate_memory_bytes,
        0
    );
    Ok(())
}

#[test]
fn worker_construction_binds_the_pool_worker_and_generation() -> TestResult {
    for (worker_id, generation) in [("other-worker", 1), ("worker", 2)] {
        let grant = verified(claims()?)?;
        let resources = ResourceManager::from_grant(&grant)?;
        let directory = tempfile::tempdir()?;
        let control = DurableInferenceControl::open(directory.path().join("control.log"), 64)?;
        let driver = TestDriver::default();
        assert!(matches!(
            ExperimentalLocalModelWorker::new(
                worker_id.to_string(),
                generation,
                8,
                driver.clone(),
                control,
                resources,
            ),
            Err(LocalModelError::GrantBinding)
        ));
        assert_eq!(driver.0.counts(), [0, 0, 0, 0]);
    }
    Ok(())
}

#[tokio::test]
async fn a_different_signed_pool_policy_is_rejected_before_dispatch() -> TestResult {
    let fixture = Fixture::new()?;
    let mut changed = fixture.grant.claims().clone();
    changed.maximum_aggregate_memory_bytes += 1;
    changed.nonce = "different-policy".to_string();
    let grant = verified(changed)?;
    assert!(matches!(
        fixture
            .worker
            .load_model(
                OperationId::parse("wrong-pool")?,
                manifest(&grant)?,
                &grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::GrantBinding)
    ));
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    assert!(fixture.record("local-load:wrong-pool")?.is_none());
    Ok(())
}

#[tokio::test]
async fn run_and_unload_bind_the_loaded_runtime_and_device_lease() -> TestResult {
    for change_runtime in [true, false] {
        let fixture = Fixture::new()?;
        fixture.load().await?;
        let mut changed = fixture.grant.claims().clone();
        changed.nonce = "different-model-binding".to_string();
        if change_runtime {
            changed.runtime_digest = "8".repeat(64);
        } else {
            changed.device_lease_id = "other-lease".to_string();
        }
        let grant = verified(changed)?;
        let run = fixture
            .worker
            .run(
                OperationId::parse("wrong-run")?,
                "model",
                input(&grant)?,
                &grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await;
        assert!(matches!(
            run,
            Err(LocalModelError::ManifestBinding | LocalModelError::GrantBinding)
        ));
        let unload = fixture
            .worker
            .unload_model(
                OperationId::parse("wrong-unload")?,
                "model",
                &grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await;
        assert!(matches!(
            unload,
            Err(LocalModelError::ManifestBinding | LocalModelError::GrantBinding)
        ));
        assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
        assert!(fixture.record("local-run:wrong-run")?.is_none());
        assert!(fixture.record("local-unload:wrong-unload")?.is_none());
    }
    Ok(())
}

#[tokio::test]
async fn renewed_grant_with_the_same_model_and_pool_policy_remains_usable() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    let mut renewal = fixture.grant.claims().clone();
    renewal.nonce = "renewal-nonce".to_string();
    renewal.grant_id = "renewal-grant".to_string();
    let grant = verified(renewal)?;
    assert_ne!(grant.witness_digest(), fixture.grant.witness_digest());
    let result = fixture
        .worker
        .run(
            OperationId::parse("renewed-run")?,
            "model",
            input(&grant)?,
            &grant,
            &CancellationToken::new(),
            deadline()?,
        )
        .await?;
    assert_eq!(result.status, LocalExecutionStatus::Succeeded);
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 0]);
    Ok(())
}

#[test]
fn grant_issuer_epoch_and_frontier_mismatches_do_not_consume_the_nonce() -> TestResult {
    let original = claims()?;
    for variant in 0..4 {
        let mut changed = original.clone();
        match variant {
            0 => changed.issuer_id = "different-issuer".to_string(),
            1 => changed.authority_epoch += 1,
            2 => changed.revocation_revision += 1,
            _ => changed.revocation_head_digest = "8".repeat(64),
        }
        let mut trusted = verifier(&original, BTreeSet::new())?;
        assert!(matches!(
            trusted.verify(signed(changed)),
            Err(LocalModelError::GrantBinding)
        ));
        trusted.verify(signed(original.clone()))?;
    }
    Ok(())
}

#[test]
fn verified_input_enforces_digest_and_granted_token_bounds() -> TestResult {
    let grant = verified(claims()?)?;
    let bytes = b"ordinary input".to_vec();
    let pinned = digest(&bytes);
    let valid = VerifiedInput::verify(bytes.clone(), &pinned, 16, &grant)?;
    assert_eq!(valid.bytes(), bytes.as_slice());
    assert_eq!(valid.digest(), pinned);
    assert_eq!(valid.maximum_tokens(), 16);
    for tokens in [0, grant.claims().maximum_tokens_per_request + 1] {
        assert!(matches!(
            VerifiedInput::verify(bytes.clone(), &pinned, tokens, &grant),
            Err(LocalModelError::InputBinding)
        ));
    }
    assert!(matches!(
        VerifiedInput::verify(bytes, &"9".repeat(64), 16, &grant),
        Err(LocalModelError::InputBinding)
    ));
    Ok(())
}
