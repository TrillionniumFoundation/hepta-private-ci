use super::tests::stored_pre_send;
use super::tests::stored_terminal;
use super::*;

fn state() -> StoredExactDeliveryState {
    let mut state = StoredExactDeliveryState {
        schema: EXACT_DELIVERY_SCHEMA,
        ..Default::default()
    };
    state.pre_sends.insert(
        "attempt-a".into(),
        stored_pre_send("thread-a", "turn-a", "attempt-a"),
    );
    state
}

fn uncertain() -> StoredTerminal {
    let mut observation = stored_terminal("attempt-a");
    observation.disposition = "Indeterminate".into();
    observation.provider_receipt_digest = [21; 32];
    observation
}

#[test]
fn exclusive_expiry_and_clock_rollback_reject_send() {
    assert_eq!(
        check_send_time(10, 20, 20),
        Err(ExactContextDeliveryError::Expired)
    );
    assert_eq!(
        check_send_time(10, 9, 20),
        Err(ExactContextDeliveryError::Clock)
    );
    assert_eq!(check_send_time(10, 19, 20), Ok(()));
    assert_eq!(
        check_send_time(0, 1, 20),
        Err(ExactContextDeliveryError::Clock)
    );
}

#[test]
fn indeterminate_stays_unresolved_across_real_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, _) = ExactDeliveryStore::open(directory.path()).expect("open");
    let mut state = state();
    assert!(apply_observation(&mut state, uncertain()).expect("observe"));
    assert!(state.has_unresolved_for_turn("thread-a", "turn-a"));
    assert!(state.terminals.is_empty());
    store.persist(&state).expect("persist");
    drop(store);
    let (_, recovered) = ExactDeliveryStore::open(directory.path()).expect("reopen");
    assert!(recovered.has_unresolved_attempt("attempt-a"));
    assert_eq!(recovered.observations.len(), 1);
}

#[test]
fn final_observation_retains_indeterminate_history() {
    let mut state = state();
    apply_observation(&mut state, uncertain()).expect("unknown");
    let mut terminal = stored_terminal("attempt-a");
    terminal.observed_unix_ms += 1;
    assert!(apply_observation(&mut state, terminal).expect("resolved"));
    assert!(!state.has_unresolved_attempt("attempt-a"));
    assert_eq!(state.observations.len(), 1);
    validate_stored_state(&state).expect("complete history");
}

#[test]
fn retry_timestamp_is_not_a_new_semantic_terminal() {
    let mut state = state();
    let terminal = stored_terminal("attempt-a");
    apply_observation(&mut state, terminal.clone()).expect("first");
    let mut repeated = terminal.clone();
    repeated.observed_unix_ms += 100;
    assert!(!apply_observation(&mut state, repeated).expect("idempotent"));
    assert_eq!(
        state.terminals["attempt-a"].observed_unix_ms,
        terminal.observed_unix_ms
    );
}

#[test]
fn conflicting_final_and_final_to_unknown_regression_are_rejected() {
    let mut state = state();
    apply_observation(&mut state, stored_terminal("attempt-a")).expect("first");
    let mut conflicting = stored_terminal("attempt-a");
    conflicting.provider_receipt_digest = [99; 32];
    assert!(apply_observation(&mut state, conflicting).is_err());
    assert!(apply_observation(&mut state, uncertain()).is_err());
}

#[test]
fn pre_send_proof_substitution_and_time_rollback_are_rejected() {
    let mut state = state();
    let mut substituted = stored_terminal("attempt-a");
    substituted.final_request_proof_digest = [55; 32];
    assert!(apply_observation(&mut state, substituted).is_err());
    let mut unknown = uncertain();
    unknown.observed_unix_ms = 100;
    apply_observation(&mut state, unknown).expect("unknown");
    assert_eq!(
        apply_observation(&mut state, stored_terminal("attempt-a")),
        Err(ExactContextDeliveryError::Clock)
    );
}

#[test]
fn legacy_indeterminate_is_migrated_without_becoming_final() {
    let mut state = state();
    state.schema = 1;
    state.terminals.insert("attempt-a".into(), uncertain());
    migrate_state(&mut state).expect("migration");
    assert_eq!(state.schema, EXACT_DELIVERY_SCHEMA);
    assert!(state.has_unresolved_attempt("attempt-a"));
    assert_eq!(state.observations.len(), 1);
    validate_stored_state(&state).expect("valid migration");
}

#[test]
fn failed_directory_sync_fences_the_same_writer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, _) = ExactDeliveryStore::open(directory.path()).expect("open");
    let state = state();
    let result = store.persist_with_sync(&state, |_| {
        Err(ExactContextDeliveryError::IndeterminateDurability)
    });
    assert_eq!(
        result,
        Err(ExactContextDeliveryError::IndeterminateDurability)
    );
    assert_eq!(
        store.persist(&state),
        Err(ExactContextDeliveryError::ReopenRequired)
    );
    drop(store);
    let (_, recovered) =
        ExactDeliveryStore::open(directory.path()).expect("reopen committed bytes");
    assert!(recovered.has_unresolved_attempt("attempt-a"));
}

#[test]
fn unknown_disposition_and_missing_proof_fields_are_not_accepted_on_reopen() {
    let mut state = state();
    state
        .pre_sends
        .get_mut("attempt-a")
        .expect("claim")
        .tokenizer_identity_digest = [0; 32];
    assert!(validate_stored_state(&state).is_err());
    let mut state = self::state();
    let mut terminal = stored_terminal("attempt-a");
    terminal.disposition = "ProbablyDelivered".into();
    state.terminals.insert("attempt-a".into(), terminal);
    assert!(validate_stored_state(&state).is_err());
}

#[test]
fn domain_errors_redact_attached_raw_content_in_display_and_debug() {
    let error = ExactContextDeliveryError::Domain("RAW-CONTEXT-DO-NOT-LOG".into());
    for rendered in [
        format!("{error}"),
        format!("{error:?}"),
        format!("{error:#?}"),
    ] {
        assert!(!rendered.contains("RAW-CONTEXT"));
        assert_eq!(rendered, "context_delivery_v2_domain_rejected");
    }
}

#[test]
fn framing_rejects_metadata_wrong_roles_and_concatenated_content() {
    let policy = ResponsesJsonFramingPolicy::new(
        "provider",
        "model",
        Digest32::of_bytes(b"config"),
        Digest32::of_bytes(b"endpoint"),
    )
    .expect("policy");
    let context = r#"{"schema":"hepta.context-bundle.v2","items":[]}"#;
    let valid = serde_json::json!({"model":"model", "input":[{"role":"developer","content":[{"type":"input_text","text":context}]}]});
    assert!(
        policy
            .verify_final_request(
                &serde_json::to_vec(&valid).expect("json"),
                context.as_bytes()
            )
            .is_ok()
    );
    let metadata = serde_json::json!({"model":"model", "input":[], "metadata":{"context":context}});
    assert!(
        policy
            .verify_final_request(
                &serde_json::to_vec(&metadata).expect("json"),
                context.as_bytes()
            )
            .is_err()
    );
    for role in ["user", "system", "assistant", "tool"] {
        let request = serde_json::json!({"model":"model", "input":[{"role":role,"content":[{"type":"input_text","text":context}]}]});
        assert!(
            policy
                .verify_final_request(
                    &serde_json::to_vec(&request).expect("json"),
                    context.as_bytes()
                )
                .is_err()
        );
    }
    let joined = serde_json::json!({"model":"model", "input":[{"role":"developer","content":[{"type":"input_text","text":format!("{context} extra instruction")}]}]});
    assert!(
        policy
            .verify_final_request(
                &serde_json::to_vec(&joined).expect("json"),
                context.as_bytes()
            )
            .is_err()
    );
}

#[test]
fn tokenizer_artifact_mutation_is_rejected() {
    let directory = tempfile::tempdir().expect("tempdir");
    let binary = directory.path().join("binary");
    let vocabulary = directory.path().join("vocabulary");
    std::fs::write(&binary, b"original binary").expect("binary");
    std::fs::write(&vocabulary, b"original vocabulary").expect("vocabulary");
    let identity = FinalRequestTokenizerIdentityV2::new(
        Digest32::of_bytes(b"provider"),
        Digest32::of_bytes(b"model"),
        Digest32::of_bytes(b"declared"),
        hash_bounded_file(&binary).expect("hash"),
        Digest32::of_bytes(b"version"),
        hash_bounded_file(&vocabulary).expect("hash"),
        Digest32::of_bytes(b"normalization"),
    )
    .expect("identity");
    let config = TokenizerRuntimeConfig {
        binary: binary.clone(),
        vocabulary: vocabulary.clone(),
        provider_id: "provider".into(),
        model: "model".into(),
        version: "version".into(),
        normalization: "normalization".into(),
        timeout: Duration::from_secs(1),
        identity,
    };
    config.verify_artifacts().expect("initial identity");
    std::fs::write(&vocabulary, b"substitution").expect("mutate");
    assert_eq!(
        config.verify_artifacts(),
        Err(ExactContextDeliveryError::TokenizerIdentity)
    );
}

#[test]
fn product_owner_fails_closed_before_tokenizer_when_external_security_is_missing() {
    let directory = tempfile::tempdir().expect("directory");
    let registry_path = directory.path().join("registry");
    let delivery_path = directory.path().join("delivery");
    let registry = DurablePromptRegistry::open_state_dir(&registry_path, 64).expect("registry");
    let security = Arc::new(ContextSecurityRuntimeV3::new());
    let owner = AgentdExactContextDeliveryOwner::open_product(
        &delivery_path,
        Arc::new(Mutex::new(registry)),
        security,
    )
    .expect("product owner");

    assert_eq!(
        owner.require_external_security(),
        Err(ExactContextDeliveryError::SecurityCapabilitiesUnavailable)
    );
}
