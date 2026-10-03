use super::*;
#[test]
fn unprotected_generator_config_is_rejected_before_role_or_key_use() {
    let path = std::env::temp_dir().join(format!("parameter-g-unprotected-{}", std::process::id()));
    std::fs::write(&path, b"{\"schema\":\"caller claimed G\"}").expect("public fixture");
    assert!(run_fixed_parameter_generator_v3(&path).is_err());
    assert_eq!(
        std::fs::read(&path).expect("unchanged"),
        b"{\"schema\":\"caller claimed G\"}"
    );
    std::fs::remove_file(path).expect("cleanup");
}

#[test]
fn complete_parameter_role_pins_have_bounded_distinct_evidence_ids() {
    let round = Digest32::of_bytes(b"actual sealed round");
    let payload = Digest32::of_bytes(b"whole original signed payload");
    let generator = parameter_role_evidence_id(LearningEvidenceRoleV1::Generator, round, payload)
        .expect("complete pins fit the original StableId bound");
    assert_eq!(generator.as_str().len(), "parameter-g.".len() + 64);
    assert_eq!(
        generator,
        parameter_role_evidence_id(LearningEvidenceRoleV1::Generator, round, payload)
            .expect("same exact operation")
    );
    for (role, other_round, other_payload) in [
        (LearningEvidenceRoleV1::Observer, round, payload),
        (
            LearningEvidenceRoleV1::Generator,
            Digest32::of_bytes(b"another round"),
            payload,
        ),
        (
            LearningEvidenceRoleV1::Generator,
            round,
            Digest32::of_bytes(b"another whole payload"),
        ),
    ] {
        let other = parameter_role_evidence_id(role, other_round, other_payload).expect("bounded");
        assert_eq!(other.as_str().len(), 76);
        assert_ne!(generator, other);
    }
    assert!(parameter_role_evidence_id(LearningEvidenceRoleV1::Evaluator, round, payload).is_err());
}
