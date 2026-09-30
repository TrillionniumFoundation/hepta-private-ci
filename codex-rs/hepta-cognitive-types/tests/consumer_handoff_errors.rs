//! Exercise the public codec, binding and final-use handoff, not an unchecked
//! test executor. These fixtures do not authenticate a real product owner.

use std::collections::BTreeSet;
use std::fmt::Debug;

use codex_hepta_cognitive_types::consumer::CanonicalConsumerBindingError;
use codex_hepta_cognitive_types::consumer::CanonicalConsumerBindingV1;
use codex_hepta_cognitive_types::consumer::CanonicalConsumerV1;
use codex_hepta_cognitive_types::consumer::CanonicalMigrationPostureV1;
use codex_hepta_cognitive_types::consumer::CanonicalPayloadKindV1;
use codex_hepta_cognitive_types::consumer::bind_memory_event_consumer_v1;
use codex_hepta_cognitive_types::consumer::bind_recall_packet_consumer_v1;
use codex_hepta_cognitive_types::consumer_adapters::ConsumerConvergenceStateV1;
use codex_hepta_cognitive_types::contract::ContractErrorCodeV1;
use codex_hepta_cognitive_types::contract::ContractViolationV1;
use codex_hepta_cognitive_types::contract::Validated;
use codex_hepta_cognitive_types::hnmf::*;
use codex_hepta_cognitive_types::hnmf_learning::*;
use codex_hepta_cognitive_types::wire::CognitiveContractV1;
use codex_hepta_cognitive_types::wire::encode_wire_v1;

fn must<T, E: Debug>(result: Result<T, E>, context: &str) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("{context}: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>, context: &str) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("{context}: unexpected success: {value:?}"),
    }
}

fn id(value: &str) -> ContractIdV1 {
    must(ContractIdV1::new(value), "valid fixture identity")
}

fn digest(character: char) -> ContractDigestV1 {
    must(
        ContractDigestV1::parse(&std::iter::repeat_n(character, 64).collect::<String>()),
        "valid fixture digest",
    )
}

fn event() -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: id("event:consumer"),
        episode_id: id("episode:consumer"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: id("agent:consumer"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: id("span:consumer"),
            modality: ModalityKindV1::Text,
            asset_sha256: digest('a'),
            range: SpanRangeV1::ByteRange { start: 0, end: 1 },
            preprocessor_manifest_sha256: digest('b'),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["consumer".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: id("source:consumer"),
            source_revision: 1,
            source_sha256: digest('c'),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: digest('d'),
        ndu_state_digest: digest('e'),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    }
}

fn recall() -> RecallPacketV1 {
    RecallPacketV1 {
        cue_digest: digest('1'),
        event_snapshot_digest: digest('2'),
        engram_snapshot_digest: digest('3'),
        selected_events: vec![SelectedEventRefV1 {
            event_id: id("event:consumer"),
            revision: 1,
            event_digest: digest('4'),
        }],
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 1_000_000,
        confidence_ppm: 900_000,
        ood_ppm: 0,
        abstain: None,
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 1,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    }
}

#[test]
fn binding_error_categories_are_exhaustive_and_payload_free() {
    use CanonicalConsumerBindingError as Error;
    use ContractErrorCodeV1 as Code;

    let cases = [
        (
            Error::CanonicalContract("private payload sentinel".to_string()),
            Code::InvalidValue,
            "binding.canonicalPayload",
        ),
        (Error::ZeroDigest, Code::EmptyDigest, "binding"),
        (
            Error::CompatibilityDigestRequired,
            Code::MissingValue,
            "binding.compatibilityPayloadSha256",
        ),
        (
            Error::UnexpectedCompatibilityDigest,
            Code::InvalidValue,
            "binding.compatibilityPayloadSha256",
        ),
        (
            Error::CurrentnessRevalidationRequired,
            Code::MissingValue,
            "binding.currentnessRevalidationRequired",
        ),
        (
            Error::ConsumerNotRegistered {
                consumer: CanonicalConsumerV1::CognitiveRead,
            },
            Code::ContractMismatch,
            "binding.consumer",
        ),
        (
            Error::MigrationPostureNotAuthorized {
                consumer: CanonicalConsumerV1::CognitiveRead,
                posture: CanonicalMigrationPostureV1::Native,
                state: ConsumerConvergenceStateV1::RegisteredPendingCutover,
            },
            Code::StateConflict,
            "binding.migrationPosture",
        ),
        (
            Error::ConsumerPayloadMismatch {
                consumer: CanonicalConsumerV1::CognitiveRead,
                payload: CanonicalPayloadKindV1::RecallPacket,
            },
            Code::ContractMismatch,
            "binding.payloadKind",
        ),
        (
            Error::BindingDigestMismatch,
            Code::DigestMismatch,
            "binding.bindingSha256",
        ),
        (Error::Arithmetic, Code::LimitExceeded, "binding"),
    ];
    for (error, code, path) in cases {
        let violation = error.violation();
        assert_eq!(violation.code, code);
        assert_eq!(violation.field_path, path);
        assert!(!violation.message.contains("private payload sentinel"));
        assert!(violation.message.len() <= 128);
        assert_eq!(ContractViolationV1::from(error), violation);
    }
}

fn reseal(binding: &mut CanonicalConsumerBindingV1) {
    binding.binding_sha256 = must(binding.compute_binding_sha256(), "resealed binding");
}

fn exercise_binding_refusals<T: CognitiveContractV1 + Debug>(
    value: T,
    binding: CanonicalConsumerBindingV1,
) {
    use ContractErrorCodeV1 as Code;

    let expected = must(Validated::new(value), "valid expected projection");
    let wire = must(encode_wire_v1(expected.as_inner()), "canonical input");
    let handoff = must(
        binding.compare_canonical_projection_v1(&expected, &wire),
        "baseline public handoff",
    );
    let mut cases = Vec::new();

    let mut invalid = binding.clone();
    invalid.source_snapshot_sha256 = digest('9');
    cases.push((invalid, Code::DigestMismatch, "binding.bindingSha256"));

    let mut invalid = binding.clone();
    invalid.compatibility_payload_sha256 = None;
    reseal(&mut invalid);
    cases.push((
        invalid,
        Code::MissingValue,
        "binding.compatibilityPayloadSha256",
    ));

    let mut invalid = binding.clone();
    invalid.currentness_revalidation_required = false;
    reseal(&mut invalid);
    cases.push((
        invalid,
        Code::MissingValue,
        "binding.currentnessRevalidationRequired",
    ));

    let mut invalid = binding.clone();
    invalid.payload_kind = match binding.payload_kind {
        CanonicalPayloadKindV1::RecallPacket => CanonicalPayloadKindV1::MemoryEvent,
        _ => CanonicalPayloadKindV1::RecallPacket,
    };
    reseal(&mut invalid);
    cases.push((invalid, Code::ContractMismatch, "binding.payloadKind"));

    let mut invalid = binding.clone();
    invalid.migration_posture = CanonicalMigrationPostureV1::Native;
    reseal(&mut invalid);
    cases.push((
        invalid,
        Code::InvalidValue,
        "binding.compatibilityPayloadSha256",
    ));

    let mut invalid = binding.clone();
    invalid.migration_posture = CanonicalMigrationPostureV1::Native;
    invalid.compatibility_payload_sha256 = None;
    reseal(&mut invalid);
    cases.push((invalid, Code::StateConflict, "binding.migrationPosture"));

    for (invalid, code, path) in cases {
        let before_decode = must_err(
            invalid.compare_canonical_projection_v1(&expected, &wire),
            "invalid binding cannot enter the decoder",
        );
        let final_use = must_err(
            handoff.require_match_for_current_binding(&invalid),
            "an old success cannot validate a new invalid binding",
        );
        for violation in [before_decode, final_use] {
            assert_eq!(violation.code, code);
            assert_eq!(violation.field_path, path);
        }
        assert_eq!(
            must(
                handoff.require_match_for_current_binding(&binding),
                "unchanged baseline remains usable",
            )
            .as_inner(),
            expected.as_inner(),
        );
    }

    let mut changed = binding;
    changed.operation_id = id("operation:different");
    reseal(&mut changed);
    must(changed.validate(), "structurally valid alternative");
    let violation = must_err(
        handoff.require_match_for_current_binding(&changed),
        "resealed operation substitution is still refused",
    );
    assert_eq!(violation.code, Code::StateConflict);
    assert_eq!(violation.field_path, "handoff.currentBinding");
}

fn exercise_wire_refusals<T: CognitiveContractV1 + Debug>(
    value: T,
    binding: CanonicalConsumerBindingV1,
) {
    use ContractErrorCodeV1 as Code;

    let expected = must(Validated::new(value), "valid expected projection");
    let wire = must(encode_wire_v1(expected.as_inner()), "canonical input");
    let text = must(std::str::from_utf8(&wire), "UTF-8 wire").to_owned();
    let baseline = must(
        binding.compare_canonical_projection_v1(&expected, &wire),
        "baseline public comparison",
    );
    must(
        baseline.require_match_for_current_binding(&binding),
        "baseline final-use check",
    );
    let cases = [
        (format!("{text} ").into_bytes(), Code::NonCanonicalEncoding),
        (
            text.replace(T::SCHEMA_ID, "hepta.invalid.schema.v1")
                .into_bytes(),
            Code::SchemaMismatch,
        ),
        (
            text.replace(T::CONTRACT_ID, "UnexpectedContractV1")
                .into_bytes(),
            Code::ContractMismatch,
        ),
        (
            text.replace("\"schemaVersion\":1", "\"schemaVersion\":2")
                .into_bytes(),
            Code::VersionMismatch,
        ),
    ];
    for (changed_wire, code) in cases {
        assert_ne!(changed_wire, wire);
        let violation = must_err(
            binding.compare_canonical_projection_v1(&expected, &changed_wire),
            "changed wire cannot reuse a prior successful payload",
        );
        assert_eq!(violation.code, code);
        let unchanged = must(
            binding.compare_canonical_projection_v1(&expected, &wire),
            "valid bytes still traverse the normal public path",
        );
        must(
            unchanged.require_match_for_current_binding(&binding),
            "unchanged binding still matches",
        );
    }
}

fn each_consumer(
    exercise_events: fn(MemoryEventV1, CanonicalConsumerBindingV1),
    exercise_recalls: fn(RecallPacketV1, CanonicalConsumerBindingV1),
) {
    for consumer in CanonicalConsumerV1::ALL {
        match consumer {
            CanonicalConsumerV1::CognitiveRead
            | CanonicalConsumerV1::CognitiveStore
            | CanonicalConsumerV1::CompactEngine => {
                let value = event();
                let binding = must(
                    bind_memory_event_consumer_v1(
                        id("operation:errors"),
                        consumer,
                        &value,
                        digest('5').digest(),
                        digest('6').digest(),
                        Some(digest('7').digest()),
                        CanonicalMigrationPostureV1::CompatibilityBound,
                    ),
                    "event consumer binding",
                );
                exercise_events(value, binding);
            }
            CanonicalConsumerV1::MemoryRetrieval | CanonicalConsumerV1::IntelligenceControl => {
                let value = recall();
                let binding = must(
                    bind_recall_packet_consumer_v1(
                        id("operation:errors"),
                        consumer,
                        &value,
                        digest('5').digest(),
                        digest('6').digest(),
                        Some(digest('7').digest()),
                        CanonicalMigrationPostureV1::CompatibilityBound,
                    ),
                    "recall consumer binding",
                );
                exercise_recalls(value, binding);
            }
        }
    }
}

#[test]
fn all_five_public_handoffs_preserve_binding_refusal_categories() {
    each_consumer(exercise_binding_refusals, exercise_binding_refusals);
}

#[test]
fn all_five_public_handoffs_reject_wire_drift_without_reusing_success() {
    each_consumer(exercise_wire_refusals, exercise_wire_refusals);
}
