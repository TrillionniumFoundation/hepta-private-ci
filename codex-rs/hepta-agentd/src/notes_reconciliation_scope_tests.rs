//! Two real attached targets and original queued/unknown/pre-boundary rows.
//! The signing keys/application here are explicit fixtures, not Root proof.
use super::*;
use codex_hepta_memory::ProductionQueuedReceipt;
use pretty_assertions::assert_eq;

async fn prepare_device(
    host: &AgentdProductionWriterHost,
    owner: &AgentId,
    name: &str,
    sequence: u64,
) -> Result<ProductionQueuedReceipt, Box<dyn Error>> {
    let request = Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new([1; 16], [2; 16], sequence)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: HOS2_CPU_PERIOD_NS,
        cap_ns: 1_001,
    };
    let operation = OperationIntentV1::new(
        StableId::new(name)?,
        StableId::new(owner.as_str())?,
        StableId::new(HOS2_DESTINATION_V1)?,
        Digest32::of_bytes(request.to_json()?.as_bytes()),
        request.scope_digest(),
        Generation::new(1)?,
        /*expected_predecessor*/ None,
    )?;
    Ok(host
        .writer()
        .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, request.to_json()?)
        .await?)
}

#[tokio::test]
async fn finite_notes_reconciler_excludes_device_grants_dispatch_and_observation()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory,
        config,
        host,
        final_use,
        issuer,
        primary_device,
        ..
    } = notes_host_fixture().await?;
    let owner = config.identity().agent_id.clone();
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let application = Arc::new(Application {
        target: target.clone(),
        effects: AtomicUsize::new(0),
        observations: AtomicUsize::new(0),
        lose_reply: AtomicBool::new(true),
        receipt: Mutex::new(None),
    });
    // Both consumers share the canonical signer, while retaining separate
    // original FinalUse directories and nonce/frontier state.
    let notes_final_use_path = directory.path().join("notes-scope-final-use");
    fs::create_dir(&notes_final_use_path)?;
    fs::set_permissions(&notes_final_use_path, fs::Permissions::from_mode(0o700))?;
    let notes_final_use = FinalUseAuthority::open_state_dir(
        &notes_final_use_path,
        "hos2-host-external-fixture".into(),
        issuer.key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 19,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let host = Arc::new(
        host.attach_target(
            final_use,
            Arc::new(ProductionHos2Target::new(primary_device.clone())),
            issuer.clone(),
        )?
        .attach_additional_target(
            notes_final_use,
            Arc::new(ProductionNotesTarget::new(
                target.clone(),
                application.clone(),
            )?),
        )?,
    );
    assert_eq!(host.destination_count(), 2);
    let rejected = prepare_device(&host, &owner, "device:scope:rejected", /*sequence*/ 1).await?;
    issuer.invalid_first_signature.store(true, Ordering::SeqCst);
    assert!(
        host.dispatch_to_with_grant_provider(HOS2_DESTINATION_V1, rejected.clone())
            .await
            .is_err()
    );
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    // Prove the non-Notes row is actually eligible for the original all-target
    // renewal path, rather than testing an inert queued row alone.
    let deadline = Instant::now() + Duration::from_secs(10);
    while host
        .writer()
        .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
        .await?
        .is_empty()
    {
        assert!(
            Instant::now() < deadline,
            "pre-boundary proof did not become eligible"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let queued = prepare_device(&host, &owner, "device:scope:queued", /*sequence*/ 2).await?;
    let unknown = prepare_device(&host, &owner, "device:scope:unknown", /*sequence*/ 3).await?;
    host.writer()
        .mark_indeterminate(&unknown.occurrence_key, "fixture lost device entry")
        .await?;
    let payload = serde_json::to_string(&json!({
        "schema_version":1,"action":"replace_note","operation_id":"notes.scope.lost-ack",
        "destination_id":target.destination_id(),"target":target,"expected_revision":0,"text":"Notes scope fixture"
    }))?;
    let operation = notes_operation_intent(
        &target,
        &payload,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    let notes = host
        .writer()
        .prepare_operation(operation, NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    let outcome = host
        .dispatch_to_with_grant_provider(&target.destination_id(), notes.clone())
        .await?;
    assert_eq!(outcome.state, LocalOutcomeState::Indeterminate);
    let issuer_before = issuer.requests.load(Ordering::SeqCst);
    let anchor = host.writer().recovery_anchor().await?;
    assert!(
        host.reauthorize_pending_for_destination("not-attached", /*limit*/ 8)
            .await
            .is_err()
    );
    assert!(
        host.reconcile_for_destination("not-attached", /*limit*/ 8)
            .await
            .is_err()
    );
    assert_eq!(host.writer().recovery_anchor().await?, anchor);
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(crate::runtime::run_notes_operation_reconciler(
        host.clone(),
        AgentdNotesObjectiveConfig {
            profile_digest: Digest32::of_bytes(b"scope.fixture"),
            target,
        },
        Duration::from_millis(10),
        cancellation.clone(),
    ));
    let result: Result<(), Box<dyn Error>> = async {
        let deadline = Instant::now() + Duration::from_secs(10);
        while host.writer().status(&notes.occurrence_key).await? != LocalOutcomeState::Committed {
            if Instant::now() >= deadline {
                return Err("finite Notes readback did not complete".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Ok(())
    }
    .await;
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(5), worker).await???;
    result?;
    assert_eq!(issuer.requests.load(Ordering::SeqCst), issuer_before);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    assert_eq!(primary_device.queries.load(Ordering::SeqCst), 0);
    assert_eq!(application.effects.load(Ordering::SeqCst), 1);
    assert!(application.observations.load(Ordering::SeqCst) > 0);
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Queued
    );
    assert_eq!(
        host.writer().status(&unknown.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        host.writer()
            .awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8)
            .await?
            .len(),
        1
    );
    // The unchanged Full owner path can still renew that original proof and
    // observe its own unknown work; the finite profile left it untouched.
    assert_eq!(host.reauthorize_pending(/*limit*/ 8).await?, 1);
    host.reconcile(/*limit*/ 8).await?;
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 1);
    assert!(primary_device.queries.load(Ordering::SeqCst) > 0);
    assert_eq!(application.effects.load(Ordering::SeqCst), 1);
    Ok(())
}
