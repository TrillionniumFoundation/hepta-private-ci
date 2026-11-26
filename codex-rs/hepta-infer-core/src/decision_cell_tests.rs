use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("stable id")
}

fn bundle() -> DecisionCellParameterBundleV1 {
    DecisionCellParameterBundleV1 {
        base_bundle_digest: digest("base"),
        organ_id: id("browser.organ"),
        organ_bundle_digest: digest("organ"),
        cell_slot_id: Some(id("route.cell")),
        cell_bundle_digest: Some(digest("cell")),
        action_head_digest: digest("action-head"),
        target_head_digest: digest("target-head"),
        parameter_head_digest: digest("parameter-head"),
        disposition_head_digest: digest("disposition-head"),
        postcondition_head_digest: digest("postcondition-head"),
        state_head_digest: digest("state-head"),
        calibration_artifact_digest: digest("calibration"),
        ood_artifact_digest: digest("ood"),
        effective_parameter_digest: digest("effective"),
    }
}

fn request() -> DecisionCellRequestV1 {
    let actions = vec![
        DecisionCellActionCandidateV1 {
            action_id: id("action.activate"),
            action_semantic_digest: digest("activate"),
            target_required: true,
        },
        DecisionCellActionCandidateV1 {
            action_id: id("action.stop"),
            action_semantic_digest: digest("stop"),
            target_required: false,
        },
    ];
    let targets = vec![
        DecisionCellTargetCandidateV1 {
            target_id: id("target.a"),
            target_generation: 7,
            target_semantic_digest: digest("target-a"),
        },
        DecisionCellTargetCandidateV1 {
            target_id: id("target.b"),
            target_generation: 7,
            target_semantic_digest: digest("target-b"),
        },
    ];
    let parameter_bundle_digest = bundle().semantic_digest().expect("bundle");
    DecisionCellRequestV1 {
        request_id: id("decision-1"),
        generation: Generation::new(7).expect("generation"),
        model_id: id("model-1"),
        model_manifest_digest: digest("manifest"),
        weights_digest: digest("weights"),
        objective_digest: digest("objective"),
        ndu_digest: digest("ndu"),
        body_digest: digest("body"),
        observation_frontier_digest: digest("observation"),
        legal_action_set_digest: decision_cell_action_set_digest_v1(&actions).expect("actions"),
        candidate_target_set_digest: decision_cell_target_set_digest_v1(&targets).expect("targets"),
        parameter_bundle_digest,
        previous_state_digest: Some(digest("state-before")),
        actions,
        targets,
        feature_vector_q24: vec![1, -2, 3],
        deadline_monotonic_micros: 99,
    }
}

fn runtime() -> DecisionCellRuntimeTupleV1 {
    DecisionCellRuntimeTupleV1 {
        model_id: id("model-1"),
        model_manifest_digest: digest("manifest"),
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        parameter_bundle: bundle(),
    }
}

fn observation() -> DecisionCellObservationV1 {
    DecisionCellObservationV1 {
        action_scores_q24: vec![5, 1],
        target_scores_q24: vec![2, 9],
        parameter_values_q24: vec![4, -4],
        disposition_scores_q24: [9, 1, 0, 0, 0, 0],
        expected_postcondition_digest: digest("postcondition"),
        confidence_ppm: 900_000,
        ood_ppm: 10_000,
        value_q24: 100,
        cost_q24: 20,
        state_successor_digest: digest("state-after"),
        observed_memory_bytes: 1000,
        transient_allocation_bytes: 200,
        queue_age_micros: 30,
        latency_micros: 40,
        status: DecisionCellTerminalStatusV1::Succeeded,
    }
}

#[test]
fn typed_heads_select_only_from_frozen_candidates() {
    let request = request();
    let receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation()).expect("receipt");
    assert_eq!(receipt.selected_action_id, Some(id("action.activate")));
    assert_eq!(receipt.selected_target_id, Some(id("target.b")));
    assert_eq!(receipt.selected_target_generation, Some(7));
    assert_eq!(
        receipt.disposition,
        Some(DecisionCellDispositionV1::Continue)
    );
    assert!(!receipt.authority.grants_any());
    verify_decision_cell_receipt_v1(&request, &receipt).expect("verify");
}

#[test]
fn candidate_order_and_set_substitution_fail_closed() {
    let mut reordered = request();
    reordered.actions.swap(0, 1);
    assert_eq!(
        decision_cell_request_digest_v1(&reordered),
        Err(DecisionCellContractError::InvalidCandidateOrder)
    );

    let mut substituted = request();
    substituted.actions[0].action_semantic_digest = digest("changed");
    assert_eq!(
        decision_cell_request_digest_v1(&substituted),
        Err(DecisionCellContractError::CandidateSetDigestMismatch)
    );
}

#[test]
fn base_organ_cell_and_head_drift_are_rejected() {
    let request = request();
    for changed in ["base", "organ", "cell", "head", "calibration", "ood"] {
        let mut runtime = runtime();
        match changed {
            "base" => runtime.parameter_bundle.base_bundle_digest = digest("changed"),
            "organ" => runtime.parameter_bundle.organ_bundle_digest = digest("changed"),
            "cell" => runtime.parameter_bundle.cell_bundle_digest = Some(digest("changed")),
            "head" => runtime.parameter_bundle.action_head_digest = digest("changed"),
            "calibration" => {
                runtime.parameter_bundle.calibration_artifact_digest = digest("changed")
            }
            "ood" => runtime.parameter_bundle.ood_artifact_digest = digest("changed"),
            _ => unreachable!(),
        }
        assert_eq!(
            build_decision_cell_receipt_v1(&request, runtime, observation()),
            Err(DecisionCellContractError::RuntimeBindingMismatch),
            "{changed}"
        );
    }
}

#[test]
fn nonterminal_observation_cannot_smuggle_a_choice() {
    let request = request();
    let mut observation = observation();
    observation.status = DecisionCellTerminalStatusV1::Indeterminate;
    assert_eq!(
        build_decision_cell_receipt_v1(&request, runtime(), observation),
        Err(DecisionCellContractError::NonTerminalOutputPresent)
    );
}

#[test]
fn abstain_disposition_never_selects_an_action_or_target() {
    let request = request();
    let mut observation = observation();
    observation.disposition_scores_q24 = [0, 0, 9, 0, 0, 0];
    let receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation).expect("receipt");
    assert_eq!(
        receipt.disposition,
        Some(DecisionCellDispositionV1::Abstain)
    );
    assert_eq!(receipt.selected_action_id, None);
    assert_eq!(receipt.selected_target_id, None);
}

#[test]
fn stop_disposition_does_not_select_or_consume_an_action() {
    let request = request();
    let mut observation = observation();
    observation.action_scores_q24 = vec![0, 10];
    observation.disposition_scores_q24 = [0, 10, 0, 0, 0, 0];
    let receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation).expect("receipt");
    assert_eq!(receipt.selected_action_id, None);
    assert_eq!(receipt.selected_target_id, None);
    assert_eq!(receipt.disposition, Some(DecisionCellDispositionV1::Stop));
}

#[test]
fn receipt_tampering_is_detected() {
    let request = request();
    let mut receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation()).expect("receipt");
    receipt.confidence_ppm -= 1;
    assert_eq!(
        verify_decision_cell_receipt_v1(&request, &receipt),
        Err(DecisionCellContractError::ReceiptDigestMismatch)
    );
}

#[test]
fn durable_receipt_codec_round_trips_exactly() {
    let request = request();
    let receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation()).expect("receipt");
    let bytes = encode_decision_cell_receipt_v1(&request, &receipt).expect("encode");
    let decoded = decode_decision_cell_receipt_v1(&request, &bytes).expect("decode");
    assert_eq!(decoded, receipt);
    assert_eq!(
        encode_decision_cell_receipt_v1(&request, &decoded).expect("re-encode"),
        bytes
    );
}

#[test]
fn durable_receipt_codec_rejects_unknown_fields_and_semantic_tamper() {
    let request = request();
    let receipt =
        build_decision_cell_receipt_v1(&request, runtime(), observation()).expect("receipt");
    let bytes = encode_decision_cell_receipt_v1(&request, &receipt).expect("encode");
    let text = String::from_utf8(bytes).expect("utf8");
    let changed = text.replacen(
        "\"authority_granted\":false",
        "\"authority_granted\":false,\"unknown\":1",
        1,
    );
    assert_eq!(
        decode_decision_cell_receipt_v1(&request, changed.as_bytes()),
        Err(DecisionCellContractError::InvalidEncoding)
    );

    let changed = text.replacen("\"confidence_ppm\":900000", "\"confidence_ppm\":899999", 1);
    assert_eq!(
        decode_decision_cell_receipt_v1(&request, changed.as_bytes()),
        Err(DecisionCellContractError::ReceiptDigestMismatch)
    );
}
