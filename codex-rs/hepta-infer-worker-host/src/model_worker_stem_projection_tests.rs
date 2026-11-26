use super::*;

const Q24: i64 = 1 << 24;

fn d(character: char) -> String {
    character.to_string().repeat(64)
}

fn fixture() -> LowRankStemProjectionV1 {
    LowRankStemProjectionV1 {
        encoder_digest: d('a'),
        preprocessor_digest: d('b'),
        runtime_digest: d('c'),
        normalizer_digest: d('e'),
        representation: "mean".to_string(),
        input_width: 3,
        output_width: 2,
        rank: 2,
        a_q24: vec![Q24, 0, 0, 0, Q24, 0],
        b_q24: vec![Q24, 0, 0, Q24],
        bias_q24: vec![0, Q24 / 8],
    }
}

fn binding() -> StemProjectionBindingV1 {
    StemProjectionBindingV1 {
        scope_digest: d('1'),
        generation: 5,
        revocation_frontier_digest: d('2'),
        encoder_digest: d('a'),
        preprocessor_digest: d('b'),
        runtime_digest: d('c'),
        source_input_digest: d('d'),
        source_feature_digest: "e2738fbff6a632280fd48ed1022a3ea63a924111c75bc65260766e31b4f41327"
            .to_string(),
    }
}

#[test]
fn projection_parity_matches_python_golden_v1() {
    let projection = fixture();
    assert_eq!(
        projection
            .digest()
            .expect("pinned Q24 projector")
            .to_string(),
        "451632b3946c1d3dd690eaf2007ad71ba00b50c49c8911854aa02be25a7838c3"
    );
    let input = [0.5_f32, -0.25_f32, 0.125_f32];
    assert_eq!(
        projection.project_float32(&input).expect("project"),
        vec![Q24 / 2, -Q24 / 8]
    );
    assert_eq!(
        stem_feature_f32_digest(&input, 3, "mean")
            .expect("source digest")
            .to_string(),
        binding().source_feature_digest
    );
    let result = project_bound_f32(&projection, &binding(), &input, 3)
        .expect("scope/revision/f32 projection");
    assert_eq!(result.values_q24, vec![Q24 / 2, -Q24 / 8]);
    assert_eq!(
        result.projected_input_digest.to_string(),
        "a61a79d9d616f28356a12dbcb1eaccbf37c7d51ae3fee807fc6d8d724150a40e"
    );
    assert!(!result.production_authorized);
}

#[test]
fn low_rank_projection_can_read_last_coordinate_beyond_512() {
    let mut projection = fixture();
    projection.input_width = 768;
    projection.rank = 1;
    projection.output_width = 256;
    projection.a_q24 = vec![0; 768];
    projection.a_q24[767] = Q24;
    projection.b_q24 = vec![0; 256];
    projection.b_q24[255] = Q24;
    projection.bias_q24 = vec![0; 256];
    let mut input = vec![0; 768];
    input[767] = Q24 / 4;
    let output = projection.project_q24(&input).expect("no truncation");
    assert_eq!(output.len(), 256);
    assert!(output[..255].iter().all(|&value| value == 0));
    assert_eq!(output[255], Q24 / 4);
}

#[test]
fn scope_generation_frontier_and_projection_revision_change_bound_identity() {
    let source = [0.5_f32, -0.25_f32, 0.125_f32];
    let base = project_bound_f32(&fixture(), &binding(), &source, 3)
        .expect("baseline")
        .projected_input_digest;
    let mut changed = binding();
    changed.scope_digest = d('9');
    assert_ne!(
        base,
        project_bound_f32(&fixture(), &changed, &source, 3)
            .expect("scope")
            .projected_input_digest
    );
    changed = binding();
    changed.generation += 1;
    assert_ne!(
        base,
        project_bound_f32(&fixture(), &changed, &source, 3)
            .expect("generation")
            .projected_input_digest
    );
    changed = binding();
    changed.revocation_frontier_digest = d('8');
    assert_ne!(
        base,
        project_bound_f32(&fixture(), &changed, &source, 3)
            .expect("frontier")
            .projected_input_digest
    );
    let mut projector = fixture();
    projector.bias_q24[1] += 1;
    assert_ne!(
        base,
        project_bound_f32(&projector, &binding(), &source, 3)
            .expect("different projector")
            .projected_input_digest
    );
}

#[test]
fn rejects_untrusted_input_digest_schema_and_unsafe_numeric() {
    let source = [0.5_f32, -0.25_f32, 0.125_f32];
    let mut changed = binding();
    changed.source_feature_digest = d('0');
    assert_eq!(
        project_bound_f32(&fixture(), &changed, &source, 3),
        Err(Error::FeatureContract)
    );
    changed = binding();
    changed.encoder_digest = d('f');
    assert_eq!(
        project_bound_f32(&fixture(), &changed, &source, 3),
        Err(Error::FeatureContract)
    );
    let mut invalid = fixture();
    invalid.a_q24.pop();
    assert_eq!(invalid.digest(), Err(Error::FeatureLimit));
    invalid = fixture();
    invalid.a_q24[0] = Q24 * 9;
    assert_eq!(invalid.digest(), Err(Error::FeatureLimit));
    assert_eq!(
        fixture().project_float32(&[f32::NAN, 0.0, 0.0]),
        Err(Error::FeatureLimit)
    );
    assert_eq!(fixture().project_q24(&[0, 0]), Err(Error::FeatureLimit));
}

#[test]
fn ties_even_and_positive_negative_overflow_fail_closed() {
    let q = Q24 as i128;
    assert_eq!(q48_round_ties_even(q / 2), Ok(0));
    assert_eq!(q48_round_ties_even(3 * q / 2), Ok(2));
    assert_eq!(q48_round_ties_even(-q / 2), Ok(0));
    assert_eq!(q48_round_ties_even(-3 * q / 2), Ok(-2));
    assert_eq!(
        q48_round_ties_even(9 * q * q),
        Err(Error::FeatureOutputMismatch)
    );
    assert_eq!(
        q48_round_ties_even(-9 * q * q),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn native_neuron_request_must_consume_exact_projected_digest_and_vector() {
    use super::super::NeuronFeatureRequest;
    use super::super::WorkerRequest;
    use super::super::canonical_neuron_feature_payload_digest;

    let features = [0.5_f32, -0.25_f32, 0.125_f32];
    let bound = project_bound_f32(&fixture(), &binding(), &features, 3).expect("project");
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "request.projected.1".to_string(),
            reservation_id: "reservation.projected.1".to_string(),
            model_digest: d('8'),
            payload_digest: d('0'),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: d('0'),
            reservation_model_digest: d('8'),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: binding().encoder_digest,
        head_digest: d('7'),
        weights_digest: d('6'),
        input_digest: bound.projected_input_digest.to_string(),
        feature_vector_q24: bound.values_q24.clone(),
        expected_output_width: 2,
    };
    let payload = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;
    assert_eq!(
        verify_neuron_projected_request(&binding(), &bound, &request, 5),
        Ok(())
    );
    assert_eq!(
        verify_neuron_projected_request(&binding(), &bound, &request, 6),
        Err(Error::FeatureContract)
    );
    request.feature_vector_q24[0] += 1;
    assert_eq!(
        verify_neuron_projected_request(&binding(), &bound, &request, 5),
        Err(Error::FeatureContract)
    );
}
