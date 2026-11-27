#[tokio::test]
async fn valid_load_run_duplicate_and_unload_release_exact_resources_once() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    assert_eq!(
        fixture.worker.resources.snapshot()?.aggregate_memory_bytes,
        128
    );
    let operation = OperationId::parse("run")?;
    let input = input(&fixture.grant)?;
    let cancellation = CancellationToken::new();
    let deadline = deadline()?;
    let first = fixture
        .worker
        .run(
            operation.clone(),
            "model",
            input.clone(),
            &fixture.grant,
            &cancellation,
            deadline.clone(),
        )
        .await?;
    let duplicate = fixture
        .worker
        .run(
            operation,
            "model",
            input,
            &fixture.grant,
            &cancellation,
            deadline,
        )
        .await?;
    assert_eq!(first, duplicate);
    assert_eq!(first.observed_usage_tokens, Some(7));
    let completed = fixture.worker.resources.snapshot()?;
    assert_eq!(completed.aggregate_memory_bytes, 128);
    assert_eq!(completed.active_requests, 0);
    assert_eq!(completed.observed_usage_tokens, 7);
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 0]);
    fixture
        .worker
        .unload_model(
            OperationId::parse("unload")?,
            "model",
            &fixture.grant,
            &cancellation,
            self::deadline()?,
        )
        .await?;
    let unloaded = fixture.worker.resources.snapshot()?;
    assert_eq!(unloaded.aggregate_memory_bytes, 0);
    assert!(unloaded.models.is_empty());
    assert!(!unloaded.fenced);
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 1]);
    Ok(())
}

#[tokio::test]
async fn cancelled_load_does_not_contact_the_driver_or_retain_resources() -> TestResult {
    let fixture = Fixture::new()?;
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    assert!(matches!(
        fixture
            .worker
            .load_model(
                OperationId::parse("cancel-load")?,
                manifest(&fixture.grant)?,
                &fixture.grant,
                &cancellation,
                deadline()?,
            )
            .await,
        Err(LocalModelError::Cancelled)
    ));
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 0);
    assert!(snapshot.models.is_empty());
    assert!(!snapshot.fenced);
    assert_eq!(
        fixture
            .record("local-load:cancel-load")?
            .ok_or("missing cancelled load")?
            .state,
        NativeReservationState::Released
    );
    Ok(())
}

#[tokio::test]
async fn cancelled_run_and_unload_preserve_the_ready_model_without_driver_contact() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    assert!(matches!(
        fixture
            .worker
            .run(
                OperationId::parse("cancel-run")?,
                "model",
                input(&fixture.grant)?,
                &fixture.grant,
                &cancellation,
                deadline()?,
            )
            .await,
        Err(LocalModelError::Cancelled)
    ));
    assert!(matches!(
        fixture
            .worker
            .unload_model(
                OperationId::parse("cancel-unload")?,
                "model",
                &fixture.grant,
                &cancellation,
                deadline()?,
            )
            .await,
        Err(LocalModelError::Cancelled)
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 128);
    assert_eq!(snapshot.active_requests, 0);
    assert_eq!(snapshot.models[0].state, ModelResourceState::Ready);
    assert!(!snapshot.fenced);
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    assert_eq!(
        fixture
            .record("local-run:cancel-run")?
            .ok_or("missing cancelled run")?
            .state,
        NativeReservationState::Released
    );
    assert_eq!(
        fixture
            .record("local-unload:cancel-unload")?
            .ok_or("missing cancelled unload")?
            .state,
        NativeReservationState::Released
    );
    Ok(())
}

#[test]
fn dropping_a_load_after_driver_entry_retains_memory_and_fences() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.driver.0.load_mode.store(PENDING, Ordering::SeqCst);
    let cancellation = CancellationToken::new();
    let mut future = Box::pin(fixture.worker.load_model(
        OperationId::parse("pending-load")?,
        manifest(&fixture.grant)?,
        &fixture.grant,
        &cancellation,
        deadline()?,
    ));
    assert_pending_once(future.as_mut());
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    drop(future);
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 256);
    assert_eq!(snapshot.models[0].state, ModelResourceState::RepairRequired);
    assert!(snapshot.fenced);
    assert!(matches!(
        fixture.worker.resources.reserve_load("other", 1),
        Err(LocalModelError::ResourceCapacity)
    ));
    assert_eq!(
        fixture
            .record("local-load:pending-load")?
            .ok_or("missing dispatched load")?
            .state,
        NativeReservationState::Dispatching
    );
    Ok(())
}

#[tokio::test]
async fn dropping_a_run_after_driver_entry_retains_transient_and_concurrency() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture.driver.0.run_mode.store(PENDING, Ordering::SeqCst);
    let cancellation = CancellationToken::new();
    let mut future = Box::pin(fixture.worker.run(
        OperationId::parse("pending-run")?,
        "model",
        input(&fixture.grant)?,
        &fixture.grant,
        &cancellation,
        deadline()?,
    ));
    assert_pending_once(future.as_mut());
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 0]);
    drop(future);
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 132);
    assert_eq!(snapshot.active_requests, 1);
    assert!(snapshot.fenced);
    assert!(snapshot.usage_unknown);
    assert!(matches!(
        fixture.worker.resources.reserve_run(1),
        Err(LocalModelError::ResourceCapacity)
    ));
    assert_eq!(
        fixture
            .record("local-run:pending-run")?
            .ok_or("missing dispatched run")?
            .state,
        NativeReservationState::Dispatching
    );
    Ok(())
}

#[tokio::test]
async fn indeterminate_load_keeps_the_reserved_model_as_zombie() -> TestResult {
    let fixture = Fixture::new()?;
    fixture
        .driver
        .0
        .load_mode
        .store(INDETERMINATE, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .worker
            .load_model(
                OperationId::parse("load")?,
                manifest(&fixture.grant)?,
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::DriverIndeterminate(_))
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 256);
    assert_eq!(snapshot.models[0].state, ModelResourceState::Zombie);
    assert!(snapshot.fenced);
    assert_eq!(
        fixture
            .record("local-load:load")?
            .ok_or("missing uncertain load")?
            .state,
        NativeReservationState::Indeterminate
    );
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    Ok(())
}

#[tokio::test]
async fn indeterminate_run_does_not_make_capacity_available_again() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture
        .driver
        .0
        .run_mode
        .store(INDETERMINATE, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .worker
            .run(
                OperationId::parse("uncertain-run")?,
                "model",
                input(&fixture.grant)?,
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::DriverIndeterminate(_))
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 132);
    assert_eq!(snapshot.active_requests, 1);
    assert!(snapshot.fenced);
    assert!(snapshot.usage_unknown);
    assert!(matches!(
        fixture.worker.resources.reserve_run(1),
        Err(LocalModelError::ResourceCapacity)
    ));
    assert_eq!(
        fixture
            .record("local-run:uncertain-run")?
            .ok_or("missing uncertain run")?
            .state,
        NativeReservationState::Indeterminate
    );
    Ok(())
}

#[tokio::test]
async fn nonterminal_observation_and_exact_duplicate_remain_held_without_redispatch() -> TestResult
{
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture
        .driver
        .0
        .run_mode
        .store(NONTERMINAL, Ordering::SeqCst);
    let operation = OperationId::parse("nonterminal")?;
    let input = input(&fixture.grant)?;
    let cancellation = CancellationToken::new();
    let deadline = deadline()?;
    let first = fixture
        .worker
        .run(
            operation.clone(),
            "model",
            input.clone(),
            &fixture.grant,
            &cancellation,
            deadline.clone(),
        )
        .await?;
    let duplicate = fixture
        .worker
        .run(
            operation,
            "model",
            input,
            &fixture.grant,
            &cancellation,
            deadline,
        )
        .await?;
    assert_eq!(first, duplicate);
    assert_eq!(first.status, LocalExecutionStatus::Indeterminate);
    assert!(!first.terminal_observed);
    assert_eq!(first.observed_usage_tokens, None);
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 0]);
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 132);
    assert_eq!(snapshot.active_requests, 1);
    assert!(snapshot.fenced);
    Ok(())
}

#[tokio::test]
async fn terminal_driver_rejection_releases_only_the_run_reservation() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture.driver.0.run_mode.store(REJECTED, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .worker
            .run(
                OperationId::parse("rejected-run")?,
                "model",
                input(&fixture.grant)?,
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::DriverRejected(_))
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 128);
    assert_eq!(snapshot.active_requests, 0);
    assert!(!snapshot.fenced);
    assert_eq!(
        fixture
            .record("local-run:rejected-run")?
            .ok_or("missing rejected run")?
            .state,
        NativeReservationState::Released
    );
    Ok(())
}

#[tokio::test]
async fn failed_unload_retains_model_memory_and_fences() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture
        .driver
        .0
        .unload_mode
        .store(INDETERMINATE, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .worker
            .unload_model(
                OperationId::parse("uncertain-unload")?,
                "model",
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::ReconciliationRequired)
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 128);
    assert_eq!(snapshot.models[0].state, ModelResourceState::Zombie);
    assert!(snapshot.fenced);
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 1]);
    Ok(())
}

#[tokio::test]
async fn terminal_missing_usage_is_preserved_as_unknown_not_zero() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    fixture
        .driver
        .0
        .run_mode
        .store(MISSING_USAGE, Ordering::SeqCst);
    let result = fixture
        .worker
        .run(
            OperationId::parse("missing-usage")?,
            "model",
            input(&fixture.grant)?,
            &fixture.grant,
            &CancellationToken::new(),
            deadline()?,
        )
        .await?;
    assert!(result.terminal_observed);
    assert_eq!(result.observed_usage_tokens, None);
    let snapshot = fixture.worker.resources.snapshot()?;
    assert!(snapshot.usage_unknown);
    assert_eq!(snapshot.observed_usage_tokens, 0);
    assert_eq!(snapshot.aggregate_memory_bytes, 128);
    assert_eq!(snapshot.active_requests, 0);
    Ok(())
}

#[tokio::test]
async fn invalid_load_terminal_attestation_retains_the_reservation() -> TestResult {
    let fixture = Fixture::new()?;
    fixture
        .driver
        .0
        .load_mode
        .store(NONTERMINAL, Ordering::SeqCst);
    assert!(matches!(
        fixture
            .worker
            .load_model(
                OperationId::parse("unconfirmed-load")?,
                manifest(&fixture.grant)?,
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::DriverAttestation)
    ));
    let snapshot = fixture.worker.resources.snapshot()?;
    assert_eq!(snapshot.aggregate_memory_bytes, 256);
    assert_eq!(snapshot.models[0].state, ModelResourceState::Zombie);
    assert!(snapshot.fenced);
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    Ok(())
}

#[tokio::test]
async fn conflicting_duplicate_is_rejected_without_driver_replay() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.load().await?;
    let operation = OperationId::parse("bound-run")?;
    let cancellation = CancellationToken::new();
    let deadline = deadline()?;
    fixture
        .worker
        .run(
            operation.clone(),
            "model",
            input(&fixture.grant)?,
            &fixture.grant,
            &cancellation,
            deadline.clone(),
        )
        .await?;
    let bytes = b"different input".to_vec();
    let changed = VerifiedInput::verify(bytes.clone(), &digest(&bytes), 16, &fixture.grant)?;
    assert!(matches!(
        fixture
            .worker
            .run(
                operation,
                "model",
                changed,
                &fixture.grant,
                &cancellation,
                deadline,
            )
            .await,
        Err(LocalModelError::Journal(
            codex_hepta_infer_core::durable_control::Error::Conflict
        ))
    ));
    assert_eq!(fixture.driver.0.counts(), [1, 1, 0, 0]);
    assert_eq!(
        fixture.worker.resources.snapshot()?.observed_usage_tokens,
        7
    );
    Ok(())
}
