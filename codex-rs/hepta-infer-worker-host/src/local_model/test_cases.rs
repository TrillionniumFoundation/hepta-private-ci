#[test]
fn semantic_drift_and_live_revocation_fail_closed() {
    let (verifier, mut signed) = signed_grant();
    signed.claims.maximum_tokens += 1;
    assert!(matches!(
        verifier.verify(&signed, 100, "worker.1", 7),
        Err(Error::InvalidGrant("semantic digest"))
    ));

    let (verifier, signed) = signed_grant();
    let verified = verifier.verify(&signed, 100, "worker.1", 7).unwrap();
    verifier
        .update_revocations(3, 5, BTreeSet::from(["nonce.1".to_string()]))
        .unwrap();
    assert!(matches!(
        verified.validate_live(100, "worker.1", 7),
        Err(Error::InvalidGrant(_))
    ));
}

#[test]
fn aggregate_memory_and_generation_fence_are_enforced() {
    let resources = ResourceManager::new(7, 2_048, 2).unwrap();
    resources
        .reserve_model("model.1", 1_024, 2_048)
        .unwrap()
        .commit("handle.1".to_string(), 1_024)
        .unwrap();
    assert_eq!(
        resources.reserve_model("model.2", 1_025, 2_048).err(),
        Some(Error::ResourceCapacity)
    );
    resources.fence_generation().unwrap();
    assert_eq!(
        resources.reserve_model("model.2", 1, 2_048).err(),
        Some(Error::GenerationFenced)
    );
}

#[tokio::test]
async fn exact_duplicate_returns_zero_usage_without_second_run() {
    let directory = tempdir().unwrap();
    let mut control =
        DurableInferenceControl::open(directory.path().join("local.journal"), 32).unwrap();
    let driver = driver(TestDriver::terminal(), Some(TestDriver::terminal()), true);
    let worker = worker(&driver, ResourceManager::new(7, 8_192, 2).unwrap());
    let grant = verified_grant();
    worker.load_model(&grant, manifest()).await.unwrap();
    let operation = OperationId::parse("operation.1".to_string()).unwrap();
    let first = worker
        .run(
            &mut control,
            operation.clone(),
            "model.1",
            input(),
            64,
            9_000,
            &grant,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    let duplicate = worker
        .run(
            &mut control,
            operation,
            "model.1",
            input(),
            64,
            9_000,
            &grant,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(first, duplicate);
    assert_eq!(first.consumed_tokens, Some(0));
    assert_eq!(driver.run_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn reopened_unknown_dispatch_is_inspect_only() {
    let directory = tempdir().unwrap();
    let journal = directory.path().join("unknown.journal");
    let driver = driver(
        DriverRunEvidence {
            terminal_observed: false,
            status: None,
            output_digest: None,
            consumed_tokens: None,
            observed_model_bytes: 1_024,
            observed_kv_memory_bytes: 0,
            transient_memory_bytes: 0,
        },
        Some(TestDriver::terminal()),
        true,
    );
    let grant = verified_grant();
    {
        let mut control = DurableInferenceControl::open(&journal, 32).unwrap();
        let worker = worker(&driver, ResourceManager::new(7, 8_192, 2).unwrap());
        worker.load_model(&grant, manifest()).await.unwrap();
        let unknown = worker
            .run(
                &mut control,
                OperationId::parse("operation.2".to_string()).unwrap(),
                "model.1",
                input(),
                64,
                9_000,
                &grant,
                &CancellationToken::new(),
            )
            .await
            .unwrap();
        assert_eq!(unknown.status, LocalRunStatus::Indeterminate);
        assert_eq!(unknown.consumed_tokens, None);
    }
    let mut control = DurableInferenceControl::open(&journal, 32).unwrap();
    let worker = worker(&driver, ResourceManager::new(7, 8_192, 2).unwrap());
    worker.load_model(&grant, manifest()).await.unwrap();
    let reconciled = worker
        .run(
            &mut control,
            OperationId::parse("operation.2".to_string()).unwrap(),
            "model.1",
            input(),
            64,
            9_000,
            &grant,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(reconciled.status, LocalRunStatus::Succeeded);
    assert_eq!(driver.run_calls.load(Ordering::SeqCst), 1);
    assert_eq!(driver.inspect_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn unload_failure_retains_handle_and_marks_repair_required() {
    let driver = driver(TestDriver::terminal(), None, false);
    let resources = ResourceManager::new(7, 8_192, 2).unwrap();
    let worker = worker(&driver, resources.clone());
    let grant = verified_grant();
    worker.load_model(&grant, manifest()).await.unwrap();
    assert_eq!(
        worker.unload_model("model.1").await,
        Err(Error::RepairRequired)
    );
    let snapshot = resources.snapshot().unwrap();
    assert_eq!(snapshot.loaded_models, 1);
    assert_eq!(snapshot.repair_required_models, 1);
}
