use super::tests::digest;
use super::tests::id;
use super::tests::profile;
use super::*;
use crate::*;
use codex_hepta_types::Generation;
fn admission() -> PlasticityAdmissionEvidenceV1 {
    PlasticityAdmissionEvidenceV1 {
        baseline_id: id("baseline"),
        objective_digest: digest(b"objective"),
        selected_artifact_digest: digest(b"artifact"),
        artifact_registry_binding: digest(b"binding"),
        artifact_registry_head_digest: digest(b"current"),
        qualification_evidence_head_digest: digest(b"ledger"),
        owner_evidence_set_digest: digest(b"seven"),
        window: profile().window,
        baseline_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        dataset_digest: digest(b"dataset"),
        update_rule_digest: digest(b"update"),
        modulator_digest: digest(b"modulator"),
        modulator_broadcast_digest: digest(b"broadcast"),
        eligibility_digest: digest(b"eligibility"),
        generator_digest: digest(b"generator"),
    }
}
#[test]
fn whole_profile_round_trips_every_original_field_and_original_candidate_set() {
    let p = profile();
    let bytes = encode_untrusted_parameter_generator_profile_v3(&p).expect("whole profile");
    let decoded = decode_untrusted_parameter_generator_profile_v3(&bytes).expect("whole decode");
    assert_eq!(decoded, p);
    assert_eq!(
        generate_parameter_candidates_v3(decoded),
        generate_parameter_candidates_v3(p.clone())
    );
    let mut inline = encode_parameter_generator_profile_body_v3(&p).expect("original inline");
    let n = inline.len();
    inline.extend_from_slice(b"next original field");
    let (same, consumed) =
        decode_parameter_generator_profile_body_prefix_v3(&inline).expect("prefix");
    assert_eq!(same, p);
    assert_eq!(consumed, n);
}
#[test]
fn complete_admission_transport_keeps_the_exact_original_observer_payload() {
    let a = admission();
    let bytes = encode_untrusted_plasticity_admission_v1(&a).expect("whole facts");
    let same = decode_untrusted_plasticity_admission_v1(&bytes).expect("facts");
    assert_eq!(same, a);
    let payload = plasticity_admission_signing_payload_v1(&a);
    assert!(payload.starts_with(b"hepta.intelligence.plasticity-admission.v1\0"));
    let mut changed = same;
    changed.eligibility_digest = digest(b"changed real eligibility");
    assert_ne!(plasticity_admission_signing_payload_v1(&changed), payload);
    let mut inline = encode_plasticity_admission_body_v1(&a).expect("original body");
    let n = inline.len();
    inline.push(19);
    let (same, consumed) = decode_plasticity_admission_body_prefix_v1(&inline).expect("prefix");
    assert_eq!(same, a);
    assert_eq!(consumed, n);
}
#[test]
fn partial_tampered_foreign_and_oversized_role_materials_fail_before_any_authority() {
    let bytes = encode_untrusted_parameter_generator_profile_v3(&profile()).expect("profile");
    for cut in 0..bytes.len() {
        assert!(decode_untrusted_parameter_generator_profile_v3(&bytes[..cut]).is_err());
    }
    let mut changed = bytes.clone();
    changed[18] ^= 1;
    assert!(decode_untrusted_parameter_generator_profile_v3(&changed).is_err());
    let a = encode_untrusted_plasticity_admission_v1(&admission()).expect("admission");
    assert!(decode_untrusted_parameter_generator_profile_v3(&a).is_err());
    assert!(decode_untrusted_plasticity_admission_v1(&bytes).is_err());
    let oversized = vec![0; MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 + 1];
    assert!(decode_untrusted_parameter_generator_profile_v3(&oversized).is_err());
    assert!(decode_untrusted_plasticity_admission_v1(&oversized).is_err());
}
#[test]
fn semantically_invalid_profile_and_missing_original_no_change_are_refused() {
    let mut p = profile();
    p.mutation_policy.policy_digest = digest(b"wrong policy");
    assert!(encode_untrusted_parameter_generator_profile_v3(&p).is_err());
    let mut generated = generate_parameter_candidates_v3(profile()).expect("generated");
    generated
        .candidates
        .retain(|c| c.kind != ParameterCandidateKindV2::NoChange);
    assert_eq!(
        no_change_disposition_signing_payload_v1(&generated, &admission()),
        Err(ParameterMaterialCodecErrorV1::MissingNoChange)
    );
}
