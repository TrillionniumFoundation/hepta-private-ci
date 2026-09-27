include!("contract_tests_base.rs");

#[test]
fn checked_in_cross_language_negative_vectors_are_rejected() {
    let document: serde_json::Value = serde_json::from_str(include_str!(
        "../../../qualification/cognitive-types-v1/negative-vectors.json"
    ))
    .expect("negative vector document");
    let cases = document["cases"].as_array().expect("negative vector cases");
    assert_eq!(cases.len(), 7);
    for case in cases {
        let name = case["name"].as_str().expect("negative vector name");
        let contract = case["contract"].as_str().expect("negative vector contract");
        let wire = case["wire"].as_str().expect("negative vector wire");
        let expected = case["expectedErrorContains"]
            .as_str()
            .expect("negative vector expected error");
        let error = match contract {
            "ModalitySpanRefV1" => decode_wire_v1::<ModalitySpanRefV1>(wire.as_bytes())
                .map(|_| ())
                .expect_err(name),
            "RecallPacketV1" => decode_wire_v1::<RecallPacketV1>(wire.as_bytes())
                .map(|_| ())
                .expect_err(name),
            "PlasticityBatchV1" => decode_wire_v1::<PlasticityBatchV1>(wire.as_bytes())
                .map(|_| ())
                .expect_err(name),
            "TopologyProposalV1" => decode_wire_v1::<TopologyProposalV1>(wire.as_bytes())
                .map(|_| ())
                .expect_err(name),
            "ForgetPropagationReceiptV1" => {
                decode_wire_v1::<ForgetPropagationReceiptV1>(wire.as_bytes())
                    .map(|_| ())
                    .expect_err(name)
            }
            other => panic!("unregistered negative-vector contract: {other}"),
        };
        assert!(
            error.to_string().contains(expected),
            "{name}: unexpected error {error}"
        );
    }
}
