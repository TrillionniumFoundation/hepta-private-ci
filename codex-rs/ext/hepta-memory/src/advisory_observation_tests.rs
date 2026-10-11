use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionDataInit;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::IntuitionCandidate;
use codex_hepta_memory::IntuitionMode;
use codex_hepta_memory::NeuronFeature;
use codex_hepta_memory::NeuronParameter;
use codex_hepta_memory::NeuronPosition;
use codex_hepta_memory::ShadowAdvisoryInput;
use codex_hepta_memory::shadow_advisory_evaluate;

use super::HEPTA_MEMORY_SHADOW_ADVISORY_OBSERVATION_NAMESPACE;
use super::ShadowAdvisoryObservationError;
use super::ShadowAdvisoryObservationInput;
use super::ShadowAdvisoryObservationReason;
use super::observe_shadow_advisory;
use super::observe_shadow_advisory_input;
use super::require_shadow_advisory_observation;
use super::shadow_advisory_turn_observation;

const TURN_ID: &str = "turn-shadow-advisory-1";
const OTHER_TURN_ID: &str = "turn-shadow-advisory-2";

fn host_input(turn_id: &str) -> ShadowAdvisoryObservationInput {
    let state_digest = Sha256Digest::for_bytes(b"host-state:v1");
    let snapshot_digest = Sha256Digest::for_bytes(b"host-kg-snapshot:v1");
    let policy_digest = Sha256Digest::for_bytes(b"host-policy:v1");
    let input = ShadowAdvisoryInput {
        state_digest: state_digest.clone(),
        snapshot_digest: snapshot_digest.clone(),
        policy_digest: policy_digest.clone(),
        authority_epoch: 11,
        neuron: codex_hepta_memory::NeuronProposalInput {
            position: NeuronPosition::MemoryRetrievalRank,
            state_digest,
            policy_digest: policy_digest.clone(),
            authority_epoch: 11,
            sample_count: 12,
            baseline_bps: 7_000,
            features: vec![NeuronFeature::new("host-success", 9_000).expect("feature")],
        },
        neuron_parameter: NeuronParameter::RetrievalWeightBps,
        intuition: codex_hepta_memory::IntuitionShadowInput {
            snapshot_digest,
            schema_digest: codex_hepta_memory::intuition_schema_digest(),
            policy_digest,
            authority_epoch: 11,
            mode: IntuitionMode::SuggestOnly,
            max_risk_bps: 6_000,
            min_confidence_bps: 5_000,
            require_evidence: true,
            candidates: vec![
                IntuitionCandidate::new(
                    "host-candidate",
                    8_000,
                    1_000,
                    vec![IntuitionMode::SuggestOnly],
                    true,
                )
                .expect("candidate"),
            ],
        },
    };
    let receipt = shadow_advisory_evaluate(&input).expect("shadow receipt");
    ShadowAdvisoryObservationInput::new(turn_id, input, receipt)
}

fn seeded_store(input: ShadowAdvisoryObservationInput) -> ExtensionData {
    let mut init = ExtensionDataInit::new();
    init.insert(input);
    ExtensionData::new_with_init(TURN_ID, init)
}

#[test]
fn host_supplied_receipt_becomes_valid_digest_only_observation() {
    let store = seeded_store(host_input(TURN_ID));
    let observation = observe_shadow_advisory(&store).expect("observation");

    assert_eq!(
        observation.reason,
        ShadowAdvisoryObservationReason::Observed
    );
    assert_eq!(
        observation.namespace,
        HEPTA_MEMORY_SHADOW_ADVISORY_OBSERVATION_NAMESPACE
    );
    assert!(observation.is_shadow_only());
    observation.validate().expect("self-validating observation");
    assert_eq!(
        shadow_advisory_turn_observation(&store),
        Some(observation.clone())
    );

    let serialized = serde_json::to_string(&observation).expect("serialize observation");
    assert!(!serialized.contains("host-candidate"));
    assert!(!serialized.contains("host-success"));
    assert!(!serialized.contains(TURN_ID));
    assert!(!serialized.contains("host-kg-snapshot"));
}

#[test]
fn missing_host_input_is_rejected_without_synthesizing_snapshot() {
    let store = ExtensionData::new(TURN_ID);
    let error = require_shadow_advisory_observation(&store).expect_err("missing input");
    assert_eq!(
        error,
        ShadowAdvisoryObservationError::Rejected(ShadowAdvisoryObservationReason::HostInputMissing)
    );
    let observation = shadow_advisory_turn_observation(&store).expect("rejection observation");
    assert_eq!(
        observation.reason,
        ShadowAdvisoryObservationReason::HostInputMissing
    );
    assert!(observation.input_digest.is_none());
    assert!(observation.snapshot_digest.is_none());
    observation.validate().expect("valid rejection envelope");
}

#[test]
fn mismatched_turn_is_rejected_before_any_nested_digest_is_retained() {
    let store = ExtensionData::new(TURN_ID);
    let input = host_input(OTHER_TURN_ID);
    let error = observe_shadow_advisory_input(&store, &input).expect_err("scope mismatch");
    assert_eq!(
        error,
        ShadowAdvisoryObservationError::Rejected(
            ShadowAdvisoryObservationReason::TurnBindingMismatch
        )
    );
    let observation = shadow_advisory_turn_observation(&store).expect("scope rejection");
    assert_eq!(
        observation.reason,
        ShadowAdvisoryObservationReason::TurnBindingMismatch
    );
    assert!(observation.input_digest.is_none());
}

#[test]
fn tampered_receipt_is_rejected_and_never_attached_as_authority() {
    let mut input = host_input(TURN_ID);
    input.receipt.runtime_consumer = true;
    let store = ExtensionData::new(TURN_ID);
    let error = observe_shadow_advisory_input(&store, &input).expect_err("tampered receipt");
    assert_eq!(
        error,
        ShadowAdvisoryObservationError::Rejected(
            ShadowAdvisoryObservationReason::AuthorityBoundary,
        )
    );
    let observation = shadow_advisory_turn_observation(&store).expect("receipt rejection");
    assert_eq!(
        observation.reason,
        ShadowAdvisoryObservationReason::AuthorityBoundary
    );
    assert!(observation.input_digest.is_none());
    assert!(!observation.runtime_consumer);
    assert!(observation.is_shadow_only());
}

#[test]
fn observation_is_idempotent_and_conflicts_are_fail_closed() {
    let input = host_input(TURN_ID);
    let store = ExtensionData::new(TURN_ID);
    let first = observe_shadow_advisory_input(&store, &input).expect("first observation");
    let replay = observe_shadow_advisory_input(&store, &input).expect("exact replay");
    assert_eq!(first, replay);

    let mut different = host_input(TURN_ID);
    different.input.authority_epoch = 12;
    let error = observe_shadow_advisory_input(&store, &different).expect_err("conflict");
    assert_eq!(error, ShadowAdvisoryObservationError::Conflict);
    assert_eq!(shadow_advisory_turn_observation(&store), Some(first));
}

#[test]
fn invalid_nested_input_is_observed_as_a_bounded_rejection() {
    let mut input = host_input(TURN_ID);
    input.input.authority_epoch = 0;
    let store = ExtensionData::new(TURN_ID);
    let error = observe_shadow_advisory_input(&store, &input).expect_err("invalid input");
    assert_eq!(
        error,
        ShadowAdvisoryObservationError::Rejected(ShadowAdvisoryObservationReason::InputRejected)
    );
    let observation = shadow_advisory_turn_observation(&store).expect("input rejection");
    assert_eq!(
        observation.reason,
        ShadowAdvisoryObservationReason::InputRejected
    );
    assert!(
        serde_json::to_string(&observation)
            .expect("serialize rejection")
            .contains("input_rejected")
    );
}

#[test]
fn host_input_type_round_trips_through_extension_data_init() {
    let input = host_input(TURN_ID);
    let mut init = ExtensionDataInit::new();
    assert!(init.insert(input.clone()).is_none());
    let store = ExtensionData::new_with_init(TURN_ID, init.clone());
    assert_eq!(
        store.get::<ShadowAdvisoryObservationInput>().as_deref(),
        Some(&input)
    );
    assert_eq!(
        init.get::<ShadowAdvisoryObservationInput>().as_deref(),
        Some(&input)
    );
}
