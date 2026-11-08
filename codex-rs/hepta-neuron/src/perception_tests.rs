use super::*;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::perception_test_support::*;
use pretty_assertions::assert_eq;

#[test]
fn perception_cross_language_fixture_round_trips_and_binds_raw_evidence() {
    let observation = observation();
    checked(observation.validate(&binding(&observation), &[actor_source()]));
    let bytes = checked(observation.encode());
    assert_eq!(bytes.as_slice(), &PERCEPTION_FIXTURE[..PERCEPTION_FIXTURE.len() - 1]);
    assert_eq!(Digest32::of_bytes(&bytes).to_string(), "e08fffef99344a9ff1bd0c70f715dfdf450ecf179732f6cd12e33fc0fa9cb454");
    assert_eq!(observation.evidence.iter().map(|evidence| checked(evidence.digest()).to_string()).collect::<Vec<_>>(), vec![
        "196e6aa9f9741eeccb5d98a6be934d120ae250990dd43657782e936933ddd12a",
        "f63d795e3a39f912dd50f8840a175029dbed31dd36b8846cf7870ba4dbd77fbc",
    ]);
}

#[test]
fn perception_global_and_dense_retain_identical_raw_evidence_identity() {
    let dense = observation();
    let mut global = dense.clone();
    global.representation = PerceptionRepresentationV1::Global;
    global.latents = vec![PerceptionLatentV1 {
        evidence_digests: dense.evidence.iter().map(|evidence| checked(evidence.digest()).into_array()).collect(),
        values_q24: vec![1 << 24, 1 << 23],
        prediction_residual_q24: None,
        residual_predictor_digest: None,
    }];
    checked(global.validate(&binding(&global), &[actor_source()]));
    assert_eq!(global.evidence, dense.evidence);
    assert_eq!(checked(global.evidence_digest()), checked(dense.evidence_digest()));
    assert_ne!(checked(global.encode()), checked(dense.encode()));
}

#[test]
fn perception_rebinding_forged_bytes_does_not_make_them_actor_observed() {
    let mut observation = observation();
    let binding = binding(&observation);
    observation.evidence[0].raw_bytes[0] ^= 1;
    observation.latents[0].evidence_digests = vec![checked(observation.evidence[0].digest()).into_array()];
    checked(observation.encode());
    assert_eq!(observation.validate(&binding, &[actor_source()]), Err(PerceptionErrorV1::SourceMismatch));
}

#[test]
fn perception_latents_require_nonempty_bounded_vectors_and_exact_evidence_links() {
    let original = observation();
    for mutation in 0..7 {
        let mut observation = original.clone();
        match mutation {
            0 => observation.latents[0].values_q24.clear(),
            1 => observation.latents[0].values_q24[0] = Q24_LIMIT + 1,
            2 => observation.latents[0].evidence_digests[0] = d("wrong-evidence").into_array(),
            3 => observation.latents.reverse(),
            4 => observation.latents[0].prediction_residual_q24 = Some(0),
            5 => observation.latents[0].values_q24.resize(MAX_FEATURES + 1, 0),
            6 => { observation.latents.pop(); }
            _ => unreachable!(),
        }
        assert_eq!(observation.encode(), Err(PerceptionErrorV1::InvalidLatent));
    }
    let mut duplicated = original;
    duplicated.evidence[1].evidence_id = duplicated.evidence[0].evidence_id.clone();
    assert_eq!(duplicated.encode(), Err(PerceptionErrorV1::InvalidEvidence));
}

#[test]
fn perception_residuals_require_the_hosts_separately_pinned_predictor() {
    let mut observation = observation();
    let mut binding = binding(&observation);
    let predictor = d("residual-predictor");
    observation.latents[0].prediction_residual_q24 = Some(1);
    observation.latents[0].residual_predictor_digest = Some(predictor.into_array());
    assert_eq!(observation.validate(&binding, &[actor_source()]), Err(PerceptionErrorV1::BindingMismatch));
    binding.residual_predictor_digest = Some(predictor);
    checked(observation.validate(&binding, &[actor_source()]));
    observation.latents[0].prediction_residual_q24 = Some(-1);
    assert_eq!(observation.encode(), Err(PerceptionErrorV1::InvalidLatent));
}

#[test]
fn perception_wire_rejects_teacher_fields_duplicates_and_oversize_inputs() {
    let original = checked(observation().encode());
    let mut value = checked(serde_json::from_slice::<serde_json::Value>(&original));
    value["teacher_truth"] = serde_json::json!([1, 2]);
    assert_eq!(PerceptionObservationV1::decode(&checked(serde_json::to_vec(&value))), Err(PerceptionErrorV1::InvalidWire));
    let mut duplicate = b"{\"schema\":\"hepta.perception.observation.v1\",".to_vec();
    duplicate.extend_from_slice(&original[1..]);
    assert_eq!(PerceptionObservationV1::decode(&duplicate), Err(PerceptionErrorV1::InvalidWire));
    assert_eq!(PerceptionObservationV1::decode(&vec![b' '; MAX_OBSERVATION_BYTES + 1]), Err(PerceptionErrorV1::Capacity));
    let mut nested = checked(serde_json::from_slice::<serde_json::Value>(&original));
    nested["latents"][0]["teacher_features"] = serde_json::json!([1, 2]);
    assert_eq!(PerceptionObservationV1::decode(&checked(serde_json::to_vec(&nested))), Err(PerceptionErrorV1::InvalidWire));
}
