use super::*;
use pretty_assertions::assert_eq;
#[test]
fn full_port_roundtrip_preserves_every_stage_and_original_identity() {
    let mut port = CanonicalPortInputV1 {
        run_id: StableId::new("actual.canary.run").unwrap(),
        snapshot_digest: Digest32::of_bytes(b"actual snapshot"),
        objective_digest: Digest32::of_bytes(b"actual objective"),
        candidate_set_digest: Digest32::of_bytes(b"actual candidate set"),
        predecessor_digest: Digest32::ZERO,
        budget_micros: 1000,
        stage: CanonicalStageV1::NeuralSignalCollected,
    };
    for stage in [
        CanonicalStageV1::ObjectiveValidated,
        CanonicalStageV1::UtilityEvaluated,
        CanonicalStageV1::NeuralSignalCollected,
        CanonicalStageV1::PromptPortfolioBuilt,
        CanonicalStageV1::IntuitionDecided,
        CanonicalStageV1::ContextCompiled,
        CanonicalStageV1::EvaluationAdmitted,
    ] {
        port.stage = stage;
        let bytes = encode_canonical_port_input_material_v1(&port).unwrap();
        assert_eq!(
            decode_canonical_port_input_material_v1(&bytes).unwrap(),
            port
        );
        for prefix in 0..bytes.len() {
            assert!(decode_canonical_port_input_material_v1(&bytes[..prefix]).is_err());
        }
        let mut widened = bytes.clone();
        widened.extend_from_slice(b"execution_authority=true");
        assert!(decode_canonical_port_input_material_v1(&widened).is_err());
        let mut unknown_stage = bytes;
        *unknown_stage.last_mut().unwrap() = 7;
        assert!(decode_canonical_port_input_material_v1(&unknown_stage).is_err());
    }
    assert!(
        decode_canonical_port_input_material_v1(&vec![
            b' ';
            MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1
                + 1
        ])
        .is_err()
    );
}
