use super::*;
use codex_hepta_types::Digest32;

fn model(contract:OutputContract)->FutureHead {
    let digest=Digest32::of_bytes(b"unit-test-only-not-production-trust").to_string();
    let pins:crate::runtime_profile::Pins=serde_json::from_value(serde_json::json!({
        "protocol":digest,"feature_profile":digest,"weights":digest,"calibration":digest,
        "verification":digest,"device":digest,"upstream_model":digest,"source_manifest":digest,
        "dataset":digest,"measured_ece_ppm":0,"measured_false_acceptance_ppm":0,
    })).unwrap();
    let (_,mut config)=crate::runtime_profile::configuration(&pins,digest.parse().unwrap()).unwrap();
    config.state_width=33;config.input_feature_dimension=510;
    let mut w1=vec![vec![0.0;478];64];w1[0][0]=0.2;
    let mut w2=vec![vec![0.0;64];33];w2[17][0]=0.3;w2[32][0]=1.0;
    FutureHead {weights:Weights {w1,b1:vec![0.0;64],w2,b2:vec![0.0;33],token_state:vec![vec![0.0;8];24]},
        calibration:Calibration {cuts:vec![0.2,0.8],probabilities:vec![0.8;8]},
        config,contract,measured_resident_heap_bytes:0}
}

fn request(model:&FutureHead,observed:i64)->NeuronModelRequestV1 {
    let mut features=vec![0;510];features[0]=Q/4;features[477]=Q;
    features[478..].fill(observed);
    NeuronModelRequestV1 {request_id:StableId::new("test.request").unwrap(),
        config_id:model.config.config_id.clone(),generation:model.config.generation,
        model_id:model.config.model_id.clone(),encoder_digest:model.config.encoder_digest,
        head_digest:model.config.head_digest,weights_digest:model.config.weights_digest,
        input_digest:canonical_feature_vector_digest_v1(&features),feature_vector_q24:features,
        expected_output_width:33}
}

fn maximum_error(output:&NeuronModelOutputV1)->u64 {
    output.drive_q24.iter().zip(&output.prediction_q24).map(|(a,b)|a.abs_diff(*b)).max().unwrap()
}

#[test]
fn later_observation_cannot_change_real_state_forecast() {
    let mut head=model(OutputContract::StateResidual);
    let left=request(&head,0);let right=request(&head,Q);
    assert_eq!(head.forecast(&left.feature_vector_q24).unwrap(),head.forecast(&right.feature_vector_q24).unwrap());
    let a=head.execute(&left).unwrap();let b=head.execute(&right).unwrap();
    assert_eq!(a.prediction_q24,b.prediction_q24);
    assert_ne!(a.drive_q24,b.drive_q24);
    assert_ne!(maximum_error(&a),maximum_error(&b));
}

#[test]
fn confidence_carrier_changes_observed_copy_but_not_forecast_probability() {
    let mut head=model(OutputContract::FutureCorrectness);
    let left=request(&head,0);let right=request(&head,Q);
    let forecast=head.forecast(&left.feature_vector_q24).unwrap();
    assert_eq!(forecast,head.forecast(&right.feature_vector_q24).unwrap());
    let a=head.execute(&left).unwrap();let b=head.execute(&right).unwrap();
    assert_eq!(a.prediction_q24[0],b.prediction_q24[0]);
    assert_eq!(a.prediction_q24[0],forecast[0]);
    assert_eq!(a.prediction_q24[1..],a.drive_q24[1..]);
    assert_eq!(b.prediction_q24[1..],b.drive_q24[1..]);
    assert_ne!(a.prediction_q24[1..],b.prediction_q24[1..]);
    assert_eq!(maximum_error(&a),maximum_error(&b));
}
