use super::*;

fn batch() -> Batch {
    Batch {
        schema: "hepta.masked-calibration-reference-batch.v1".into(),
        batch_id: "calibration-fixture".into(),
        source_archive_digest: Digest32::of_bytes(b"archive").to_string(),
        source_pairs_digest: Digest32::of_bytes(b"pairs").to_string(),
        task_template_digest: Digest32::of_bytes(b"template").to_string(),
        task_sources: vec![TaskSource {
            claim_id: 1,
            cited_doc_ids: vec![10, 20],
            source_claim_file_digest: Digest32::of_bytes(b"claims").to_string(),
            source_claim_row_1based: 3,
        }],
        rows: vec![Row {
            row_id: "row-1".into(),
            claim_id: 1,
            doc_id: 10,
            source_record_digest: Digest32::of_bytes(b"raw-source-row").to_string(),
            prompt: "Classify this claim and cited abstract".into(),
            prompt_digest: Digest32::of_bytes(b"Classify this claim and cited abstract")
                .to_string(),
        }],
    }
}

#[test]
fn masked_batch_rejects_gold_fields_and_incomplete_dependencies()
-> Result<(), Box<dyn std::error::Error>> {
    let value = batch();
    validate_batch(&value)?;
    let json = serde_json::json!({
        "schema":value.schema,"batch_id":value.batch_id,
        "source_archive_digest":value.source_archive_digest,
        "source_pairs_digest":value.source_pairs_digest,
        "task_template_digest":value.task_template_digest,
        "task_sources":[],"rows":[],"gold":"SUPPORT"
    });
    assert!(serde_json::from_value::<Batch>(json).is_err());
    let mut value = batch();
    value.task_sources[0].cited_doc_ids = vec![20];
    assert!(validate_batch(&value).is_err());
    let mut value = batch();
    value.task_sources[0].cited_doc_ids = vec![10, 10];
    assert!(validate_batch(&value).is_err());
    let mut value = batch();
    value.rows.push(value.rows[0].clone());
    assert!(validate_batch(&value).is_err());
    let mut value = batch();
    value.rows[0].prompt.push_str("changed");
    assert!(validate_batch(&value).is_err());
    Ok(())
}

#[cfg(unix)]
fn fixture() -> Result<
    (tempfile::TempDir, CalibrationReferenceBatch, AgentdIdentity),
    Box<dyn std::error::Error>,
> {
    use codex_hepta_agent_components::contracts::AgentId;
    use codex_hepta_agent_components::fleet::AgentManifest;
    use codex_hepta_agent_components::fleet::FleetRegistry;
    use codex_hepta_agent_components::fleet::ResourceBudget;
    use codex_hepta_agent_components::fleet::WorkspaceBinding;
    use codex_hepta_agent_components::paths::HeptaFleetRoot;
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let identity = AgentdIdentity {
        agent_id,
        layout: registered.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
    };
    let receipt_directory = identity.home_root.join("calibration-receipts");
    std::fs::create_dir(&receipt_directory)?;
    std::fs::set_permissions(&receipt_directory, std::fs::Permissions::from_mode(0o700))?;
    let value = CalibrationReferenceBatch {
        config: CalibrationReferenceBatchConfigV1 {
            batch_path: root.join("unused-root-source"),
            batch_digest: Digest32::of_bytes(b"batch").to_string(),
            receipt_directory,
            maximum_rows_per_tick: 1,
        },
        batch: batch(),
        pin: Digest32::of_bytes(b"batch"),
        host_pin: Digest32::of_bytes(b"host"),
    };
    Ok((directory, value, identity))
}

#[cfg(unix)]
#[test]
fn durable_row_reopen_preserves_request_deadline_and_prior_generation()
-> Result<(), Box<dyn std::error::Error>> {
    let (_directory, value, mut identity) = fixture()?;
    let row = &value.batch.rows[0];
    let state = value.state(row, &identity, /*timeout_seconds*/ 30)?;
    write_private(&value.state_path(row, &identity), &state)?;
    let reopen = value.state(row, &identity, /*timeout_seconds*/ 90)?;
    assert_eq!(reopen.native_request_id, state.native_request_id);
    assert_eq!(reopen.original_deadline_ms, state.original_deadline_ms);
    identity.spawn_generation = 2;
    let replacement = value.state(row, &identity, /*timeout_seconds*/ 90)?;
    assert_eq!(replacement.worker_generation, 1);
    assert_eq!(replacement.native_request_id, state.native_request_id);
    assert_ne!(
        replacement.native_request_id,
        value.request_id(row, &identity.agent_id.to_string(), 2)
    );
    assert_eq!(
        value.status(&identity, /*timeout_seconds*/ 90)?["prior_generation_pending"],
        1
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn durable_row_tamper_cannot_claim_completion_or_hide_owner_reconfiguration()
-> Result<(), Box<dyn std::error::Error>> {
    let (_directory, mut value, identity) = fixture()?;
    let row = &value.batch.rows[0];
    let original = value.state(row, &identity, /*timeout_seconds*/ 30)?;
    let path = value.state_path(row, &identity);
    let mut tampered = original.clone();
    tampered.phase = "completed".into();
    tampered.original_execution_latency_us = Some(1);
    write_private(&path, &tampered)?;
    assert!(value.state(row, &identity, /*timeout_seconds*/ 30).is_err());
    write_private(&path, &original)?;
    value.host_pin = Digest32::of_bytes(b"replacement-host");
    assert!(
        value
            .state(&value.batch.rows[0], &identity, /*timeout_seconds*/ 30)
            .is_err()
    );
    assert_eq!(
        read_regular(&path, 8 * 1024 * 1024, SourceOwnership::PrivateOwner)?,
        serde_json::to_vec(&original)?
    );
    Ok(())
}

#[test]
fn unknown_and_cached_receipts_cannot_be_complete_cost_observations() {
    let mut value = NativeReferenceObservationV1 {
        native_request_id: "reference.fixture".into(),
        prompt_digest: Digest32::of_bytes(b"prompt").to_string(),
        original_deadline_ms: 10_000,
        replayed: true,
        fresh_execution_latency_us: None,
        attempt_elapsed_us: 1,
        attempt_started_at_ms: 1_000,
        attempt_finished_at_ms: 1_001,
        native_record: None,
        native_output: None,
        native_receipt_digest: None,
        diagnostic: Some("unknown original execution".into()),
        succeeded: false,
    };
    assert_eq!(
        phase(&value, /*original_latency*/ None),
        "pending_native_recovery"
    );
    // This checks the cost classification only; validate() separately requires
    // an authentic native terminal record before such a success can be used.
    value.succeeded = true;
    assert_eq!(
        phase(&value, /*original_latency*/ None),
        "observed_missing_cost"
    );
}
