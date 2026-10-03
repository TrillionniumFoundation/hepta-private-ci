use super::*;

#[test]
fn final_time_rechecks_each_opaque_v2_participant_without_poisoning_or_anchor_effect() {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    for participant in 0..4 {
        let mut request = fixture.request();
        let (evidence, signer) = match participant {
            0 => (&mut request.generator_attestation, 0),
            1 => (&mut request.admission_attestation, 1),
            2 => (&mut request.evaluations[0].evidence.generator_plan, 0),
            _ => (&mut request.evaluations[0].evidence.evaluator_bundle, 2),
        };
        evidence.expires_at = 50;
        evidence.signature = fixture.keys[signer]
            .sign(&evidence.signing_bytes())
            .to_bytes();
        let mut writer = writer();
        let mut anchor = AnchorCommitter {
            accept: true,
            ..AnchorCommitter::default()
        };
        assert!(matches!(
            propose_authenticated_parameter_plasticity_with_final_time_v1(
                request,
                &fixture.verifier,
                &mut writer,
                &mut anchor,
                50,
                &mut || Ok(51),
            ),
            Err(ParameterPlasticityProductErrorV1::Evaluation(
                SignedEvaluationError::Evidence(SignedEvidenceError::ValidityWindow)
            ))
        ));
        assert_eq!(writer.record_count().expect("record count"), 0);
        assert_eq!(writer.current_anchor().expect("anchor"), None);
        assert_eq!(writer.state(), PlasticityWriterStateV1::Healthy);
        assert_eq!(
            (anchor.scope, anchor.fence, anchor.anchor),
            (None, None, None)
        );
    }
}

#[test]
fn no_change_final_time_requires_original_independent_evaluator() {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut request = fixture.no_change_request();
    let evidence = request.no_change_attestation.as_mut().expect("evaluator");
    evidence.expires_at = 50;
    evidence.signature = fixture.keys[2].sign(&evidence.signing_bytes()).to_bytes();
    let mut writer = writer();
    let mut anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    assert!(matches!(
        propose_authenticated_parameter_plasticity_with_final_time_v1(
            request,
            &fixture.verifier,
            &mut writer,
            &mut anchor,
            50,
            &mut || Ok(51),
        ),
        Err(ParameterPlasticityProductErrorV1::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::ValidityWindow)
        ))
    ));
    assert_eq!(writer.record_count().expect("record count"), 0);
    assert_eq!(writer.state(), PlasticityWriterStateV1::Healthy);
    assert_eq!(anchor.anchor, None);
}

#[test]
fn expired_identical_observation_preserves_original_v2_frame_and_external_anchor() {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut writer = writer();
    let mut anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let original = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor,
        50,
    )
    .expect("original commit");
    let original_anchor = anchor.anchor;
    let mut request = fixture.request();
    request.expected_registry_predecessor = original.committed_registry_anchor.frame_digest;
    assert!(matches!(
        propose_authenticated_parameter_plasticity_with_final_time_v1(
            request,
            &fixture.verifier,
            &mut writer,
            &mut anchor,
            50,
            &mut || Ok(91),
        ),
        Err(ParameterPlasticityProductErrorV1::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::ValidityWindow)
        ))
    ));
    assert_eq!(writer.record_count().expect("record count"), 1);
    assert_eq!(
        writer.current_anchor().expect("anchor"),
        Some(original.committed_registry_anchor)
    );
    assert_eq!(anchor.anchor, original_anchor);
    assert_eq!(writer.state(), PlasticityWriterStateV1::Healthy);
}
