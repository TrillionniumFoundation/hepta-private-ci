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
        for field in [
            "run_id",
            "snapshot_digest",
            "objective_digest",
            "candidate_set_digest",
            "predecessor_digest",
            "budget_micros",
            "stage",
        ] {
            let mut partial: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
            partial["port"].as_object_mut().unwrap().remove(field);
            assert!(
                decode_canonical_port_input_material_v1(&serde_json::to_vec(&partial).unwrap())
                    .is_err()
            );
        }
        let mut widened: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        widened["port"]["execution_authority"] = serde_json::json!(true);
        assert!(
            decode_canonical_port_input_material_v1(&serde_json::to_vec(&widened).unwrap())
                .is_err()
        );
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
