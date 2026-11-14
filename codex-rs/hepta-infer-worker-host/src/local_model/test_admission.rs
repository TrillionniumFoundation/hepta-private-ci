// These controls model the exact pre-dispatch interleaving using the real
// journal owner and resource guards; they do not execute a model.
#[tokio::test]
async fn duplicate_reserved_load_preserves_the_first_admission() -> TestResult {
    let fixture = Fixture::new()?;
    let operation = OperationId::parse("reserved-load")?;
    let manifest = manifest(&fixture.grant)?;
    let deadline = deadline()?;
    let request_id = format!("local-load:{}", operation.as_str());
    let payload = digest(
        &[
            manifest.envelope.manifest_digest.as_bytes(),
            fixture.grant.witness_digest().as_bytes(),
            &deadline.unix_ms().to_be_bytes(),
        ]
        .concat(),
    );
    let first = fixture
        .worker
        .reserve(&request_id, &manifest.envelope.model_id, payload)?;
    assert_eq!(first.state, NativeReservationState::Reserved);
    let first_resource = fixture.worker.resources.reserve_load(
        &manifest.envelope.model_id,
        manifest.envelope.maximum_memory_bytes,
    )?;
    let resources = fixture.worker.resources.snapshot()?;
    let journal = std::fs::read(fixture._directory.path().join("control.log"))?;

    assert!(matches!(
        fixture
            .worker
            .load_model(
                operation,
                manifest,
                &fixture.grant,
                &CancellationToken::new(),
                deadline,
            )
            .await,
        Err(LocalModelError::ReconciliationRequired)
    ));
    assert_eq!(fixture.record(&request_id)?, Some(first));
    assert_eq!(fixture.worker.resources.snapshot()?, resources);
    assert_eq!(
        std::fs::read(fixture._directory.path().join("control.log"))?,
        journal
    );
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    drop(first_resource);
    Ok(())
}

#[tokio::test]
async fn duplicate_reserved_run_preserves_the_first_admission() -> TestResult {
    let fixture = Fixture::new()?;
    let handle = fixture.load().await?;
    let operation = OperationId::parse("reserved-run")?;
    let input = input(&fixture.grant)?;
    let deadline = deadline()?;
    let request_id = format!("local-run:{}", operation.as_str());
    let payload = digest(
        &[
            input.digest.as_bytes(),
            fixture.grant.witness_digest().as_bytes(),
            handle.attestation_digest.as_bytes(),
            &input.maximum_tokens.to_be_bytes(),
            &deadline.unix_ms().to_be_bytes(),
        ]
        .concat(),
    );
    let first = fixture.worker.reserve(&request_id, "model", payload)?;
    assert_eq!(first.state, NativeReservationState::Reserved);
    let first_resource = fixture
        .worker
        .resources
        .reserve_run(u64::try_from(input.bytes.len())?)?;
    let resources = fixture.worker.resources.snapshot()?;
    let journal = std::fs::read(fixture._directory.path().join("control.log"))?;

    assert!(matches!(
        fixture
            .worker
            .run(
                operation,
                "model",
                input,
                &fixture.grant,
                &CancellationToken::new(),
                deadline,
            )
            .await,
        Err(LocalModelError::ReconciliationRequired)
    ));
    assert_eq!(fixture.record(&request_id)?, Some(first));
    assert_eq!(fixture.worker.resources.snapshot()?, resources);
    assert_eq!(
        std::fs::read(fixture._directory.path().join("control.log"))?,
        journal
    );
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    drop(first_resource);
    Ok(())
}

#[tokio::test]
async fn duplicate_reserved_unload_preserves_the_first_admission() -> TestResult {
    let fixture = Fixture::new()?;
    let handle = fixture.load().await?;
    let operation = OperationId::parse("reserved-unload")?;
    let deadline = deadline()?;
    let request_id = format!("local-unload:{}", operation.as_str());
    let payload = digest(
        &[
            handle.attestation_digest.as_bytes(),
            fixture.grant.witness_digest().as_bytes(),
            &deadline.unix_ms().to_be_bytes(),
        ]
        .concat(),
    );
    let first = fixture.worker.reserve(&request_id, "model", payload)?;
    assert_eq!(first.state, NativeReservationState::Reserved);
    let first_resource = fixture.worker.resources.begin_unload("model")?;
    let resources = fixture.worker.resources.snapshot()?;
    let journal = std::fs::read(fixture._directory.path().join("control.log"))?;

    assert!(matches!(
        fixture
            .worker
            .unload_model(
                operation,
                "model",
                &fixture.grant,
                &CancellationToken::new(),
                deadline,
            )
            .await,
        Err(LocalModelError::ReconciliationRequired)
    ));
    assert_eq!(fixture.record(&request_id)?, Some(first));
    assert_eq!(fixture.worker.resources.snapshot()?, resources);
    assert_eq!(
        std::fs::read(fixture._directory.path().join("control.log"))?,
        journal
    );
    assert_eq!(fixture.driver.0.counts(), [1, 0, 0, 0]);
    first_resource.abort_before_dispatch()?;
    assert_eq!(
        fixture.worker.resources.snapshot()?.models[0].state,
        ModelResourceState::Ready
    );
    Ok(())
}

#[tokio::test]
async fn conflicting_reserved_payload_keeps_the_original_journal_error() -> TestResult {
    let fixture = Fixture::new()?;
    let operation = OperationId::parse("reserved-conflict")?;
    let request_id = format!("local-load:{}", operation.as_str());
    let first = fixture
        .worker
        .reserve(&request_id, "model", "e".repeat(64))?;
    let resources = fixture.worker.resources.snapshot()?;
    let journal = std::fs::read(fixture._directory.path().join("control.log"))?;

    assert!(matches!(
        fixture
            .worker
            .load_model(
                operation,
                manifest(&fixture.grant)?,
                &fixture.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await,
        Err(LocalModelError::Journal(
            codex_hepta_infer_core::durable_control::Error::Conflict
        ))
    ));
    assert_eq!(fixture.record(&request_id)?, Some(first));
    assert_eq!(fixture.worker.resources.snapshot()?, resources);
    assert_eq!(
        std::fs::read(fixture._directory.path().join("control.log"))?,
        journal
    );
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    Ok(())
}

#[test]
fn first_admission_can_dispatch_settle_and_return_the_same_terminal_record() -> TestResult {
    let fixture = Fixture::new()?;
    let request_id = "local-run:original-owner";
    let payload = "e".repeat(64);
    let first = fixture
        .worker
        .reserve(request_id, "model", payload.clone())?;
    assert_eq!(first.state, NativeReservationState::Reserved);
    assert!(matches!(
        fixture.worker.reserve(request_id, "model", payload.clone()),
        Err(LocalModelError::ReconciliationRequired)
    ));
    assert_eq!(fixture.record(request_id)?, Some(first));

    fixture.worker.dispatch(
        request_id,
        "original-owner",
        &"f".repeat(64),
        fixture.grant.witness_digest(),
        &CancellationToken::new(),
        &deadline()?,
    )?;
    assert_eq!(
        fixture
            .record(request_id)?
            .ok_or("missing dispatched owner")?
            .state,
        NativeReservationState::Dispatching
    );
    // This is a journal-owner settlement control, not a model execution result.
    let observed = fixture.worker.settle(
        request_id,
        "original-owner",
        "model",
        LocalExecutionStatus::Failed,
        None,
        None,
        true,
    )?;
    assert_eq!(observed.status, LocalExecutionStatus::Failed);
    assert!(observed.terminal_observed);
    let terminal = fixture
        .record(request_id)?
        .ok_or("missing terminal owner")?;
    assert_eq!(terminal.state, NativeReservationState::Released);
    let journal = std::fs::read(fixture._directory.path().join("control.log"))?;
    assert_eq!(
        fixture.worker.reserve(request_id, "model", payload)?,
        terminal
    );
    assert_eq!(
        std::fs::read(fixture._directory.path().join("control.log"))?,
        journal
    );
    assert_eq!(fixture.driver.0.counts(), [0, 0, 0, 0]);
    Ok(())
}
