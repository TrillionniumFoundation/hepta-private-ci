use super::*;
use pretty_assertions::assert_eq;

#[test]
fn physical_projection_does_not_replace_original_full_pin_equality() {
    let original = NeuralCognitivePinV1 {
        payload_digest: Digest32::of_bytes(b"actual-parameter-bytes"),
        objective_digest: Digest32::of_bytes(b"original-evaluated-objective"),
        dataset_digest: Digest32::of_bytes(b"original-evaluated-dataset"),
        generation: Generation::new(3).unwrap(),
        family_digest: Digest32::of_bytes(b"original-family"),
        execution_profile_digest: Digest32::of_bytes(b"original-execution"),
    };
    let physical = SmolLmRuntimeIdentityV1::from(&original);
    let mut changed_admission = original.clone();
    changed_admission.objective_digest = Digest32::of_bytes(b"other-objective");
    changed_admission.dataset_digest = Digest32::of_bytes(b"other-dataset");
    assert_ne!(original, changed_admission);
    assert_eq!(physical, SmolLmRuntimeIdentityV1::from(&changed_admission));
    for changed in [
        NeuralCognitivePinV1 {
            payload_digest: Digest32::of_bytes(b"different-parameters"),
            ..original.clone()
        },
        NeuralCognitivePinV1 {
            generation: Generation::new(4).unwrap(),
            ..original.clone()
        },
        NeuralCognitivePinV1 {
            family_digest: Digest32::of_bytes(b"different-family"),
            ..original.clone()
        },
        NeuralCognitivePinV1 {
            execution_profile_digest: Digest32::of_bytes(b"different-execution"),
            ..original
        },
    ] {
        assert_ne!(physical, SmolLmRuntimeIdentityV1::from(&changed));
    }
    assert_eq!(
        original.compatibility_digest(),
        changed_admission.compatibility_digest()
    );
}
