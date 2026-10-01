use super::*;

fn write_historical_snapshot(
    control: &DurableInferenceControl,
    schema_version: u32,
    records: BTreeMap<String, NativeRunRecord>,
) {
    // The historical producer serializes a final cut from normal transitions
    // and commits all artifacts before load. No committed bytes are altered.
    let current = fs::read(&control.path).unwrap();
    let archive_segment_digest =
        sha256_hex(b"hepta.inference-control.archive-segment.v1\0", &current);
    let archive_chain_digest = sha256_hex(
        b"hepta.inference-control.archive-chain.v1\0",
        format!("genesis:{archive_segment_digest}").as_bytes(),
    );
    let archive_dir = sibling_directory(&control.path, "archive");
    let checkpoint_dir = sibling_directory(&control.path, "checkpoints");
    fs::create_dir_all(&archive_dir).unwrap();
    fs::create_dir_all(&checkpoint_dir).unwrap();
    set_owner_only_directory(&archive_dir).unwrap();
    set_owner_only_directory(&checkpoint_dir).unwrap();
    write_content_addressed(
        &archive_dir.join(format!("{archive_segment_digest}.journal")),
        &current,
    )
    .unwrap();
    sync_directory(&archive_dir).unwrap();
    let checkpoint = NativeCheckpoint {
        schema_version,
        generation: 1,
        maximum_in_flight: control.native.maximum_in_flight,
        records,
        archive_segment_digest: archive_segment_digest.clone(),
        archive_chain_digest: archive_chain_digest.clone(),
        created_at_unix_ms: NOW,
    };
    let bytes = serde_json::to_vec(&checkpoint).unwrap();
    let checkpoint_digest = sha256_hex(b"hepta.inference-control.checkpoint.v1\0", &bytes);
    let checkpoint_path = checkpoint_dir.join(format!("{checkpoint_digest}.json"));
    write_content_addressed(&checkpoint_path, &bytes).unwrap();
    sync_directory(&checkpoint_dir).unwrap();
    let reference = Event::CheckpointReference {
        generation: 1,
        checkpoint_path: checkpoint_path.to_str().unwrap().to_string(),
        checkpoint_digest,
        archive_segment_digest,
        archive_chain_digest,
    };
    let active = format!(
        "{JOURNAL_PREFIX}{}\n",
        serde_json::to_string(&reference).unwrap()
    );
    let temp = temporary_generation_path(&control.path, /*generation*/ 1, NOW);
    write_content_addressed(&temp, active.as_bytes()).unwrap();
    fs::rename(temp, &control.path).unwrap();
    sync_directory(control.path.parent().unwrap()).unwrap();
}

fn prepared_bound(label: &str) -> (TestPaths, DurableInferenceControl, AuthorityFixture) {
    let paths = TestPaths::new(label);
    let mut control = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    let fixture = authority_fixture("request-1");
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    (paths, control, fixture)
}

fn signed_ready_control(label: &str) -> (TestPaths, DurableInferenceControl, NativeRunRecord) {
    let (paths, mut control, fixture) = prepared_bound(label);
    let mut held = indeterminate_output("thread-1", "turn-1");
    held.owner_authority = NativeOwnerAuthority::ObservedReady;
    control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            held,
            /*protected_output*/ None,
        )
        .unwrap();
    let receipt = ReconciliationReceipt {
        schema_version: 1,
        issuer_id: "provider-reconciler".to_string(),
        authority_epoch: fixture.plan.authority_epoch(),
        request_id: "request-1".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: fixture.plan.execution_binding_digest().to_string(),
        dispatch_digest: native_dispatch_digest(
            control
                .native_record("request-1")
                .unwrap()
                .dispatch
                .as_ref()
                .unwrap(),
        )
        .unwrap(),
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        provider_id: "provider-1".to_string(),
        model_digest: fixture.plan.manifest().model_digest.clone(),
        terminal_sequence: 1,
        terminal_status: ReconciledTerminalStatus::Completed,
        output_digest: Some("b".repeat(64)),
        encrypted_output_reference: None,
        observed_output_tokens: Some(7),
        usage_microunits: Some(12),
        issued_at_unix_ms: NOW - 1,
        expires_at_unix_ms: NOW + 100,
    };
    let signed = SignedReconciliationReceipt {
        signature: signature(
            "reconciliation-key",
            "provider-reconciler",
            &fixture.reconciliation_key,
            &receipt.signing_bytes().unwrap(),
        ),
        receipt,
    };
    let verified =
        verify_reconciliation_receipt(NOW, &fixture.trust, &fixture.plan, &signed).unwrap();
    let released = control
        .reconcile_native("request-1", &fixture.plan, NOW, &verified)
        .unwrap();
    assert!(released.observation.as_ref().unwrap().succeeded());
    (paths, control, released)
}

#[test]
fn normal_schema_one_reconciliation_checkpoint_denies_unsupported_readiness() {
    let (paths, control, released) = signed_ready_control("checkpoint-v1-ready");
    write_historical_snapshot(
        &control,
        /*schema_version*/ 1,
        control.native.records.clone(),
    );
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    let restored = reopened.native_record("request-1").unwrap();
    let mut expected = released;
    expected.observation.as_mut().unwrap().owner_authority = NativeOwnerAuthority::Unverified;
    assert_eq!(restored, &expected);
    assert!(!restored.observation.as_ref().unwrap().succeeded());
    assert_eq!(restored.state, NativeReservationState::Released);
}

#[test]
fn current_schema_two_checkpoint_preserves_independently_observed_readiness() {
    let (paths, mut control, released) = signed_ready_control("checkpoint-v2-ready");
    let receipt = control.compact_native_journal().unwrap();
    let path = sibling_directory(&control.path, "checkpoints")
        .join(format!("{}.json", receipt.checkpoint_digest));
    let checkpoint: NativeCheckpoint = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(checkpoint.schema_version, 2);
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&released));
}

#[test]
fn normal_schema_one_pre_effect_abort_checkpoint_remains_released() {
    let paths = TestPaths::new("checkpoint-v1-abort");
    let empty = paths.journal.clone();
    let mut control = DurableInferenceControl::open(&empty, /*capacity*/ 8).unwrap();
    let request = NativeRequest {
        request_id: "not-sent".to_string(),
        principal_id: "principal-1".to_string(),
        worker_generation: 4,
        model: "model-1".to_string(),
        payload_digest: "a".repeat(64),
    };
    control
        .reserve_native(request, /*maximum_in_flight*/ 1)
        .unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("not-sent", dispatch("thread-1"))
        .unwrap();
    let released = control
        .abort_native_before_effect(token, "not sent".to_string())
        .unwrap();
    write_historical_snapshot(
        &control,
        /*schema_version*/ 1,
        control.native.records.clone(),
    );
    drop(control);
    let reopened = DurableInferenceControl::open(&empty, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("not-sent"), Some(&released));
}

#[test]
fn legacy_retirement_without_key_fingerprints_stays_held_in_both_checkpoint_versions() {
    for schema_version in [1, 2] {
        let (paths, mut control, fixture) = prepared_bound("checkpoint-legacy-retirement");
        control
            .settle_native_authorized(
                "request-1",
                &fixture.plan,
                NOW,
                indeterminate_output("thread-1", "turn-1"),
                /*protected_output*/ None,
            )
            .unwrap();
        let record = control.native_record("request-1").unwrap();
        let retirement = IndeterminateRetirement {
            schema_version: 1,
            authority_epoch: 3,
            request_id: "request-1".to_string(),
            principal_id: "principal-1".to_string(),
            execution_binding_digest: fixture.plan.execution_binding_digest().to_string(),
            dispatch_digest: native_dispatch_digest(record.dispatch.as_ref().unwrap()).unwrap(),
            record_revision: record.revision,
            reason_code: "provider_unrecoverable".to_string(),
            reason: "no independently recoverable provider terminal evidence".to_string(),
            issued_at_unix_ms: NOW - 1,
            expires_at_unix_ms: NOW + 100,
        };
        let message = retirement.signing_bytes().unwrap();
        let signed = SignedIndeterminateRetirement {
            retirement,
            approvals: vec![
                signature(
                    "operator-key-a",
                    "operator-a",
                    &fixture.operator_a,
                    &message,
                ),
                signature(
                    "operator-key-b",
                    "operator-b",
                    &fixture.operator_b,
                    &message,
                ),
            ],
        };
        let verified =
            verify_indeterminate_retirement(NOW, &fixture.trust, &fixture.plan, &signed).unwrap();
        let released = control
            .retire_native_indeterminate("request-1", &fixture.plan, NOW, &verified)
            .unwrap();
        assert_eq!(released.state, NativeReservationState::Released);
        // The old producer persisted IDs but had no fingerprint field.
        let mut historical = control.native.records.clone();
        historical
            .get_mut("request-1")
            .unwrap()
            .retirement
            .as_mut()
            .unwrap()
            .independent_operator_key_digests = None;
        write_historical_snapshot(&control, schema_version, historical.clone());
        drop(control);
        let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
        let restored = reopened.native_record("request-1").unwrap();
        historical.get_mut("request-1").unwrap().state = NativeReservationState::Indeterminate;
        assert_eq!(restored, historical.get("request-1").unwrap());
    }
}
