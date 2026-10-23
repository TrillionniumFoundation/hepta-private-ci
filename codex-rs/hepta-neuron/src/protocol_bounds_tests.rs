use super::*;

use pretty_assertions::assert_eq;

fn assert_profile_rejected(
    value: &NeuronRuntimeConfigProtocolV1,
    section: &str,
    field: &str,
    wire_value: serde_json::Value,
) {
    let native = native_config();
    let baseline = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    let mut wire: serde_json::Value = checked(serde_json::from_slice(&checked(
        encode_neuron_runtime_config_v1(&baseline),
    )));
    wire[section][field] = wire_value;
    assert_eq!(
        (
            encode_neuron_runtime_config_v1(value).err(),
            decode_neuron_runtime_config_v1(&checked(serde_json::to_vec(&wire))).err(),
        ),
        (
            Some(NeuronProtocolError::InvalidField("runtime config")),
            Some(NeuronProtocolError::InvalidField("runtime config")),
        ),
    );
}

#[test]
fn runtime_config_inhibition_bound_applies_to_encoder_and_decoder() {
    let native = native_config();
    let mut value = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    for edges in [4_097, u32::MAX] {
        value.inhibition_edges = edges;
        assert_profile_rejected(
            &value,
            "stateDimensions",
            "inhibitionEdges",
            serde_json::json!(edges),
        );
    }
}

#[test]
fn runtime_config_top_k_bound_applies_to_encoder_and_decoder() {
    let native = native_config();
    let mut value = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    for ratio in [9_999, 1, 0] {
        value.top_k_minimum_ratio_ppm = ratio;
        assert_profile_rejected(
            &value,
            "topKPolicy",
            "minimumRatioPpm",
            serde_json::json!(ratio),
        );
    }
}

#[test]
fn runtime_config_eligibility_bound_applies_to_encoder_and_decoder() {
    let native = native_config();
    let mut value = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    for norm in [4 * Q + 1, i64::MAX, 0, -1] {
        value.eligibility_maximum_norm_q24 = norm;
        assert_profile_rejected(
            &value,
            "eligibilityProfile",
            "maximumNormQ24",
            serde_json::json!(norm),
        );
    }
}

#[test]
fn runtime_config_profile_boundary_values_still_roundtrip() {
    let native = native_config();
    let baseline = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    for (edges, minimum_ratio, maximum_ratio, norm) in [
        (0, 10_000, 10_000, 1),
        (4_096, 10_000, 200_000, 4 * Q),
        (4_096, 200_000, 200_000, 4 * Q),
    ] {
        let value = NeuronRuntimeConfigProtocolV1 {
            inhibition_edges: edges,
            top_k_minimum_ratio_ppm: minimum_ratio,
            top_k_maximum_ratio_ppm: maximum_ratio,
            eligibility_maximum_norm_q24: norm,
            ..baseline.clone()
        };
        assert_eq!(
            checked(decode_neuron_runtime_config_v1(&checked(
                encode_neuron_runtime_config_v1(&value),
            ))),
            value,
        );
    }
}

#[test]
fn canonical_runtime_config_native_boundaries_match_wire_admission() {
    for (width, top_k, edges) in [(5, 1, 0), (100, 1, 0), (100, 20, 4_096), (256, 3, 0)] {
        let mut native = native_config();
        native.width = width;
        native.top_k = top_k;
        native.inhibition = (0..width)
            .flat_map(|target| {
                (0..width).filter_map(move |source| {
                    (source != target).then_some(crate::InhibitoryEdge {
                        source,
                        target,
                        weight_q24: 0,
                    })
                })
            })
            .take(edges)
            .collect();
        let value = checked(canonical_runtime_config_v1(
            &runtime_config(&native),
            &native,
            "2099-01-01T00:00:00Z",
        ));
        assert_eq!(
            checked(decode_neuron_runtime_config_v1(&checked(
                encode_neuron_runtime_config_v1(&value),
            ))),
            value,
        );
    }
}
