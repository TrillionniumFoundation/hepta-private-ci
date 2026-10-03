use super::*;

use pretty_assertions::assert_eq;
use serde_json::Value;

fn positional(value: &Value, fields: &[&str]) -> Value {
    Value::Array(fields.iter().map(|field| value[*field].clone()).collect())
}

fn runtime_wire() -> Value {
    let native = native_config();
    let value = checked(canonical_runtime_config_v1(
        &runtime_config(&native),
        &native,
        "2099-01-01T00:00:00Z",
    ));
    checked(serde_json::from_slice(&checked(
        encode_neuron_runtime_config_v1(&value),
    )))
}

#[test]
fn runtime_config_rejects_positional_top_level_record() {
    let wire = positional(
        &runtime_wire(),
        &[
            "configId",
            "generation",
            "encoderDigest",
            "headDigest",
            "stateDimensions",
            "fixedPointProfile",
            "topKPolicy",
            "inhibitionDigest",
            "homeostasisProfile",
            "eligibilityProfile",
            "resourceEnvelope",
            "expiry",
        ],
    );
    assert_eq!(
        decode_neuron_runtime_config_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn runtime_config_rejects_each_positional_nested_profile() {
    let profiles: [(&str, &[&str]); 6] = [
        (
            "stateDimensions",
            &[
                "temporalState",
                "activation",
                "modulators",
                "inhibitionEdges",
            ],
        ),
        (
            "fixedPointProfile",
            &[
                "stateScale",
                "rounding",
                "stateMinimumQ24",
                "stateMaximumQ24",
                "checkedWideIntermediates",
            ],
        ),
        (
            "topKPolicy",
            &[
                "minimumRatioPpm",
                "maximumRatioPpm",
                "tieBreak",
                "perPopulationFirst",
            ],
        ),
        (
            "homeostasisProfile",
            &[
                "movingAverageAlphaQ24",
                "thresholdStepQ24",
                "thresholdMinimumQ24",
                "thresholdMaximumQ24",
                "saturationLimit",
            ],
        ),
        (
            "eligibilityProfile",
            &[
                "traceDimension",
                "maximumNormQ24",
                "decayQ24",
                "localRuleDigest",
            ],
        ),
        (
            "resourceEnvelope",
            &[
                "p95LatencyMicros",
                "p99LatencyMicros",
                "transientAllocationBytes",
                "checkpointBytes",
                "writeAmplificationPpm",
            ],
        ),
    ];
    for (profile, fields) in profiles {
        let mut wire = runtime_wire();
        wire[profile] = positional(&wire[profile], fields);
        assert_eq!(
            decode_neuron_runtime_config_v1(&checked(serde_json::to_vec(&wire))).err(),
            Some(NeuronProtocolError::Json),
            "{profile}"
        );
    }
}

#[test]
fn tick_input_rejects_positional_top_level_record() {
    let input = crate::NeuronTickInputV1 {
        tick_id: id("tick.shape"),
        subject_id: id("subject.shape"),
        logical_sequence: 1,
        monotonic_time_micros: 42,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: crate::canonical_feature_vector_digest_v1(&[Q, 0, -Q]),
        feature_vector_q24: vec![Q, 0, -Q],
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: None,
        modulator_digest: None,
    };
    let wire: Value = checked(serde_json::from_slice(&checked(
        encode_neuron_tick_input_v1(&input),
    )));
    assert_eq!(
        checked(decode_neuron_tick_input_v1(&checked(serde_json::to_vec(
            &wire
        )))),
        input
    );
    let positional = positional(
        &wire,
        &[
            "tickId",
            "subjectId",
            "logicalSequence",
            "monotonicTimeMicros",
            "checkpointDigest",
            "inputFeatureDigest",
            "featureVectorQ24",
            "objectiveDigest",
            "nduSnapshotDigest",
            "bodyGeneration",
            "modulatorDigest",
        ],
    );
    assert_eq!(
        decode_neuron_tick_input_v1(&checked(serde_json::to_vec(&positional))).err(),
        Some(NeuronProtocolError::Json)
    );
}

fn receipt_wire() -> Value {
    let (_, _, tick) = committed();
    let receipt = checked(canonical_tick_receipt_v1(&tick));
    checked(serde_json::from_slice(&checked(
        encode_neuron_tick_receipt_v1(&receipt),
    )))
}

#[test]
fn tick_receipt_rejects_positional_top_level_record() {
    let wire = positional(
        &receipt_wire(),
        &[
            "tickId",
            "checkpointBefore",
            "checkpointAfter",
            "activationDigest",
            "activeIndices",
            "sparsityPpm",
            "thresholdDigest",
            "eligibilityDigest",
            "predictionErrorQ24",
            "confidencePpm",
            "oodPpm",
            "abstain",
            "resourceReceipt",
        ],
    );
    assert_eq!(
        decode_neuron_tick_receipt_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn tick_receipt_rejects_positional_resource_record() {
    let mut wire = receipt_wire();
    wire["resourceReceipt"] = positional(
        &wire["resourceReceipt"],
        &[
            "executionMicros",
            "transientAllocationBytes",
            "checkpointBytes",
            "saturationCount",
            "queueAgeMicros",
        ],
    );
    assert_eq!(
        decode_neuron_tick_receipt_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn signal_rejects_positional_top_level_record() {
    let signal = NeuronSignalReceiptV1 {
        signal_set_id: id("signal.shape"),
        model_runtime_digest: Digest32::of_bytes(b"runtime"),
        temporal_state_digest: Digest32::of_bytes(b"temporal"),
        signals_q24: vec![Q, 0, -Q],
        activation_sparsity_ppm: 333_333,
        ood_ppm: 50_000,
        abstain: false,
        authority: AuthorityPosture::DENY_ALL,
    };
    let wire: Value = checked(serde_json::from_slice(&checked(
        encode_neuron_signal_receipt_v1(&signal),
    )));
    let wire = positional(
        &wire,
        &[
            "signalSetId",
            "modelRuntimeDigest",
            "temporalStateDigest",
            "signals",
            "activationSparsityPpm",
            "oodPpm",
            "abstain",
        ],
    );
    assert_eq!(
        decode_neuron_signal_receipt_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn checkpoint_rejects_positional_top_level_record() {
    let value = checkpoint_protocol();
    let wire: Value = checked(serde_json::from_slice(&checked(
        encode_neuron_checkpoint_v1(&value),
    )));
    let wire = positional(
        &wire,
        &[
            "checkpointId",
            "predecessorId",
            "generation",
            "encoderDigest",
            "headDigest",
            "temporalStateDigest",
            "thresholdDigest",
            "activationSummary",
            "eligibilityDigest",
            "logicalSequence",
            "normalizationDigest",
            "expiresUnixMs",
        ],
    );
    assert_eq!(
        decode_neuron_checkpoint_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn checkpoint_rejects_positional_activation_record() {
    let value = checkpoint_protocol();
    let mut wire: Value = checked(serde_json::from_slice(&checked(
        encode_neuron_checkpoint_v1(&value),
    )));
    wire["activationSummary"] = positional(
        &wire["activationSummary"],
        &["activeIndices", "sparsityPpm", "saturationCount"],
    );
    assert_eq!(
        decode_neuron_checkpoint_v1(&checked(serde_json::to_vec(&wire))).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn object_decoder_preserves_duplicate_unknown_and_trailing_rejection() {
    let original = checked(serde_json::to_string(&runtime_wire()));
    for wire in [
        original.replacen(
            "\"generation\":1",
            "\"generation\":1,\"gen\\u0065ration\":1",
            1,
        ),
        original.replacen("\"generation\":1", "\"generation\":1,\"generation\":1", 1),
        original.replacen("\"activation\":5", "\"activation\":5,\"activation\":5", 1),
        original.replacen(
            "\"activation\":5",
            "\"activation\":5,\"unknownCritical\":0",
            1,
        ),
        format!("{original} {{}}"),
    ] {
        assert_ne!(wire, original);
        assert_eq!(
            decode_neuron_runtime_config_v1(wire.as_bytes()).err(),
            Some(NeuronProtocolError::Json)
        );
    }
    assert!(decode_neuron_runtime_config_v1(format!(" \n{original}\t ").as_bytes()).is_ok());
}
