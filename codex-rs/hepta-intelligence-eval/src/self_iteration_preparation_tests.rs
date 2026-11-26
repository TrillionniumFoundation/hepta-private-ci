//! Public deterministic fixtures qualify the sole codec and role-purpose binding.
//! These do not claim real raw measurements or deployed private E custody.
use super::*;
use crate::paired_supervised_test_support::SigningFixture;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;

fn facts() -> SelfIterationPreparationFactsV1 {
    let d = Digest32::of_bytes(b"complete original fixture facts");
    SelfIterationPreparationFactsV1 {
        disposition: SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        round_identity_digest: d,
        round_payload_digest: d,
        canonical_policy_digest: d,
        execution_envelope_digest: d,
        enrolled_inputs_digest: d,
        generated_digest: d,
        admission_digest: d,
        generator_evidence_digest: d,
        observer_evidence_digest: d,
        evaluation_publication_digest: d,
        admitted_at_ms: 2,
        deadline_ms: 900,
        observed_at_ms: 10,
    }
}
#[test]
fn whole_original_e_terminal_retains_every_disposition_field_and_signature() {
    let signing = SigningFixture::new(false);
    for disposition in [
        SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        SelfIterationPreparationDispositionV1::Ineligible,
        SelfIterationPreparationDispositionV1::InsufficientEvidence,
    ] {
        let mut facts = facts();
        facts.disposition = disposition;
        let payload =
            self_iteration_preparation_terminal_signing_payload_v1(&facts).expect("sole payload");
        let evidence = signing.sign(2, &payload, 10);
        let bytes = encode_self_iteration_preparation_terminal_v1(&facts, &evidence)
            .expect("whole E output");
        let decoded = decode_self_iteration_preparation_terminal_v1(&bytes).expect("whole decode");
        assert_eq!(decoded, (facts.clone(), evidence.clone()));
        assert!(
            signing
                .verifier
                .verify(LearningEvidenceRoleV1::Evaluator, &decoded.1, &payload, 10)
                .is_ok()
        );
        assert!(
            signing
                .verifier
                .verify(LearningEvidenceRoleV1::Generator, &decoded.1, &payload, 10)
                .is_err()
        );
        let mut changed = facts.clone();
        changed.round_identity_digest = Digest32::of_bytes(b"another round");
        assert!(
            signing
                .verifier
                .verify(
                    LearningEvidenceRoleV1::Evaluator,
                    &evidence,
                    &self_iteration_preparation_terminal_signing_payload_v1(&changed)
                        .expect("facts"),
                    10
                )
                .is_err()
        );
        let mut changed = facts;
        changed.evaluation_publication_digest = Digest32::of_bytes(b"another actual E publication");
        assert!(
            signing
                .verifier
                .verify(
                    LearningEvidenceRoleV1::Evaluator,
                    &evidence,
                    &self_iteration_preparation_terminal_signing_payload_v1(&changed)
                        .expect("facts"),
                    10
                )
                .is_err()
        );
    }
}
#[test]
fn partial_tampered_trailing_oversized_or_timeless_terminal_facts_are_rejected() {
    let signing = SigningFixture::new(false);
    let original = facts();
    let payload = self_iteration_preparation_terminal_signing_payload_v1(&original).expect("facts");
    let bytes =
        encode_self_iteration_preparation_terminal_v1(&original, &signing.sign(2, &payload, 10))
            .expect("packet");
    for length in [0, 1, 8, 16, bytes.len() - 1] {
        assert!(decode_self_iteration_preparation_terminal_v1(&bytes[..length]).is_err());
    }
    let mut changed = bytes.clone();
    changed[20] ^= 1;
    assert!(decode_self_iteration_preparation_terminal_v1(&changed).is_err());
    let mut trailing = bytes;
    trailing.push(0);
    assert!(decode_self_iteration_preparation_terminal_v1(&trailing).is_err());
    assert!(
        decode_self_iteration_preparation_terminal_v1(&vec![
            0;
            MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1
                + 1
        ])
        .is_err()
    );
    let mut changed = original.clone();
    changed.observed_at_ms = changed.deadline_ms;
    assert!(self_iteration_preparation_terminal_signing_payload_v1(&changed).is_err());
    let mut changed = original;
    changed.enrolled_inputs_digest = Digest32::ZERO;
    assert!(self_iteration_preparation_terminal_signing_payload_v1(&changed).is_err());
}
