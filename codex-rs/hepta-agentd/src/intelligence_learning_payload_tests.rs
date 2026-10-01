use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn operation_ids_are_kind_separated_and_stable() {
    let run = id("run.learning");
    let snapshot = digest("snapshot");
    let decision = digest("decision");
    let physical = digest("physical");
    let first =
        decision_operation_id(&run, "episode.one", snapshot, decision).expect("decision operation");
    let second =
        decision_operation_id(&run, "episode.one", snapshot, decision).expect("decision operation");
    let outcome = outcome_operation_id(&run, "outcome.one", physical).expect("outcome operation");
    assert_eq!(first, second);
    assert_ne!(first, outcome);
}

#[test]
fn evidence_payload_rejects_role_substitution() {
    let value = EvidencePayloadV1 {
        evidence_id: "evidence.one".to_string(),
        principal_id: "principal.one".to_string(),
        role: "generator".to_string(),
        trust_digest: digest("trust").to_string(),
        scope_digest: digest("scope").to_string(),
        objective_digest: digest("objective").to_string(),
        authority_epoch: 1,
        issued_at: 1,
        expires_at: 2,
        payload_digest: digest("payload").to_string(),
        signature: vec![0; 64],
    };
    assert!(value.to_typed(LearningEvidenceRoleV1::Generator).is_ok());
    assert!(value.to_typed(LearningEvidenceRoleV1::Observer).is_err());
}

fn recovery_test_evidence() -> SignedLearningEvidenceV1 {
    SignedLearningEvidenceV1 {
        evidence_id: id("evidence.recovery"),
        principal_id: id("principal.generator"),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: digest("recovery-trust"),
        scope_digest: digest("recovery-scope"),
        objective_digest: digest("recovery-objective"),
        authority_epoch: 7,
        issued_at: 100,
        expires_at: 200,
        payload_digest: digest("recovery-payload"),
        signature: [9; 64],
    }
}

fn recovery_test_binding(evidence: &SignedLearningEvidenceV1) -> VerifiedEvidenceBindingPayloadV1 {
    VerifiedEvidenceBindingPayloadV1 {
        principal_id: evidence.principal_id.to_string(),
        controller_id: "controller.generator".to_string(),
        credential_chain_digest: digest("credential-chain").to_string(),
        signing_key_digest: digest("signing-key").to_string(),
        scope_digest: evidence.scope_digest.to_string(),
        authority_epoch: evidence.authority_epoch,
        authentication_digest: learning_evidence_digest_v1(evidence).to_string(),
    }
}

fn recovery_test_principal() -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id("principal.generator"),
        credential_chain_digest: digest("credential-chain"),
        signing_key_digest: digest("signing-key"),
        scope_digest: digest("recovery-scope"),
        authority_epoch: 7,
        authenticated_at: 100,
        expires_at: 200,
    }
}

fn recovery_test_decision_payload() -> DecisionPayloadV1 {
    let evidence = recovery_test_evidence();
    let binding = recovery_test_binding(&evidence);
    let candidate = id("candidate.one");
    let candidates = vec![candidate.clone()];
    DecisionPayloadV1 {
        expected_ledger_predecessor: digest("ledger-predecessor").to_string(),
        record_id: "run.recovery".to_string(),
        episode_id: "episode.recovery".to_string(),
        run_snapshot_digest: digest("run-snapshot").to_string(),
        objective_digest: evidence.objective_digest.to_string(),
        policy_digest: digest("policy").to_string(),
        candidate_ids: vec![candidate.to_string()],
        selected_candidate_id: candidate.to_string(),
        selected_propensity_raw: ProbabilityQ32::ONE.raw(),
        completeness: CompletenessPayloadV1 {
            set_id: "candidate-set.recovery".to_string(),
            state_digest: digest("candidate-state").to_string(),
            generator_id: evidence.principal_id.to_string(),
            generator_code_digest: digest("generator-code").to_string(),
            grammar_digest: digest("candidate-grammar").to_string(),
            hard_filter_digest: digest("hard-filter").to_string(),
            truncation_digest: digest("truncation").to_string(),
            candidates_digest: codex_hepta_learning_ledger::candidate_ids_digest_v2(&candidates)
                .to_string(),
            candidate_count: 1,
            omitted_count_bound: 0,
            canonical_order_digest: codex_hepta_learning_ledger::candidate_order_digest_v2(
                &candidates,
            )
            .to_string(),
            complete_for_generator: true,
        },
        support_digest: digest("support").to_string(),
        decision_digest: digest("decision").to_string(),
        evidence: EvidencePayloadV1::from_typed(&evidence),
        evidence_binding: binding,
        now: 150,
    }
}

#[test]
fn persisted_evidence_binding_rejects_signed_identity_substitution() {
    let evidence = recovery_test_evidence();
    let binding = recovery_test_binding(&evidence);
    binding.require_evidence(&evidence).expect("exact evidence");
    let mut changed = evidence.clone();
    changed.signature[0] ^= 1;
    assert!(binding.require_evidence(&changed).is_err());
    let mut changed = evidence.clone();
    changed.principal_id = id("principal.substituted");
    assert!(binding.require_evidence(&changed).is_err());
    let mut changed = evidence.clone();
    changed.scope_digest = digest("other-scope");
    assert!(binding.require_evidence(&changed).is_err());
    let mut changed = evidence;
    changed.authority_epoch += 1;
    assert!(binding.require_evidence(&changed).is_err());
}

#[test]
fn persisted_principal_binding_rejects_key_and_credential_substitution() {
    let evidence = recovery_test_evidence();
    let binding = recovery_test_binding(&evidence);
    let principal = recovery_test_principal();
    binding
        .require_principal(&principal)
        .expect("exact principal");
    let mut changed = principal.clone();
    changed.credential_chain_digest = digest("other-chain");
    assert!(binding.require_principal(&changed).is_err());
    let mut changed = principal.clone();
    changed.signing_key_digest = digest("other-key");
    assert!(binding.require_principal(&changed).is_err());
    let mut changed = principal.clone();
    changed.scope_digest = digest("other-scope");
    assert!(binding.require_principal(&changed).is_err());
    let mut changed = principal;
    changed.authority_epoch += 1;
    assert!(binding.require_principal(&changed).is_err());
}

#[test]
fn exact_destination_observation_binds_controller_identity() {
    let payload = recovery_test_decision_payload();
    let exact = expected_persisted_event(&LearningPayloadV1::Decision(payload.clone()))
        .expect("exact persisted event");
    let mut substituted = payload;
    substituted.evidence_binding.controller_id = "controller.substituted".to_string();
    let substituted = expected_persisted_event(&LearningPayloadV1::Decision(substituted))
        .expect("substituted persisted event");
    assert_ne!(exact, substituted);
}

#[test]
fn v2_payload_round_trip_preserves_event_time_predecessor_and_authentication() {
    let payload = PersistedLearningEnvelopeV1 {
        schema_version: 2,
        owner_generation: 7,
        payload: LearningPayloadV1::Decision(recovery_test_decision_payload()),
    };
    let bytes = serde_json::to_vec(&payload).expect("encode");
    let restored: PersistedLearningEnvelopeV1 = serde_json::from_slice(&bytes).expect("decode");
    assert_eq!(
        bytes,
        serde_json::to_vec(&restored).expect("canonical re-encode")
    );
    assert_eq!(
        payload.payload.operation_id().expect("operation"),
        restored.payload.operation_id().expect("operation")
    );
    assert_eq!(
        expected_persisted_event(&payload.payload).expect("event"),
        expected_persisted_event(&restored.payload).expect("event")
    );
    let LearningPayloadV1::Decision(restored) = restored.payload else {
        panic!("decision fixture");
    };
    assert_eq!(restored.now, 150);
    assert_eq!(
        restored.expected_ledger_predecessor,
        digest("ledger-predecessor").to_string()
    );
}

#[test]
fn historical_event_reconstruction_does_not_require_a_current_write_grant() {
    let payload = recovery_test_decision_payload();
    let first = expected_persisted_event(&LearningPayloadV1::Decision(payload.clone()))
        .expect("historical event");
    let mut later_metadata = payload;
    later_metadata.now = 1_000;
    let second =
        expected_persisted_event(&LearningPayloadV1::Decision(later_metadata)).expect("same event");
    assert_eq!(first, second);
    // Reconstruction is not application. Only the live destination comparison
    // may acknowledge it; apply_decision separately checks the current clock.
}

// Witness-covered observation is exercised against the real owner backend by
// hepta-learning-ledger::production::tests::
// exact_destination_recovery_requires_event_predecessor_and_witness.
// Do not duplicate the ledger's chain/witness algorithm in the composition host.
