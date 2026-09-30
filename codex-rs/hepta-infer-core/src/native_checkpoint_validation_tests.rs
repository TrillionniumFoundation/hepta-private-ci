use super::*;

struct CheckpointFixture {
    directory: PathBuf,
    journal: PathBuf,
}

impl Drop for CheckpointFixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.directory).expect("cleanup checkpoint fixture");
    }
}

fn held_checkpoint() -> CheckpointFixture {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let directory = std::env::temp_dir().join(format!(
        "hepta-checkpoint-validation-{}-{nonce}", std::process::id()
    ));
    fs::create_dir_all(&directory).unwrap();
    let journal = directory.join("owner.journal");
    let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 8).unwrap();
    control.reserve_native(NativeRequest {
        request_id: "r1".to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 4,
        model: "actual-model".to_string(),
        payload_digest: "a".repeat(64),
    }, /*maximum_in_flight*/ 1).unwrap();
    let binding: NativeExecutionBinding = serde_json::from_value(serde_json::json!({
        "authority_epoch": 9,
        "bundle_digest": "a".repeat(64),
        "manifest_digest": "b".repeat(64),
        "quota_lease_digest": "c".repeat(64),
        "resource_lease_digest": "d".repeat(64),
        "output_policy_digest": "e".repeat(64),
        "execution_binding_digest": "f".repeat(64),
        "provider_id": "provider",
        "model_id": "actual-model",
        "model_revision": "revision-1",
        "model_digest": "1".repeat(64),
        "tokenizer_digest": "2".repeat(64),
        "template_digest": "3".repeat(64),
        "runtime_digest": "4".repeat(64),
        "adapter_digest": "5".repeat(64),
        "worker_id": "worker-1",
        "worker_generation": 4,
        "maximum_input_tokens": 128,
        "maximum_output_tokens": 128,
        "maximum_cost_microunits": 100,
        "valid_until_unix_ms": 10000
    })).unwrap();
    control.commit_native("r1", Event::BindExecution {
        request_id: "r1".to_string(),
        binding,
    }).unwrap();
    let dispatch: NativeDispatch = serde_json::from_value(serde_json::json!({
        "thread_id": "thread-1",
        "model_provider": "provider",
        "context_digest": "b".repeat(64)
    })).unwrap();
    control.dispatch_native("r1", dispatch).unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    control.settle_native("r1", NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "actual-model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: None,
    }).unwrap();
    control.compact_native_journal().unwrap();
    drop(control);
    CheckpointFixture { directory, journal }
}

fn rewrite_checkpoint(fixture: &CheckpointFixture, mutate: impl FnOnce(&mut NativeRunRecord)) {
    let journal = fs::read_to_string(&fixture.journal).unwrap();
    let reference: Event = serde_json::from_str(
        journal.lines().last().unwrap().strip_prefix(JOURNAL_PREFIX).unwrap()
    ).unwrap();
    let Event::CheckpointReference {
        generation,
        checkpoint_path,
        archive_segment_digest,
        archive_chain_digest,
        ..
    } = reference else {
        panic!("owner compaction must write a checkpoint reference");
    };
    let mut checkpoint: NativeCheckpoint =
        serde_json::from_slice(&fs::read(&checkpoint_path).unwrap()).unwrap();
    mutate(checkpoint.records.get_mut("r1").unwrap());
    let bytes = serde_json::to_vec(&checkpoint).unwrap();
    let digest = sha256_hex(b"hepta.inference-control.checkpoint.v1\0", &bytes);
    let path = Path::new(&checkpoint_path).parent().unwrap().join(format!("{digest}.json"));
    write_content_addressed(&path, &bytes).unwrap();
    let reference = Event::CheckpointReference {
        generation,
        checkpoint_path: path.to_str().unwrap().to_string(),
        checkpoint_digest: digest,
        archive_segment_digest,
        archive_chain_digest,
    };
    fs::write(&fixture.journal, format!(
        "{JOURNAL_PREFIX}{}\n", serde_json::to_string(&reference).unwrap()
    )).unwrap();
}

#[test]
fn valid_checkpoint_reopens_and_retains_unknown_execution_capacity() {
    let fixture = held_checkpoint();
    let mut reopened = DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("r1").unwrap().state, NativeReservationState::Indeterminate);
    let mut second = reopened.native_record("r1").unwrap().request.clone();
    second.request_id = "r2".to_string();
    assert_eq!(reopened.reserve_native(second, /*maximum_in_flight*/ 1), Err(Error::CapacityExceeded));
    drop(reopened);
}

#[test]
fn checkpoint_cannot_release_unknown_execution_without_terminal_evidence() {
    let fixture = held_checkpoint();
    rewrite_checkpoint(&fixture, |record| record.state = NativeReservationState::Released);
    let before = fs::read(&fixture.journal).unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8),
        Err(Error::CorruptJournal("native checkpoint state evidence"))
    ));
    assert_eq!(fs::read(&fixture.journal).unwrap(), before);
}

#[test]
fn checkpoint_revalidates_observation_assignment_identity() {
    let fixture = held_checkpoint();
    rewrite_checkpoint(&fixture, |record| {
        record.observation.as_mut().unwrap().thread_id = "other-thread".to_string();
    });
    assert!(matches!(
        DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8),
        Err(Error::AssignmentMismatch)
    ));
}

#[test]
fn checkpoint_revalidates_signed_audit_shape_and_terminal_sequence() {
    let fixture = held_checkpoint();
    rewrite_checkpoint(&fixture, |record| {
        record.state = NativeReservationState::Released;
        let output = record.observation.as_mut().unwrap();
        output.terminal_observed = true;
        output.status = NativeRunStatus::Completed;
        output.boundary_status = NativeBoundaryStatus::Succeeded;
        output.output = format!("hepta-reconciled-output-v1:{}", "6".repeat(64));
        output.codex_terminal_correlation_digest = Some("7".repeat(64));
        record.reconciliation = Some(NativeReconciliationAudit {
            receipt_digest: "7".repeat(64),
            authenticated_key_id: "provider-key".to_string(),
            terminal_sequence: 0,
            usage_microunits: Some(5),
            output_digest: Some("6".repeat(64)),
            encrypted_output_reference: None,
        });
    });
    assert!(matches!(
        DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8),
        Err(Error::InvalidIdentity("native reconciliation terminal sequence"))
    ));
}

#[test]
fn dispatched_request_survives_reopen_compaction_and_second_reopen() {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let directory = std::env::temp_dir().join(format!(
        "hepta-dispatched-checkpoint-{}-{nonce}", std::process::id()
    ));
    fs::create_dir_all(&directory).unwrap();
    let fixture = CheckpointFixture { journal: directory.join("owner.journal"), directory };
    let request = NativeRequest {
        request_id: "r1".to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 4,
        model: "actual-model".to_string(),
        payload_digest: "a".repeat(64),
    };
    let dispatch: NativeDispatch = serde_json::from_value(serde_json::json!({
        "thread_id": "thread-1",
        "model_provider": "provider",
        "context_digest": "b".repeat(64)
    })).unwrap();
    let mut control = DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8).unwrap();
    control.reserve_native(request.clone(), /*maximum_in_flight*/ 1).unwrap();
    let expected = control.dispatch_native("r1", dispatch.clone()).unwrap();
    assert_eq!(expected.state, NativeReservationState::Dispatching);
    assert_eq!(expected.observation, None);
    drop(control);
    let mut recovered = DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8).unwrap();
    assert_eq!(recovered.native_record("r1"), Some(&expected));
    assert_eq!(recovered.dispatch_native("r1", dispatch), Err(Error::InvalidTransition));
    recovered.compact_native_journal().unwrap();
    drop(recovered);
    let mut reopened = DurableInferenceControl::open(&fixture.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&expected));
    let mut second = request;
    second.request_id = "r2".to_string();
    assert_eq!(reopened.reserve_native(second, /*maximum_in_flight*/ 1), Err(Error::CapacityExceeded));
    drop(reopened);
}
