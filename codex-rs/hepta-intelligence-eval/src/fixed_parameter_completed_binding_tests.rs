//! Public synthetic tuples test binding, not the physical completion reader.
use super::*;
use crate::fixed_parameter_no_change::tests::admission;
use crate::fixed_parameter_no_change::tests::profile;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;

#[test]
fn completed_request_binding_retains_whole_round_profile_admission_and_role_signatures() {
    let fixture = SigningFixture::new(false);
    let profile = profile();
    let admission = admission(&profile);
    let generated = generate_parameter_candidates_v3(profile.clone()).unwrap();
    let generator = fixture.sign(0, &parameter_generator_signing_payload_v3(&generated), 50);
    let observer = fixture.sign(1, &plasticity_admission_signing_payload_v1(&admission), 50);
    let round = ParameterEvaluationRoundBindingV1 {
        round_identity_digest: digest("actual.round"),
        round_payload_digest: digest("full.round"),
        canonical_policy_digest: digest("actual.policy"),
        execution_envelope_digest: digest("execution"),
        admitted_at_ms: 10,
        deadline_ms: 950,
    };
    let mut completed = CompletedParameterEvaluationsV1 {
        evaluations: vec![],
        dispositions: vec![],
        reports: vec![],
        binding: None,
    };
    assert!(
        completed
            .validate_parameter_binding_v1(&round, &profile, &admission, &generator, &observer)
            .is_err()
    );
    completed.binding = Some(CompletedParameterEvaluationBindingV1 {
        round: round.clone(),
        profile: profile.clone(),
        admission: admission.clone(),
        generator: generator.clone(),
        observer: observer.clone(),
    });
    completed
        .validate_parameter_binding_v1(&round, &profile, &admission, &generator, &observer)
        .unwrap();
    let mut other_round = round.clone();
    other_round.round_payload_digest = digest("other.round");
    assert!(
        completed
            .validate_parameter_binding_v1(
                &other_round,
                &profile,
                &admission,
                &generator,
                &observer
            )
            .is_err()
    );
    let mut other_profile = profile.clone();
    other_profile.signals[0].evidence_digest = digest("other.signal");
    assert!(
        completed
            .validate_parameter_binding_v1(
                &round,
                &other_profile,
                &admission,
                &generator,
                &observer
            )
            .is_err()
    );
    let mut other_admission = admission.clone();
    other_admission.artifact_registry_head_digest = digest("other.head");
    assert!(
        completed
            .validate_parameter_binding_v1(
                &round,
                &profile,
                &other_admission,
                &generator,
                &observer
            )
            .is_err()
    );
    let mut other_generator = generator.clone();
    other_generator.signature[19] ^= 1;
    assert!(
        completed
            .validate_parameter_binding_v1(
                &round,
                &profile,
                &admission,
                &other_generator,
                &observer
            )
            .is_err()
    );
    let mut other_observer = observer;
    other_observer.evidence_id = crate::paired_supervised_test_support::id("different.issuance");
    assert!(
        completed
            .validate_parameter_binding_v1(
                &round,
                &profile,
                &admission,
                &generator,
                &other_observer
            )
            .is_err()
    );
}
