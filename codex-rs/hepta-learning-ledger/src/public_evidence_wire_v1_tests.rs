use super::*;
use crate::ReviewEvidenceWireV1;
use pretty_assertions::assert_eq;

#[test]
fn original_public_wire_retains_whole_signature_but_grants_no_admission() {
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("host trust");
    let original = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"full original dataset policy",
    );
    let wire = ReviewEvidenceWireV1::from_native(&original);
    let bytes = serde_json::to_vec(&wire).expect("original evidence bytes");
    let parsed: ReviewEvidenceWireV1 =
        serde_json::from_slice(&bytes).expect("ordinary readonly codec");
    assert_eq!(parsed.native().expect("whole original signature"), original);
    verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &parsed.native().expect("original"),
            b"full original dataset policy",
            50,
        )
        .expect("only original verifier admits");
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &original,
            b"changed policy",
            50
        ),
        Err(SignedEvidenceError::PayloadMismatch)
    );
    let mut forged = parsed;
    forged.signature_hex = "00".repeat(64);
    let forged = forged
        .native()
        .expect("untrusted parsing is not verification");
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &forged,
            b"full original dataset policy",
            50
        ),
        Err(SignedEvidenceError::InvalidSignature)
    );
}

#[test]
fn original_public_wire_preserves_selector_and_fixed_signature_bound() {
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("host trust");
    let mut original = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"facts",
    );
    original.role = LearningEvidenceRoleV1::Selector;
    let mut wire = ReviewEvidenceWireV1::from_native(&original);
    assert_eq!(wire.native().expect("original Selector transfer"), original);
    wire.signature_hex.push_str("00");
    assert!(wire.native().is_err());
    wire.signature_hex = "gg".repeat(64);
    assert!(wire.native().is_err());
    wire.signature_hex = "00".repeat(64);
    wire.role = "unknown".into();
    assert!(wire.native().is_err());
}
