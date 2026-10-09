//! Fixture keys and virtual times are not production acceptance.
use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn receipt() -> SelfEvolutionSelectionReceiptV1 {
    SelfEvolutionSelectionReceiptV1 {
        selection_id: id("selection"),
        objective_digest: digest("objective"),
        predecessor_id: id("baseline"),
        predecessor_generation: generation(7),
        predecessor_artifact_digest: digest("baseline-bytes"),
        candidate_id: id("candidate"),
        candidate_generation: generation(8),
        candidate_artifact_digest: digest("candidate-bytes"),
        no_change_baseline_id: id("baseline"),
        no_change_baseline_digest: digest("baseline-bytes"),
        dataset_digest: digest("dataset"),
        ledger_head_digest: digest("ledger"),
        evaluation_evidence_digest: digest("evaluation"),
        evaluation_authentication_digest: digest("authentication"),
        evaluation_trust_digest: digest("trust"),
        frozen_plan_digest: digest("plan"),
        minimum_dataset_records: 10,
        minimum_future_window_micros: 1_000,
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn signing_payload_binds_predecessor_candidate_and_longitudinal_policy() {
    let first = selection_signing_payload_v1(&receipt()).expect("payload");
    let mut changed = receipt();
    changed.predecessor_artifact_digest = digest("other-baseline");
    changed.no_change_baseline_digest = changed.predecessor_artifact_digest;
    let second = selection_signing_payload_v1(&changed).expect("payload");
    assert_ne!(first, second);
}

fn principal(
    name: &str,
    scope: Digest32,
    key: &ed25519_dalek::SigningKey,
) -> codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
    codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn signed(
    verifier: &LearningEvidenceVerifierV1,
    key: &ed25519_dalek::SigningKey,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    use ed25519_dalek::Signer;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{name}-evidence")),
        principal_id: id(name),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("selection-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn selector_and_rollback_are_opaque_independent_admissions() {
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use ed25519_dalek::SigningKey;

    let scope = digest("selection-scope");
    let roles = [
        (
            "generator",
            "controller-generator",
            LearningEvidenceRoleV1::Generator,
            11_u8,
        ),
        (
            "evaluator",
            "controller-evaluator",
            LearningEvidenceRoleV1::Evaluator,
            22_u8,
        ),
        (
            "observer",
            "controller-observer",
            LearningEvidenceRoleV1::Observer,
            33_u8,
        ),
        (
            "selector",
            "controller-selector",
            LearningEvidenceRoleV1::Selector,
            44_u8,
        ),
    ];
    let keys = roles.map(|(_, _, _, seed)| SigningKey::from_bytes(&[seed; 32]));
    let signers = roles
        .iter()
        .zip(keys.iter())
        .map(
            |((name, controller, role, _), key)| TrustedLearningSignerV1 {
                principal: principal(name, scope, key),
                controller_id: id(controller),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![*role],
                revoked_at: None,
            },
        )
        .collect();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers,
    })
    .expect("trust");

    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &signed(
                &verifier,
                &keys[0],
                "generator",
                LearningEvidenceRoleV1::Generator,
                b"generator",
            ),
            b"generator",
            50,
        )
        .expect("generator");
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed(
                &verifier,
                &keys[1],
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                b"evaluator",
            ),
            b"evaluator",
            50,
        )
        .expect("evaluator");
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &signed(
                &verifier,
                &keys[2],
                "observer",
                LearningEvidenceRoleV1::Observer,
                b"observer",
            ),
            b"observer",
            50,
        )
        .expect("observer");

    let mut admitted_receipt = receipt();
    admitted_receipt.evaluation_trust_digest = verifier.trust_digest();
    let prepared = PreparedSelfEvolutionSelectionV1 {
        receipt: admitted_receipt,
        generator,
        evaluator,
        observer,
    };
    let selector_payload =
        selection_signing_payload_v1(prepared.receipt()).expect("selection payload");
    let selector_evidence = signed(
        &verifier,
        &keys[3],
        "selector",
        LearningEvidenceRoleV1::Selector,
        &selector_payload,
    );
    let selected =
        admit_self_evolution_selection_v1(prepared, &selector_evidence, &verifier, 50)
            .expect("independent selection");
    assert_eq!(selected.selector_id(), &id("selector"));
    assert!(selected.revalidate_current(&verifier, 50).is_ok());
    assert!(selected.revalidate_current(&verifier, 90).is_ok());
    assert!(selected.revalidate_current(&verifier, 49).is_err());
    assert!(selected.revalidate_current(&verifier, 91).is_err());

    let regression = digest("observed-regression");
    let rollback_payload =
        rollback_signing_payload_v1(&selected, regression).expect("rollback payload");
    let rollback_evidence = signed(
        &verifier,
        &keys[1],
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &rollback_payload,
    );
    let rollback = admit_self_evolution_rollback_v1(
        &selected,
        regression,
        &rollback_evidence,
        &verifier,
        50,
    )
    .expect("independent rollback");
    assert_eq!(rollback.rollback_generation(), generation(9));
    assert_eq!(rollback.evaluator_id(), &id("evaluator"));
}

#[test]
fn receipt_rejects_generation_rewind_and_baseline_drift() {
    let mut changed = receipt();
    changed.candidate_generation = generation(9);
    assert_eq!(
        selection_signing_payload_v1(&changed),
        Err(SelfEvolutionSelectionError::BindingMismatch)
    );
    let mut changed = receipt();
    changed.no_change_baseline_id = id("other-baseline");
    assert_eq!(
        selection_signing_payload_v1(&changed),
        Err(SelfEvolutionSelectionError::BindingMismatch)
    );
}
