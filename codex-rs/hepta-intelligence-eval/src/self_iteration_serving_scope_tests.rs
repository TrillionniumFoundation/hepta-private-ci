//! The sole signed purpose retains full observed scope and ordinal, not fake G/O.
use super::*;
use crate::paired_supervised_test_support::SigningFixture;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use pretty_assertions::assert_eq;
fn facts() -> SelfIterationServingScopeIncompatibleFactsV1 {
    let d = Digest32::of_bytes(b"complete protected original owner fixture");
    SelfIterationServingScopeIncompatibleFactsV1 {
        round_identity_digest: d,
        round_payload_digest: d,
        canonical_policy_digest: d,
        execution_envelope_digest: d,
        enrolled_inputs_digest: d,
        serving_observation_digest: d,
        training_material_digest: d,
        training_registration_digest: d,
        registry_binding_digest: d,
        registry_head_digest: d,
        registry_acknowledgement_digest: d,
        serving_scope_digest: d,
        serving_objective_digest: Digest32::of_bytes(b"actual user Goal objective"),
        training_scope_digest: d,
        training_objective_digest: d,
        expected_training_scope_digest: d,
        expected_training_objective_digest: Digest32::of_bytes(
            b"original admitted training contract",
        ),
        configuration_digest: d,
        body_bundle_digest: d,
        neuron_generation: 2,
        goal_ordinal: Some(3),
        admitted_at_ms: 2,
        deadline_ms: 900,
        observed_at_ms: 10,
    }
}
#[test]
fn incompatible_training_contract_binds_full_actual_serving_observation() {
    let signing = SigningFixture::new(false);
    for ordinal in [None, Some(3)] {
        let mut f = facts();
        f.goal_ordinal = ordinal;
        assert_eq!(f.serving_scope_digest, f.training_scope_digest);
        let payload = self_iteration_serving_scope_signing_payload_v1(&f).expect("full purpose");
        let evidence = signing.sign(2, &payload, 10);
        let packet = encode_self_iteration_serving_scope_terminal_v1(&f, &evidence).expect("whole");
        assert_eq!(
            decode_self_iteration_serving_scope_terminal_v1(&packet).expect("decode"),
            (f.clone(), evidence.clone())
        );
        signing
            .verifier
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, 10)
            .expect("real fixture signature");
        assert!(crate::decode_self_iteration_preparation_terminal_v1(&packet).is_err());
        let mutations: [fn(&mut SelfIterationServingScopeIncompatibleFactsV1); 4] = [
            |f: &mut SelfIterationServingScopeIncompatibleFactsV1| {
                f.serving_observation_digest = Digest32::of_bytes(b"other actual response")
            },
            |f: &mut SelfIterationServingScopeIncompatibleFactsV1| {
                f.registry_acknowledgement_digest = Digest32::of_bytes(b"other ACK")
            },
            |f: &mut SelfIterationServingScopeIncompatibleFactsV1| f.goal_ordinal = Some(4),
            |f: &mut SelfIterationServingScopeIncompatibleFactsV1| {
                f.serving_scope_digest = Digest32::of_bytes(b"other subject")
            },
        ];
        for mutate in mutations {
            let mut changed = f.clone();
            mutate(&mut changed);
            let p =
                self_iteration_serving_scope_signing_payload_v1(&changed).expect("different facts");
            assert!(
                signing
                    .verifier
                    .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &p, 10)
                    .is_err()
            );
        }
        let mut partial = packet.clone();
        partial.pop();
        assert!(decode_self_iteration_serving_scope_terminal_v1(&partial).is_err());
        let mut tamper = packet.clone();
        tamper[30] ^= 1;
        assert!(decode_self_iteration_serving_scope_terminal_v1(&tamper).is_err());
        let mut tail = packet;
        tail.push(0);
        assert!(decode_self_iteration_serving_scope_terminal_v1(&tail).is_err());
    }
}
#[test]
fn matching_scope_missing_owner_pin_zero_ordinal_or_late_observation_has_no_terminal() {
    let mut f = facts();
    f.expected_training_scope_digest = f.training_scope_digest;
    f.expected_training_objective_digest = f.training_objective_digest;
    // An ordinary user Goal may differ while training remains compatible.
    assert_ne!(f.serving_objective_digest, f.training_objective_digest);
    assert!(self_iteration_serving_scope_signing_payload_v1(&f).is_err());
    let mut f = facts();
    f.serving_observation_digest = Digest32::ZERO;
    assert!(self_iteration_serving_scope_signing_payload_v1(&f).is_err());
    let mut f = facts();
    f.goal_ordinal = Some(0);
    assert!(self_iteration_serving_scope_signing_payload_v1(&f).is_err());
    let mut f = facts();
    f.observed_at_ms = f.deadline_ms;
    assert!(self_iteration_serving_scope_signing_payload_v1(&f).is_err());
}
