use super::*;
use crate::decode_runtime_topology_candidate_v1_json;
use crate::encode_runtime_topology_candidate_v1_json;

fn vectors() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../hepta-types/PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json"
    ))
    .expect("shared conformance vectors")
}

#[test]
fn topology_versions_roundtrip_their_own_goldens_and_reject_cross_version_inputs() {
    for vector in vectors()["validVectors"].as_array().expect("vectors") {
        let protocol = vector["protocol"].as_str().expect("protocol");
        let raw = serde_json::to_vec(&vector["json"]).expect("encode fixture");
        match protocol {
            "RuntimeTopologyCandidateV1" => {
                let value =
                    decode_runtime_topology_candidate_v1_json(&raw).expect("historical read");
                assert_eq!(
                    value
                        .as_inner()
                        .content_digest()
                        .expect("digest")
                        .to_string(),
                    vector["expectedSemanticSha256"]
                );
                let encoded = encode_runtime_topology_candidate_v1_json(&value).expect("encode V1");
                assert_eq!(
                    decode_runtime_topology_candidate_v1_json(&encoded).expect("roundtrip"),
                    value
                );
                assert_eq!(
                    decode_runtime_topology_candidate_v2_json(&raw),
                    Err(PlatformTopologyV2WireError::Transport(
                        PlatformTypesWireError::InvalidKind
                    ))
                );
            }
            "RuntimeTopologyCandidateV2" => {
                let value = decode_runtime_topology_candidate_v2_json(&raw).expect("current V2");
                assert_eq!(
                    value
                        .as_inner()
                        .content_digest()
                        .expect("digest")
                        .to_string(),
                    vector["expectedSemanticSha256"]
                );
                let encoded = encode_runtime_topology_candidate_v2_json(&value).expect("encode V2");
                assert_eq!(
                    decode_runtime_topology_candidate_v2_json(&encoded).expect("roundtrip"),
                    value
                );
                assert_eq!(
                    decode_runtime_topology_candidate_v1_json(&raw),
                    Err(PlatformTypesWireError::InvalidKind)
                );
            }
            "PromptDeliveryObservationV2" => {}
            _ => panic!("unknown protocol"),
        }
    }
}

#[test]
fn topology_versions_reject_all_shared_invalid_vectors() {
    for vector in vectors()["rawInvalidVectors"].as_array().expect("vectors") {
        let raw = vector["rawJson"].as_str().expect("raw").as_bytes();
        match vector["protocol"].as_str().expect("protocol") {
            "RuntimeTopologyCandidateV1" => assert!(
                decode_runtime_topology_candidate_v1_json(raw).is_err(),
                "{}",
                vector["id"]
            ),
            "RuntimeTopologyCandidateV2" => assert!(
                decode_runtime_topology_candidate_v2_json(raw).is_err(),
                "{}",
                vector["id"]
            ),
            "PromptDeliveryObservationV2" | "parser" => {}
            _ => panic!("unknown protocol"),
        }
    }
}

#[test]
fn v2_wrapper_bounds_retained_capacity_and_keeps_complete_commitment() {
    let document = vectors();
    let vector = document["validVectors"]
        .as_array()
        .expect("vectors")
        .iter()
        .find(|value| value["protocol"] == "RuntimeTopologyCandidateV2")
        .expect("V2 vector");
    let raw = serde_json::to_vec(&vector["json"]).expect("raw");
    let expected = decode_runtime_topology_candidate_v2_json(&raw).expect("V2");
    let mut value = expected.as_inner().clone();
    let mut deltas = Vec::with_capacity(RuntimeTopologyCandidateV2::MAX_DELTAS_V2 * 16);
    deltas.append(&mut value.deltas);
    value.deltas = deltas;
    value.deltas[0].related_module_ids =
        Vec::with_capacity(RuntimeTopologyCandidateV2::MAX_DELTAS_V2 * 16);
    let observed = ValidatedRuntimeTopologyCandidateV2::new(value).expect("bounded wrapper");
    assert_eq!(observed, expected);
    assert!(observed.as_inner().deltas.capacity() <= RuntimeTopologyCandidateV2::MAX_DELTAS_V2);
    assert!(
        observed.as_inner().deltas[0].related_module_ids.capacity()
            <= RuntimeTopologyCandidateV2::MAX_DELTAS_V2
    );
    let mut substituted = observed.into_inner();
    substituted.evaluation_digest = codex_hepta_types::Digest32::of_bytes(b"substituted");
    assert_eq!(
        ValidatedRuntimeTopologyCandidateV2::new(substituted),
        Err(PlatformTopologyV2WireError::Topology(
            RuntimeTopologyContractErrorV2::CandidateDigestMismatch
        ))
    );
}
