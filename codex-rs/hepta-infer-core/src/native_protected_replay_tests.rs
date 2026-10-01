//! Replay consumes protected metadata even after a signed final receipt replaces
//! the earlier partial-output marker.
use super::*;

#[test]
fn journal_replay_rejects_malformed_metadata_and_unbound_output_marker() {
    let paths = TestPaths::new("protected-replay");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    let expected = control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            terminal_output("thread-1", "turn-1", "private output"),
            /*protected_output*/ None,
        )
        .unwrap();
    drop(control);
    let original = fs::read_to_string(&paths.journal).unwrap();
    for mutation in 0..6 {
        let mut journal = String::new();
        for line in original.lines() {
            let mut event: Event =
                serde_json::from_str(line.strip_prefix(JOURNAL_PREFIX).unwrap()).unwrap();
            if let Event::Observe {
                output,
                protected_output,
                ..
            } = &mut event
            {
                let protected = protected_output.as_mut().unwrap();
                match mutation {
                    0 => protected.delete_after_unix_ms = 0,
                    1 => protected.output_digest = "invalid".to_string(),
                    2 => protected.encrypted_reference = Some("vault://unexpected".to_string()),
                    3 => {
                        protected.storage_mode = OutputStorageMode::ExternalEncrypted;
                        protected.ciphertext_digest = Some("c".repeat(64));
                        protected.encryption_key_id = Some("vault-key".to_string());
                        protected.encrypted_reference = None;
                    }
                    4 => output.output = format!("hepta-protected-output-v1:{}", "a".repeat(64)),
                    5 => {
                        output.output =
                            "raw plaintext cannot replace a protected marker".to_string()
                    }
                    _ => unreachable!(),
                }
                if mutation < 4 {
                    // The historical hash-only producer could encode malformed
                    // metadata. A matching old hash must not bypass validation.
                    output.output = format!(
                        "hepta-protected-output-v1:{}",
                        sha256_hex(
                            b"hepta.inference-control.protected-output.v1\0",
                            &serde_json::to_vec(protected).unwrap(),
                        )
                    );
                }
            }
            journal.push_str(JOURNAL_PREFIX);
            journal.push_str(&serde_json::to_string(&event).unwrap());
            journal.push('\n');
        }
        fs::write(&paths.journal, journal).unwrap();
        assert!(
            DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).is_err(),
            "malformed replay mutation {mutation}"
        );
    }
    fs::write(&paths.journal, original).unwrap();
    // Historical positive retention timestamps may have expired: replay checks
    // structure, rather than imposing a fresh persistence authorization.
    let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&expected));
}

#[test]
fn reconciled_checkpoint_revalidates_retained_partial_output_metadata() {
    let paths = TestPaths::new("reconciled-protected-checkpoint");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    let mut partial = indeterminate_output("thread-1", "turn-1");
    partial.output = "private partial output".to_string();
    let held = control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            partial,
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
        dispatch_digest: native_dispatch_digest(held.dispatch.as_ref().unwrap()).unwrap(),
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
    let expected = control
        .reconcile_native("request-1", &fixture.plan, NOW, &verified)
        .unwrap();
    let metadata = expected.protected_output.as_ref().unwrap();
    assert_eq!(Some(metadata), held.protected_output.as_ref());
    assert_ne!(
        metadata.journal_marker().unwrap(),
        expected.observation.as_ref().unwrap().output,
    );
    control.compact_native_journal().unwrap();
    drop(control);
    let original = fs::read_to_string(&paths.journal).unwrap();
    let original_reference: Event =
        serde_json::from_str(original.trim_end().strip_prefix(JOURNAL_PREFIX).unwrap()).unwrap();
    let Event::CheckpointReference {
        checkpoint_path, ..
    } = &original_reference
    else {
        panic!("actual compaction must write a checkpoint reference");
    };
    let original_checkpoint: NativeCheckpoint =
        serde_json::from_slice(&fs::read(checkpoint_path).unwrap()).unwrap();
    let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&expected));
    drop(reopened);

    for mutation in 0..3 {
        let mut checkpoint = original_checkpoint.clone();
        let protected = checkpoint
            .records
            .get_mut("request-1")
            .unwrap()
            .protected_output
            .as_mut()
            .unwrap();
        match mutation {
            0 => protected.delete_after_unix_ms = 0,
            1 => protected.output_digest = "invalid".to_string(),
            2 => {
                protected.storage_mode = OutputStorageMode::ExternalEncrypted;
                protected.ciphertext_digest = Some("c".repeat(64));
                protected.encryption_key_id = Some("vault-key".to_string());
                protected.encrypted_reference = None;
            }
            _ => unreachable!(),
        }
        let bytes = serde_json::to_vec(&checkpoint).unwrap();
        let digest = sha256_hex(b"hepta.inference-control.checkpoint.v1\0", &bytes);
        let path = Path::new(checkpoint_path)
            .parent()
            .unwrap()
            .join(format!("{digest}.json"));
        write_content_addressed(&path, &bytes).unwrap();
        let mut reference = original_reference.clone();
        let Event::CheckpointReference {
            checkpoint_path,
            checkpoint_digest,
            ..
        } = &mut reference
        else {
            unreachable!();
        };
        *checkpoint_path = path.to_str().unwrap().to_string();
        *checkpoint_digest = digest;
        fs::write(
            &paths.journal,
            format!(
                "{JOURNAL_PREFIX}{}\n",
                serde_json::to_string(&reference).unwrap()
            ),
        )
        .unwrap();
        assert!(matches!(
            DurableInferenceControl::open(&paths.journal, /*capacity*/ 8),
            Err(Error::InvalidIdentity("native protected output")),
        ));
    }
    fs::write(&paths.journal, original).unwrap();
    let reopened = DurableInferenceControl::open(&paths.journal, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&expected));
}
