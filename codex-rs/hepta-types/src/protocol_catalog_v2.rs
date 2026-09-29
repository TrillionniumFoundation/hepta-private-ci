//! Normative, typed catalog for the public `platform.types` protocol surface.
//!
//! Candidate-bound JSON and Markdown projections are generated from these Rust
//! descriptors. A referenced executable schema must exist and contain every
//! descriptor field before qualification can pass.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProtocolFieldDescriptorV2 {
    pub name: &'static str,
    pub wire_type: &'static str,
    pub required: bool,
    pub maximum_encoded_bytes: Option<usize>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProtocolDescriptorV2 {
    pub id: &'static str,
    pub version: u32,
    pub semantic_type_id: &'static str,
    pub semantic_encoding: &'static str,
    pub transport_schema: Option<&'static str>,
    pub codec_owner: &'static str,
    pub compatibility: &'static str,
    pub fields: &'static [ProtocolFieldDescriptorV2],
}

const PROMPT_V1_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("compilation_id", "stable_id", true, Some(128)),
    field("provider_request_digest", "digest32", true, Some(32)),
    field("delivered", "bool", true, None),
    field("rejected_reason", "optional_stable_id", false, Some(64)),
    field(
        "observed_token_positions",
        "optional_u32_array",
        false,
        Some(32_768),
    ),
    field("truncation_observed", "bool", true, None),
];

const PROMPT_V2_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("compilation_id", "stable_id", true, Some(128)),
    field("provider_request_digest", "digest32", true, Some(32)),
    field("delivered", "bool", true, None),
    field(
        "rejected_reason",
        "required_nullable_stable_id",
        true,
        Some(64),
    ),
    // This is decoded u32 payload size, not JSON text or HPTC framing size.
    field(
        "observed_token_positions",
        "required_nullable_u32_array",
        true,
        Some(crate::prompt_delivery_v2::MAX_PROMPT_V2_TOKEN_POSITIONS * 4),
    ),
    field("truncation_observed", "bool", true, None),
    field(
        "legacy_v1_digest",
        "required_nullable_digest32",
        true,
        Some(32),
    ),
];

const TOPOLOGY_V1_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("proposal_digest", "digest32", true, Some(32)),
    field("candidate_id", "stable_id", true, Some(128)),
    field("candidate_digest", "derived_digest32", true, Some(32)),
    field("baseline_generation", "positive_u64", true, None),
    field("candidate_generation", "positive_u64", true, None),
    field("selected_topology_digest", "digest32", true, Some(32)),
    field("evaluation_digest", "digest32", true, Some(32)),
    field("rollback_predecessor_digest", "digest32", true, Some(32)),
    field("changed", "bool", true, None),
    field("deltas", "ordered_topology_delta_array", true, Some(65_536)),
];

const RANDOM_STREAM_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("manifest_id", "stable_id", true, Some(128)),
    field("root_seed_digest", "digest32", true, Some(32)),
    field("algorithm_namespace", "enum_token", true, Some(64)),
    field("episode_id", "stable_id", true, Some(128)),
    field("decision_id", "stable_id", true, Some(128)),
    field("stream_id", "stable_id", true, Some(128)),
    field("counter_start", "u64", true, None),
    field("counter_end_exclusive", "u64", true, None),
    field("generator_id", "enum_token", true, Some(64)),
    field("generator_version", "bounded_text", true, Some(64)),
];

const EXTERNAL_SYSTEM_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("system_id", "stable_id", true, Some(128)),
    field("system_class", "closed_enum", true, Some(64)),
    field("host_identity_digest", "digest32", true, Some(32)),
    field("os_release_digest", "digest32", true, Some(32)),
    field("package_inventory_digest", "digest32", true, Some(32)),
    field("service_graph_digest", "digest32", true, Some(32)),
    field("filesystem_scope_digest", "digest32", true, Some(32)),
    field("identity_map_digest", "digest32", true, Some(32)),
    field("network_surface_digest", "digest32", true, Some(32)),
    field("secret_reference_digest", "digest32", true, Some(32)),
    field("observed_at", "utc_timestamp", true, Some(64)),
    field("authorization_witness", "digest32", true, Some(32)),
];

const SENSOR_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("sensor_id", "stable_id", true, Some(128)),
    field("sensor_class", "closed_enum", true, Some(64)),
    field("hardware_or_adapter_digest", "digest32", true, Some(32)),
    field("calibration_generation", "positive_u64", true, None),
    field("clock_domain", "bounded_text", true, Some(128)),
    field("valid_from", "utc_timestamp", true, Some(64)),
    field("valid_until", "utc_timestamp", true, Some(64)),
    field("uncertainty_profile", "bounded_object", true, Some(256)),
    field("operating_range", "bounded_object", true, Some(192)),
    field("failure_policy", "closed_enum", true, Some(64)),
];

const REGISTERED_NUMERIC_V2_FIELDS: &[ProtocolFieldDescriptorV2] = &[
    field("conversion", "numeric_conversion_receipt_v1", true, None),
    field("registry_generation", "positive_u64", true, None),
    field("registry_digest", "digest32", true, Some(32)),
    field(
        "source_profile_definition_digest",
        "digest32",
        true,
        Some(32),
    ),
    field(
        "target_profile_definition_digest",
        "digest32",
        true,
        Some(32),
    ),
    field(
        "normalization_definition_digest",
        "digest32",
        true,
        Some(32),
    ),
    field("conversion_receipt_digest", "digest32", true, Some(32)),
    field("admission_digest", "derived_digest32", true, Some(32)),
];

pub const PLATFORM_TYPES_PROTOCOL_CATALOG_V2: &[ProtocolDescriptorV2] = &[
    ProtocolDescriptorV2 {
        id: "PromptDeliveryObservationV1",
        version: 1,
        semantic_type_id: "legacy:hepta.prompt-delivery-observation.v1",
        semantic_encoding: "frozen_custom_length_framed_sha256",
        transport_schema: None,
        codec_owner: "runtime.codex/learning.ledger compatibility",
        compatibility: "frozen_read_compatible_no_reinterpretation",
        fields: PROMPT_V1_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "PromptDeliveryObservationV2",
        version: 2,
        semantic_type_id: "platform.types:prompt-delivery-observation-v2",
        semantic_encoding: "HPTC_V1_schema_2",
        transport_schema: Some("schemas/prompt-delivery-observation-v2.schema.json"),
        codec_owner: "platform.wire",
        compatibility: "additive_v2_with_explicit_v1_migration_witness",
        fields: PROMPT_V2_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "RuntimeTopologyCandidateV1",
        version: 1,
        semantic_type_id: "platform.types:runtime-topology-candidate-v1",
        semantic_encoding: "HPTC_V1_schema_1",
        transport_schema: Some("schemas/runtime-topology-candidate-v1.schema.json"),
        codec_owner: "platform.wire",
        compatibility: "v1_frozen_semantics_validated_wrapper_required_at_product_boundary",
        fields: TOPOLOGY_V1_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "RandomStreamManifestV1",
        version: 1,
        semantic_type_id: "platform.types:random-stream-manifest-v1",
        semantic_encoding: "HPTC_V1_schema_1",
        transport_schema: Some("schemas/random-stream-manifest-v1.schema.json"),
        codec_owner: "platform.wire",
        compatibility: "v1_frozen_semantics",
        fields: RANDOM_STREAM_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "ExternalSystemManifestV1",
        version: 1,
        semantic_type_id: "platform.types:external-system-manifest-v1",
        semantic_encoding: "HPTC_V1_schema_1",
        transport_schema: Some("schemas/external-system-manifest-v1.schema.json"),
        codec_owner: "platform.wire",
        compatibility: "v1_frozen_semantics",
        fields: EXTERNAL_SYSTEM_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "SensorCalibrationManifestV1",
        version: 1,
        semantic_type_id: "platform.types:sensor-calibration-manifest-v1",
        semantic_encoding: "HPTC_V1_schema_1",
        transport_schema: Some("schemas/sensor-calibration-manifest-v1.schema.json"),
        codec_owner: "platform.wire",
        compatibility: "v1_frozen_semantics",
        fields: SENSOR_FIELDS,
    },
    ProtocolDescriptorV2 {
        id: "RegisteredNumericConversionReceiptV2",
        version: 2,
        semantic_type_id: "platform.types:numeric-registry-admission-v2",
        semantic_encoding: "HPTC_V1_schema_2",
        transport_schema: None,
        codec_owner: "platform.types/native",
        compatibility: "additive_v2_v1_receipt_remains_readable",
        fields: REGISTERED_NUMERIC_V2_FIELDS,
    },
];

const fn field(
    name: &'static str,
    wire_type: &'static str,
    required: bool,
    maximum_encoded_bytes: Option<usize>,
) -> ProtocolFieldDescriptorV2 {
    ProtocolFieldDescriptorV2 {
        name,
        wire_type,
        required,
        maximum_encoded_bytes,
    }
}
