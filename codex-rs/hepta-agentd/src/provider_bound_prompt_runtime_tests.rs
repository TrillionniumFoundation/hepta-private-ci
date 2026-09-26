use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid stable id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn stage(dispatch_id: &str, generation: u64, request: &[u8]) -> ProviderBoundPromptStageV2 {
    let mut value = ProviderBoundPromptStageV2 {
        dispatch_id: id(dispatch_id),
        generation,
        bundle_digest: digest(&format!("bundle:{generation}")),
        canonical_serialization_proof_digest: digest(&format!("serialization:{generation}")),
        canonical_payload_digest: digest(&format!("payload:{generation}")),
        attachment_digest: digest(&format!("attachment:{generation}")),
        snapshot_successor_digest: digest(&format!("successor:{generation}")),
        preparation_digest: digest(&format!("preparation:{generation}")),
        provider_request_digest: Digest32::of_bytes(request),
        provider_request_coverage_digest: digest(&format!("coverage:{generation}")),
        wire_semantic_digest: digest(&format!("wire:{generation}")),
        tokenizer_identity_digest: digest(&format!("tokenizer-identity:{generation}")),
        tokenizer_attestation_digest: digest(&format!("tokenizer-attestation:{generation}")),
        exact_token_count: u64::try_from(request.len()).unwrap_or(u64::MAX),
        exact_request_bytes: request.to_vec(),
        stage_digest: Digest32::ZERO,
    };
    value.stage_digest = value.compute_digest();
    value.validate().expect("fixture stage validates");
    value
}

#[test]
fn durable_claim_reopens_with_the_exact_same_request_bytes() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:reopen");
    let attempt_id = id("attempt:provider-bound:one");
    let exact_request = b"provider-final-request\0with-framing\ncontext";
    let stage = stage(dispatch_id.as_str(), 1, exact_request);
    let original_stage_digest = stage.stage_digest();
    let original_request_digest = stage.provider_request_digest();

    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        assert_eq!(
            runtime.stage(stage.clone()).expect("stage"),
            ProviderBoundStageDispositionV2::Inserted
        );
        let lease = runtime
            .claim_dispatch(&dispatch_id, 1, attempt_id.clone(), 100)
            .expect("claim dispatch");
        assert_eq!(
            lease.disposition(),
            ProviderBoundDispatchDispositionV2::Claimed
        );
        assert_eq!(lease.exact_request_bytes(), exact_request);
        assert_eq!(lease.provider_request_digest(), original_request_digest);
    }

    let reopened = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("reopen runtime");
    let snapshot = reopened
        .snapshot(&dispatch_id)
        .expect("snapshot")
        .expect("entry");
    assert_eq!(snapshot.stage_digest, original_stage_digest);
    assert_eq!(snapshot.dispatch_attempt_id, Some(attempt_id.clone()));
    let lease = reopened
        .claim_dispatch(&dispatch_id, 1, attempt_id, 999)
        .expect("idempotent claim");
    assert_eq!(
        lease.disposition(),
        ProviderBoundDispatchDispositionV2::ExistingClaim
    );
    assert_eq!(lease.exact_request_bytes(), exact_request);
}

#[test]
fn a_different_attempt_is_blocked_after_a_durable_claim() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:fence");
    let first_attempt = id("attempt:provider-bound:first");
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime
            .stage(stage(dispatch_id.as_str(), 7, b"request-seven"))
            .expect("stage");
        runtime
            .claim_dispatch(&dispatch_id, 7, first_attempt, 700)
            .expect("first claim");
    }

    let reopened = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("reopen runtime");
    assert_eq!(
        reopened.claim_dispatch(
            &dispatch_id,
            7,
            id("attempt:provider-bound:blind-retry"),
            701,
        ),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending)
    );
}

#[test]
fn stage_is_idempotent_but_same_generation_mutation_is_rejected() {
    let runtime = AgentdProviderBoundPromptRuntimeV2::new();
    let dispatch_id = id("dispatch:provider-bound:idempotent");
    let first = stage(dispatch_id.as_str(), 2, b"request-two");
    assert_eq!(
        runtime.stage(first.clone()).expect("insert"),
        ProviderBoundStageDispositionV2::Inserted
    );
    assert_eq!(
        runtime.stage(first).expect("repeat"),
        ProviderBoundStageDispositionV2::Unchanged
    );
    assert_eq!(
        runtime.stage(stage(dispatch_id.as_str(), 2, b"mutated-request")),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::StageConflict)
    );
    assert_eq!(
        runtime.stage(stage(dispatch_id.as_str(), 1, b"older-request")),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
    );
}

#[test]
fn indeterminate_terminal_blocks_generation_reuse_until_reconciled() {
    let runtime = AgentdProviderBoundPromptRuntimeV2::new();
    let dispatch_id = id("dispatch:provider-bound:reconcile");
    let attempt_id = id("attempt:provider-bound:reconcile");
    runtime
        .stage(stage(dispatch_id.as_str(), 3, b"request-three"))
        .expect("stage");
    runtime
        .claim_dispatch(&dispatch_id, 3, attempt_id.clone(), 300)
        .expect("claim");
    assert_eq!(
        runtime
            .record_terminal_for_test(
                &dispatch_id,
                3,
                &attempt_id,
                ContextDeliveryDispositionV2::Indeterminate,
                301,
                digest("receipt:indeterminate"),
            )
            .expect("record indeterminate"),
        ProviderBoundTerminalDispositionV2::Recorded
    );
    assert_eq!(
        runtime.stage(stage(dispatch_id.as_str(), 4, b"request-four")),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending)
    );
    assert_eq!(
        runtime
            .record_terminal_for_test(
                &dispatch_id,
                3,
                &attempt_id,
                ContextDeliveryDispositionV2::Delivered,
                302,
                digest("receipt:completed"),
            )
            .expect("reconcile terminal"),
        ProviderBoundTerminalDispositionV2::Reconciled
    );
    assert_eq!(
        runtime
            .stage(stage(dispatch_id.as_str(), 4, b"request-four"))
            .expect("advance generation"),
        ProviderBoundStageDispositionV2::ReplacedGeneration
    );
    let snapshot = runtime
        .snapshot(&dispatch_id)
        .expect("snapshot")
        .expect("entry");
    assert_eq!(snapshot.generation, 4);
    assert!(snapshot.dispatch_attempt_id.is_none());
    assert!(snapshot.terminal_disposition.is_none());
}

#[test]
fn terminal_write_is_idempotent_and_conflicting_terminal_is_rejected() {
    let runtime = AgentdProviderBoundPromptRuntimeV2::new();
    let dispatch_id = id("dispatch:provider-bound:terminal-idempotent");
    let attempt_id = id("attempt:provider-bound:terminal-idempotent");
    runtime
        .stage(stage(dispatch_id.as_str(), 1, b"terminal-request"))
        .expect("stage");
    runtime
        .claim_dispatch(&dispatch_id, 1, attempt_id.clone(), 10)
        .expect("claim");
    let receipt_digest = digest("terminal-receipt");
    assert_eq!(
        runtime
            .record_terminal_for_test(
                &dispatch_id,
                1,
                &attempt_id,
                ContextDeliveryDispositionV2::NotDispatched,
                11,
                receipt_digest,
            )
            .expect("terminal"),
        ProviderBoundTerminalDispositionV2::Recorded
    );
    assert_eq!(
        runtime
            .record_terminal_for_test(
                &dispatch_id,
                1,
                &attempt_id,
                ContextDeliveryDispositionV2::NotDispatched,
                11,
                receipt_digest,
            )
            .expect("repeat terminal"),
        ProviderBoundTerminalDispositionV2::Unchanged
    );
    assert_eq!(
        runtime.record_terminal_for_test(
            &dispatch_id,
            1,
            &attempt_id,
            ContextDeliveryDispositionV2::Rejected,
            12,
            digest("conflicting-terminal"),
        ),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalConflict)
    );
}

#[test]
fn stale_generation_cannot_claim_or_settle() {
    let runtime = AgentdProviderBoundPromptRuntimeV2::new();
    let dispatch_id = id("dispatch:provider-bound:stale");
    let attempt_id = id("attempt:provider-bound:stale");
    runtime
        .stage(stage(dispatch_id.as_str(), 9, b"generation-nine"))
        .expect("stage");
    assert_eq!(
        runtime.claim_dispatch(&dispatch_id, 8, attempt_id.clone(), 90),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
    );
    runtime
        .claim_dispatch(&dispatch_id, 9, attempt_id.clone(), 90)
        .expect("current generation claim");
    assert_eq!(
        runtime.record_terminal_for_test(
            &dispatch_id,
            8,
            &attempt_id,
            ContextDeliveryDispositionV2::Delivered,
            91,
            digest("stale-terminal"),
        ),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
    );
}

#[test]
fn corrupt_request_bytes_are_rejected_on_reopen() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:corrupt");
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime
            .stage(stage(dispatch_id.as_str(), 1, b"original-request"))
            .expect("stage");
    }

    let state_path = temporary.path().join(STATE_FILE);
    let mut value: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&state_path).expect("read state"),
    )
    .expect("decode state");
    value["entries"][0]["stage"]["exact_request_base64"] =
        serde_json::Value::String(STANDARD_NO_PAD.encode(b"tampered-request"));
    std::fs::write(
        &state_path,
        serde_json::to_vec(&value).expect("encode corruption"),
    )
    .expect("write corruption");

    assert!(matches!(
        AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path()),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch)
            | Err(AgentdProviderBoundPromptRuntimeErrorV2::StageDigestMismatch)
            | Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)
    ));
}

#[test]
fn a_second_process_owner_cannot_open_the_same_state_directory() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let first = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("first owner");
    assert!(matches!(
        AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path()),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::StateLocked)
    ));
    drop(first);
    AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("lock released");
}

#[test]
fn synced_next_file_is_recovered_when_canonical_state_is_missing() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:next-recovery");
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime
            .stage(stage(dispatch_id.as_str(), 1, b"recover-next"))
            .expect("stage");
    }
    let state_path = temporary.path().join(STATE_FILE);
    let next_path = temporary.path().join(NEXT_FILE);
    std::fs::rename(&state_path, &next_path).expect("simulate crash before rename");

    let recovered = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("recover next file");
    assert!(
        recovered
            .snapshot(&dispatch_id)
            .expect("snapshot")
            .is_some()
    );
    assert!(state_path.exists());
    assert!(!next_path.exists());
}
