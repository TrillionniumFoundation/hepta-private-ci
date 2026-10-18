use super::*;
use codex_hepta_types::Digest32;

fn request(purpose: SelfIterationOwnerPurposeV1) -> SelfIterationOwnerRequestV1 {
    SelfIterationOwnerRequestV1::from_original_bytes(
        purpose,
        b"whole original consumer",
        b"whole original record",
        SelfIterationOwnerModelFactsV1 {
            request_id: "original.request".into(),
            envelope_digest: Digest32::of_bytes(b"envelope").to_string(),
            candidate_digest: Digest32::of_bytes(b"frozen").to_string(),
            output_digest: Digest32::of_bytes(b"whole output").to_string(),
            native_run_digest: Digest32::of_bytes(b"original terminal").to_string(),
        },
    )
    .unwrap()
}
#[test]
fn finite_schema_does_not_allow_cross_role_or_extra_authority() {
    let mut value = serde_json::to_value(request(SelfIterationOwnerPurposeV1::Evaluate)).unwrap();
    value["schema_version"] = 6.into();
    assert!(decode_self_iteration_owner_request_v1(&serde_json::to_vec(&value).unwrap()).is_err());
    value["schema_version"] = 5.into();
    value["sign_payload"] = "caller payload".into();
    assert!(decode_self_iteration_owner_request_v1(&serde_json::to_vec(&value).unwrap()).is_err());
    value.as_object_mut().unwrap().remove("sign_payload");
    value["model_facts"]["authority"] = true.into();
    assert!(decode_self_iteration_owner_request_v1(&serde_json::to_vec(&value).unwrap()).is_err());
}
#[test]
fn whole_owner_large_transport_keeps_old_generator_limit() {
    let original = vec![0xd1; MAX_SELF_ITERATION_OWNER_EVALUATION_BYTES_V1];
    let response = SelfIterationOwnerResponseV1::Granted(
        SelfIterationOwnerGrantedV1::from_publication(
            SelfIterationOwnerPurposeV1::Evaluate,
            Digest32::of_bytes(b"frozen"),
            &original,
        )
        .unwrap(),
    );
    let bytes =
        encode_self_iteration_owner_response_v1(SelfIterationOwnerPurposeV1::Evaluate, &response)
            .unwrap();
    assert!(bytes.len() > 64 * 1024);
    match decode_self_iteration_owner_response_v1(SelfIterationOwnerPurposeV1::Evaluate, &bytes)
        .unwrap()
    {
        SelfIterationOwnerResponseV1::Granted(value) => {
            assert_eq!(value.publication().unwrap(), original)
        }
        _ => panic!("whole publication lost"),
    }
    assert!(
        decode_self_iteration_owner_response_v1(SelfIterationOwnerPurposeV1::Observe, &bytes)
            .is_err()
    );
    assert!(
        SelfIterationOwnerGrantedV1::from_publication(
            SelfIterationOwnerPurposeV1::Evaluate,
            Digest32::of_bytes(b"frozen"),
            &vec![0; MAX_SELF_ITERATION_OWNER_EVALUATION_BYTES_V1 + 1]
        )
        .is_err()
    );
    assert_eq!(MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1, 16 * 1024);
}
#[test]
fn absent_or_noncanonical_fact_identity_is_refused() {
    let original = request(SelfIterationOwnerPurposeV1::Select);
    let mut value = serde_json::to_value(&original).unwrap();
    for field in [
        "envelope_digest",
        "candidate_digest",
        "output_digest",
        "native_run_digest",
    ] {
        let mut wrong = value.clone();
        wrong["model_facts"][field] = "00".repeat(32).into();
        assert!(
            decode_self_iteration_owner_request_v1(&serde_json::to_vec(&wrong).unwrap()).is_err()
        );
    }
    value["frozen_consumer_hex"] = "AA".into();
    assert!(decode_self_iteration_owner_request_v1(&serde_json::to_vec(&value).unwrap()).is_err());
}
#[test]
fn owner_purpose_and_full_original_fact_tuple_survive_dispatch() {
    for purpose in [
        SelfIterationOwnerPurposeV1::Evaluate,
        SelfIterationOwnerPurposeV1::Select,
        SelfIterationOwnerPurposeV1::Observe,
    ] {
        let original = request(purpose);
        let bytes = encode_self_iteration_owner_request_v1(&original).unwrap();
        let FrozenGeneratorOperationV1::IndependentOwner(actual) =
            decode_frozen_generator_operation_v1(&bytes).unwrap()
        else {
            panic!("another operation")
        };
        assert_eq!(actual.model_facts, original.model_facts);
        assert_eq!(
            actual.original_bytes().unwrap(),
            original.original_bytes().unwrap()
        );
        assert_eq!(actual.purpose, purpose);
    }
}
