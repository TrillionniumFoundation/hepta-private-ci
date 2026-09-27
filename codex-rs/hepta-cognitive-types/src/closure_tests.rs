use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use proptest::prelude::*;
use serde_json::Value;

use crate::MemoryKind;
use crate::MemoryRecord;
use crate::RecordState;
use crate::contract::Validated;
use crate::handoff::CanonicalHandoffV1;
use crate::handoff::ConsumerHandoffContextV1;
use crate::handoff::ShadowParityV1;
use crate::hnmf::*;
use crate::hnmf_learning::*;
use crate::lane_c::*;
use crate::transitions::*;
use crate::wire::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("../tests/fixtures/closure_vectors.json"))
        .unwrap_or_else(|error| panic!("corpus: {error}"))
}

fn payload(name: &str) -> Value {
    vectors()["vectors"].as_array().unwrap_or_else(|| panic!("missing fixture value")).iter()
        .find(|row| row["name"] == name).unwrap_or_else(|| panic!("missing fixture row"))["payload"].clone()
}

fn decode<T: CognitiveContractV1>(value: Value) -> T {
    serde_json::from_value(value).unwrap_or_else(|error| panic!("fixture: {error}"))
}

fn canonical<T: CognitiveContractV1>(value: Value) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "contract": T::CONTRACT_ID, "schema": T::SCHEMA_ID,
        "schemaVersion": COGNITIVE_WIRE_VERSION_V1, "payload": value,
    })).unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

fn check_vector<T: CognitiveContractV1 + std::fmt::Debug>(row: &Value) {
    let raw: T = decode(row["payload"].clone());
    let value = Validated::new(raw.clone()).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    let encoded = value.encode_wire().unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    assert_eq!(encoded, canonical::<T>(row["payload"].clone()));
    assert_eq!(decode_validated_wire_v1::<T>(&encoded).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), value);
    assert_eq!(canonical_contract_digest_v1(&raw).unwrap_or_else(|error| panic!("fixture failed: {error:?}")).to_string(), row["legacyDigest"]);
    assert_eq!(value.bound_digest().unwrap_or_else(|error| panic!("fixture failed: {error:?}")).to_string(), row["boundDigest"]);
    let mut spaced = encoded.clone();
    spaced.push(b' ');
    assert!(decode_wire_v1::<T>(&spaced).is_err());
}

#[test]
fn all_registered_contracts_and_full_u64_match_shared_corpus() {
    for row in vectors()["vectors"].as_array().unwrap_or_else(|| panic!("missing fixture value")) {
        match row["contract"].as_str().unwrap_or_else(|| panic!("missing fixture value")) {
            "ModalitySpanRefV1" => check_vector::<ModalitySpanRefV1>(row),
            "MemoryEventV1" => check_vector::<MemoryEventV1>(row),
            "CrossModalBindingV1" => check_vector::<CrossModalBindingV1>(row),
            "EngramNodeV1" => check_vector::<EngramNodeV1>(row),
            "SynapseV1" => check_vector::<SynapseV1>(row),
            "MemoryCueV1" => check_vector::<MemoryCueV1>(row),
            "RecallPacketV1" => check_vector::<RecallPacketV1>(row),
            "OutcomeSignalV1" => check_vector::<OutcomeSignalV1>(row),
            "ReplaySelectionReceiptV1" => check_vector::<ReplaySelectionReceiptV1>(row),
            "PlasticityBatchV1" => check_vector::<PlasticityBatchV1>(row),
            "TopologyProposalV1" => check_vector::<TopologyProposalV1>(row),
            "ForgetPropagationReceiptV1" => check_vector::<ForgetPropagationReceiptV1>(row),
            unknown => panic!("unregistered corpus type {unknown}"),
        }
    }
}

#[test]
fn same_logical_identity_with_different_payload_is_rejected() {
    let mut event = payload("MemoryEventV1");
    let mut duplicate = event["provenance"][0].clone();
    duplicate["sourceSha256"] = Value::String("d".repeat(64));
    event["provenance"].as_array_mut().unwrap_or_else(|| panic!("missing fixture value")).push(duplicate);
    assert!(decode_wire_v1::<MemoryEventV1>(&canonical::<MemoryEventV1>(event)).is_err());

    let mut recall = payload("RecallPacketV1");
    let mut duplicate = recall["selectedEvents"][0].clone();
    duplicate["eventDigest"] = Value::String("9".repeat(64));
    recall["selectedEvents"].as_array_mut().unwrap_or_else(|| panic!("missing fixture value")).push(duplicate);
    recall["resourceReceipt"]["candidateEventCount"] = Value::from(2);
    assert!(Validated::new(decode::<RecallPacketV1>(recall)).is_err());

    let mut recall = payload("RecallPacketV1");
    let mut duplicate = recall["activeNodes"][0].clone();
    duplicate["activationPpm"] = Value::from(900_000);
    recall["activeNodes"].as_array_mut().unwrap_or_else(|| panic!("missing fixture value")).push(duplicate);
    recall["resourceReceipt"]["nodeCount"] = Value::from(2);
    recall["resourceReceipt"]["activeNodeCount"] = Value::from(2);
    assert!(Validated::new(decode::<RecallPacketV1>(recall)).is_err());

    let mut topology = payload("TopologyProposalV1");
    let mut duplicate = topology["typedNodesEdges"]["nodes"][0].clone();
    duplicate["label"] = Value::String("zz-duplicate-label".to_string());
    topology["typedNodesEdges"]["nodes"].as_array_mut().unwrap_or_else(|| panic!("missing fixture value")).push(duplicate);
    topology["resourceDelta"]["nodeDelta"] = Value::from(2);
    assert!(Validated::new(decode::<TopologyProposalV1>(topology)).is_err());
}

#[test]
fn byte_preflight_counts_escaped_utf8_without_collecting_payload() {
    let value = "\u{0001}".repeat(100);
    // JSON emits quotes plus six bytes for each escaped control scalar.
    assert!(crate::wire_semantics::validate_serialized_bound(&value, 602).is_ok());
    assert!(crate::wire_semantics::validate_serialized_bound(&value, 601).is_err());
    assert!(crate::wire_semantics::validate_serialized_bound(&"é", 4).is_ok());
    assert!(crate::wire_semantics::validate_serialized_bound(&"é", 3).is_err());
}

fn id(value: &str) -> StableId { StableId::new(value).unwrap_or_else(|error| panic!("fixture failed: {error:?}")) }
fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }

fn snapshot(frontier: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:closure"), purpose_id: id("purpose:closure"),
        memory_ledger_frontier: frontier, knowledge_fact_frontier: 1,
        tombstone_frontier: 0, source_ledger_frontier: 1,
        knowledge_graph_generation: Generation::new(1).unwrap_or_else(|error| panic!("fixture failed: {error:?}")),
        compact_checkpoint_generation: Generation::new(1).unwrap_or_else(|error| panic!("fixture failed: {error:?}")),
        prompt_registry_revision: Revision::new(1).unwrap_or_else(|error| panic!("fixture failed: {error:?}")),
        retrieval_profile_digest: digest("retrieval"), encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 1, model_digest: digest("model"), tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"), tool_schema_digest: digest("tools"),
    }).unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

#[test]
fn write_transition_rejects_zero_advance_profile_substitution_and_scope_change() {
    let intent = MemoryWriteIntentV1::new(id("intent:1"), digest("candidate"), snapshot(1), digest("fence"), digest("auth")).expect("intent");
    for (mut observed, should_pass) in [(snapshot(1), false), (snapshot(2), true)] {
        let receipt = MemoryWriteReceiptV1::committed(&intent, observed.clone(), id("record:1"), digest("record"), observed.vector.memory_ledger_frontier, MemoryWriteDisposition::Inserted);
        assert_eq!(receipt.is_ok(), should_pass);
        if let Ok(receipt) = receipt {
            validate_write_transition_v1(&intent, &receipt).expect("validated transition");
        }
        observed.vector.scope_id = id("scope:other");
        observed.vector_digest = observed.vector.digest();
        assert!(MemoryWriteReceiptV1::committed(&intent, observed.clone(), id("record:1"), digest("record"), observed.vector.memory_ledger_frontier, MemoryWriteDisposition::Inserted).is_err());
    }
    let mut observed = snapshot(2);
    observed.vector.tokenizer_digest = digest("substituted-tokenizer");
    observed.vector_digest = observed.vector.digest();
    assert!(MemoryWriteReceiptV1::committed(&intent, observed, id("record:1"), digest("record"), 2, MemoryWriteDisposition::Inserted).is_err());
}

#[test]
fn stale_future_snapshot_can_be_rejected_without_claiming_a_commit() {
    let intent = MemoryWriteIntentV1::new(id("intent:future"), digest("candidate"), snapshot(9), digest("fence"), digest("auth")).expect("intent");
    let receipt = MemoryWriteReceiptV1::rejected(&intent, snapshot(1), MemoryWriteRejectionCodeV1::SnapshotStale, digest("rejection-evidence")).expect("rejection is an observation");
    validate_write_transition_v1(&intent, &receipt).expect("no committed transition claimed");
    assert!(receipt.record_id().is_none());
}

fn handoff_context() -> ConsumerHandoffContextV1 {
    ConsumerHandoffContextV1 {
        consumer: "cognitive.read".to_string(), operation_id: id("operation:1"),
        principal_id: id("principal:1"), snapshot: snapshot(1), source_digest: digest("source"),
        legacy_digest: digest("legacy"), authorization_digest: digest("auth"), owner_evidence_digest: digest("owner"),
    }
}

#[test]
fn shadow_parity_is_computed_and_operation_bound_not_a_supplied_boolean() {
    let event = Validated::new(decode::<MemoryEventV1>(payload("MemoryEventV1"))).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    let bytes = event.encode_wire().unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    let original = CanonicalHandoffV1::compare(Validated::new(handoff_context()).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), &event, &bytes).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    assert_eq!(original.parity(), ShadowParityV1::Matched);
    assert_eq!(original.require_match().unwrap_or_else(|error| panic!("fixture failed: {error:?}")), &event);
    let mut context = handoff_context();
    context.operation_id = id("operation:2");
    let other = CanonicalHandoffV1::compare(Validated::new(context).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), &event, &bytes).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    assert_ne!(original.receipt_digest(), other.receipt_digest());
    let mut different = payload("MemoryEventV1");
    different["semanticKeys"] = serde_json::json!(["different"]);
    let mismatched = CanonicalHandoffV1::compare(Validated::new(handoff_context()).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), &event, &canonical::<MemoryEventV1>(different)).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
    assert_eq!(mismatched.parity(), ShadowParityV1::Mismatch);
    assert!(mismatched.require_match().is_err());
    let mut bad = payload("MemoryEventV1");
    bad["unexpected"] = Value::Bool(true);
    assert!(CanonicalHandoffV1::compare(Validated::new(handoff_context()).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), &event, &canonical::<MemoryEventV1>(bad)).is_err());
}

proptest! {
    #[test]
    fn full_u64_cue_wire_roundtrip(now in 1u64..=u64::MAX) {
        let mut value = payload("MemoryCueV1");
        value["nowUnixMs"] = Value::from(now);
        let cue = Validated::new(decode::<MemoryCueV1>(value)).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
        let bytes = cue.encode_wire().unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
        prop_assert_eq!(decode_validated_wire_v1::<MemoryCueV1>(&bytes).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), cue);
    }

    #[test]
    fn revision_successor_never_accepts_a_gap(gap in 2u64..1_000) {
        let first = Validated::new(MemoryRecord {
            record_id: id("record:1"), revision: Revision::new(1).unwrap_or_else(|error| panic!("fixture failed: {error:?}")), kind: MemoryKind::Fact,
            content_digest: digest("first"), predecessor_digest: None, citations: Vec::new(), state: RecordState::Live,
        }).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
        let mut next = first.as_inner().clone();
        next.revision = Revision::new(2).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
        next.predecessor_digest = Some(first.checked_record_digest());
        prop_assert!(validate_record_transition_v1(&first, &Validated::new(next.clone()).unwrap_or_else(|error| panic!("fixture failed: {error:?}"))).is_ok());
        next.revision = Revision::new(1 + gap).unwrap_or_else(|error| panic!("fixture failed: {error:?}"));
        prop_assert!(validate_record_transition_v1(&first, &Validated::new(next).unwrap_or_else(|error| panic!("fixture failed: {error:?}"))).is_err());
    }
}
