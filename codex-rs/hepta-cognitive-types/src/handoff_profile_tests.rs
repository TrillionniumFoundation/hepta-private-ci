// These aliases exercise the public generic codec and handoff, not a second
// production contract. All payload validation delegates to the real fixtures.
#[derive(Clone, Debug, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
#[serde(transparent)]
struct OtherHandoffSchema<T>(T);

impl<T: crate::wire::CognitiveContractV1> crate::wire::CognitiveContractV1
    for OtherHandoffSchema<T>
{
    const CONTRACT_ID: &'static str = T::CONTRACT_ID;
    const SCHEMA_ID: &'static str = "hepta.test.unregistered-handoff-schema.v1";
    const MAX_ENCODED_BYTES: usize = T::MAX_ENCODED_BYTES;

    fn validate_contract(&self) -> Result<(), crate::hnmf::HnmfContractError> {
        self.0.validate_contract()
    }
}

#[derive(Clone, Debug, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
#[serde(transparent)]
struct OtherHandoffLimit<T>(T);

impl<T: crate::wire::CognitiveContractV1> crate::wire::CognitiveContractV1
    for OtherHandoffLimit<T>
{
    const CONTRACT_ID: &'static str = T::CONTRACT_ID;
    const SCHEMA_ID: &'static str = T::SCHEMA_ID;
    const MAX_ENCODED_BYTES: usize = T::MAX_ENCODED_BYTES + 1;

    fn validate_contract(&self) -> Result<(), crate::hnmf::HnmfContractError> {
        self.0.validate_contract()
    }
}

fn assert_handoff_rejects_profile_aliases<T: crate::wire::CognitiveContractV1 + std::fmt::Debug>(
    binding: &crate::consumer::CanonicalConsumerBindingV1,
    value: T,
) {
    use crate::contract::ContractErrorCodeV1;
    use crate::contract::Validated;

    let schema_alias = OtherHandoffSchema(value.clone());
    // Frozen V1 intentionally does not bind schema. Preserve this historical
    // interpretation and reject the alias at the current handoff boundary.
    assert_eq!(
        canonical_contract_digest_v1(&schema_alias).expect("alias frozen digest"),
        binding.canonical_payload_sha256.digest()
    );
    let wire = encode_wire_v1(&schema_alias).expect("alias is valid for its own schema");
    let expected = Validated::new(schema_alias).expect("alias projection");
    let error = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect_err("a different schema cannot inherit the binding");
    assert_eq!(error.code, ContractErrorCodeV1::SchemaMismatch);
    assert_eq!(error.field_path, "binding.payloadSchema");

    let limit_alias = OtherHandoffLimit(value.clone());
    let wire = encode_wire_v1(&limit_alias).expect("larger-limit alias");
    assert_eq!(wire, encode_wire_v1(&value).expect("registered wire"));
    let expected = Validated::new(limit_alias).expect("limit alias projection");
    let error = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect_err("a different limit cannot inherit the binding");
    assert_eq!(error.code, ContractErrorCodeV1::ContractMismatch);
    assert_eq!(error.field_path, "binding.payloadLimit");

    // Rejection must not invalidate or cache a conclusion about the genuine
    // value. A subsequent checked call follows the same existing public API.
    assert_common_semantic_comparison(binding, value);
}

#[test]
fn all_five_consumer_families_reject_schema_and_resource_profile_substitution() {
    use crate::consumer::CanonicalConsumerV1;

    for consumer in CanonicalConsumerV1::ALL {
        match consumer {
            CanonicalConsumerV1::CognitiveRead
            | CanonicalConsumerV1::CognitiveStore
            | CanonicalConsumerV1::CompactEngine => {
                let binding = test_consumer_binding(consumer, "op:profile", "source", "cut");
                assert_handoff_rejects_profile_aliases(&binding, event());
            }
            CanonicalConsumerV1::MemoryRetrieval | CanonicalConsumerV1::IntelligenceControl => {
                let binding = test_recall_consumer_binding(consumer, "op:profile", "source", "cut");
                assert_handoff_rejects_profile_aliases(&binding, recall_packet());
            }
        }
    }
}

#[test]
fn public_wire_json_violation_does_not_echo_input_text() {
    use crate::contract::ContractErrorCodeV1;

    let marker = "input-marker-do-not-log";
    let wire = encode_wire_v1(&event()).expect("canonical event");
    let mut document: serde_json::Value = serde_json::from_slice(&wire).expect("wire document");
    document["schemaVersion"] = serde_json::Value::String(marker.to_owned());
    let malformed = serde_json::to_vec(&document).expect("malformed version input");
    let error = decode_wire_v1::<crate::hnmf::MemoryEventV1>(&malformed)
        .expect_err("string version must reject");
    let violation = error.violation();
    assert_eq!(violation.code, ContractErrorCodeV1::InvalidValue);
    assert_eq!(violation.field_path, "wire");
    assert!(violation.message.starts_with("invalid wire JSON at line "));
    assert!(!violation.message.contains(marker));
    assert!(
        !serde_json::to_string(&violation)
            .expect("audit JSON")
            .contains(marker)
    );
}
