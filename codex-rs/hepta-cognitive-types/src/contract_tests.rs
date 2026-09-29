include!("contract_tests_base.rs");

#[test]
fn split_contract_test_source_contains_all_golden_vectors() {
    let source = include_str!("contract_tests_base.rs");
    for digest in [
        "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273",
        "22d5a29e55ad08c3541eb8eb9afe577eb5efd1a75e0d37ea1c64eae436db0540",
        "4f85c20ffc206e5fe472dfd5be8ab7a71e5d79eb8661bce6dcb5a8f8284b777f",
        "5b7f4f5addf00b7e331d6682e9fb5be99dbc438d4cfc915ac536e8a16dcb23c5",
        "1649b8d6d428cd485dfbf2c46b2b0b82f41baec6c1cd0bee5da7a511cad93d6c",
        "27adab5830e8849e2ac765bf69728bfb10d000caaa639c84e2cec9e3adec5a00",
        "0a3ec1c285ce6f7c710c975c79497a870c2d9c6a91696e22c16a11c43b0983fc",
        "78294b30bac6687f2332b4294471d3ba609bb827e0b01ec77280e2eeedc07a0d",
        "94f4265ca6c39c314e1d350aba45d78dd6b9aa973bfd740f8bb81df0995a5787",
        "779fc9779a6a170aba791fd4c984eb35855d5cbc394c37945123bc0ddf8dd41a",
        "83fed9c7f5a4677f9564ac36b524cf8865effc27f032ca465d4368c114ac40aa",
        "f0f4f746a2c2e3f5a22bd5d5ce1760185d5c6579ef0bb6e5a23b1722edbfd62b",
    ] {
        assert!(
            source.contains(digest),
            "missing split-source vector {digest}"
        );
    }
}

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

include!("identity_tests.rs");

include!("handoff_tests.rs");
include!("codec_tests.rs");
include!("handoff_profile_tests.rs");
