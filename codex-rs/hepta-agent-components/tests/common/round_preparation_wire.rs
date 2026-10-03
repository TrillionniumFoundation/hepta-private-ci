//! Transport fixtures grant no reservation or file custody.
use super::*;
#[test]
fn preparation_preserves_whole_bytes_and_refuses_other_purposes() {
    let payload = vec![0xab; 4096];
    let bytes = encode_round_preparation_request_v1(&RoundPreparationRequestV1::from_round_bytes(&payload).unwrap()).unwrap();
    assert_eq!(decode_round_preparation_request_v1(&bytes).unwrap().round_bytes().unwrap(), payload);
    match decode_frozen_generator_operation_v1(&bytes).unwrap() {
        FrozenGeneratorOperationV1::PrepareRound(actual) => assert_eq!(actual.round_bytes().unwrap(), payload),
        _ => panic!("preparation purpose changed"),
    }
    assert!(decode_frozen_generator_request_v1(&bytes).is_err());
    assert!(decode_frozen_generator_observation_request_v2(&bytes).is_err());
    assert!(RoundPreparationRequestV1::from_round_bytes(&vec![0;4097]).is_err());
    for value in [json!({"schema_version":8,"round_payload_hex":"AA"}),json!({"schema_version":8,"round_payload_hex":"a"}),json!({"schema_version":8,"round_payload_hex":"ab","dispatch":true})] {
        assert!(decode_round_preparation_request_v1(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}
#[test]
fn preparation_retains_whole_pin_and_refuses_aliases_or_authority() {
    use codex_hepta_agent_components::types::Digest32;
    let pin = Digest32::of_bytes(b"whole bundle").to_string();
    let expected = json!({"schema_version":8,"round_payload_digest":pin,"result":{"outcome":"prepared","bundle":{"path":"/root/original/bundle.json","digest":pin}}});
    let actual = decode_round_preparation_response_v1(&serde_json::to_vec(&expected).unwrap()).unwrap();
    assert_eq!(serde_json::from_slice::<serde_json::Value>(&encode_round_preparation_response_v1(&actual).unwrap()).unwrap(),expected);
    for path in ["relative.json","/root/../bundle.json","/root/./bundle.json","/root//bundle.json"] {
        let mut changed=expected.clone();changed["result"]["bundle"]["path"]=json!(path);
        assert!(decode_round_preparation_response_v1(&serde_json::to_vec(&changed).unwrap()).is_err());
    }
    for field in ["authority","activation","replace_original"] {
        let mut changed=expected.clone();changed["result"][field]=json!(true);
        assert!(decode_round_preparation_response_v1(&serde_json::to_vec(&changed).unwrap()).is_err());
    }
    let mut changed=expected;changed["round_payload_digest"]=json!("0".repeat(64));
    assert!(decode_round_preparation_response_v1(&serde_json::to_vec(&changed).unwrap()).is_err());
}
