//! Proposed opt-in encoding qualification only. No store, gateway or runtime call.
//! Includes the exact unregistered accounting source without exporting a pool/API.

#[path = "../../hepta-automation/src/retrieval_choice_qualification/encoding.rs"]
mod encoding;

use codex_hepta_agent_protocol::CognitiveContextItem;
use codex_hepta_agent_protocol::CognitiveContextPlan;
use codex_hepta_agent_protocol::CognitiveContextSnapshot;
use encoding::EncodingError;
use encoding::FieldValue;
use encoding::RetainedBudget;
use encoding::check_observation;
use encoding::encode_record;
use serde::Deserialize;
use serde::Serialize;

// Candidate fixture envelope from the reviewed plan; this does NOT replace or
// duplicate the producer-owned CognitiveContextSnapshot/Item/Plan definitions.
#[derive(Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum FixtureObservation {
    Retrieved {
        schema_version: u32,
        owner: String,
        run_id: String,
        activation_id: String,
        choice_digest: String,
        claim_digest: String,
        attempt: u32,
        body_generation: u64,
        context_digest: String,
        producer_contract: String,
        producer_canonical_bytes: Vec<u8>,
        producer_digest: String,
    },
}

fn synthetic_snapshot(content: &str) -> CognitiveContextSnapshot {
    CognitiveContextSnapshot {
        snapshot_digest: "a".repeat(64),
        read_digest: "b".repeat(64),
        omitted_records: 0,
        items: vec![CognitiveContextItem {
            memory_id: "00000000-0000-4000-8000-000000000119:full-memory-identifier".to_owned(),
            revision: 1,
            content: content.to_owned(),
            content_sha256: "c".repeat(64),
        }],
        plan: Some(CognitiveContextPlan {
            evaluated_context_digest: "d".repeat(64),
            plan_receipt_digest: "e".repeat(64),
            read_allowed: true,
        }),
    }
}

fn envelope(snapshot: &CognitiveContextSnapshot) -> Result<FixtureObservation, serde_json::Error> {
    Ok(FixtureObservation::Retrieved {
        schema_version: 1,
        owner: "00000000-0000-4000-8000-000000000119".to_owned(),
        run_id: "read0001".to_owned(),
        activation_id: "act00001".to_owned(),
        choice_digest: "f".repeat(64),
        claim_digest: "a".repeat(64),
        attempt: 1,
        body_generation: 1,
        context_digest: "b".repeat(64),
        producer_contract: "cognitive_context_snapshot_v1".to_owned(),
        producer_canonical_bytes: serde_json::to_vec(snapshot)?,
        producer_digest: "c".repeat(64),
    })
}

#[test]
fn actual_producer_types_roundtrip_without_shortening_ids() {
    let snapshot = synthetic_snapshot("synthetic");
    let observation = envelope(&snapshot).unwrap();
    let bytes = serde_json::to_vec(&observation).unwrap();
    let decoded: FixtureObservation = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(decoded, observation);
    let FixtureObservation::Retrieved {
        producer_canonical_bytes,
        ..
    } = decoded;
    let restored: CognitiveContextSnapshot =
        serde_json::from_slice(&producer_canonical_bytes).unwrap();
    assert_eq!(restored, snapshot);
    assert_eq!(
        serde_json::to_vec(&restored).unwrap(),
        producer_canonical_bytes
    );
    // Log actual serializer lengths; this test intentionally fails if even the
    // selected minimal fixture cannot fit. Do not revise the limit to make it pass.
    eprintln!(
        "producer_bytes={} observation_bytes={}",
        producer_canonical_bytes.len(),
        bytes.len()
    );
    assert_eq!(check_observation(&bytes), Ok(()));
    let record =
        encode_record(&[("observation_canonical_bytes", FieldValue::Blob(&bytes))]).unwrap();
    let mut budget = RetainedBudget::default();
    budget.charge(&record).unwrap();
    assert_eq!(budget.used(), record.bytes().len());
}

#[test]
fn real_serde_expansion_counts_toward_complete_observation_limit() {
    let snapshot = synthetic_snapshot(&"\"\\证据".repeat(512));
    let observation = envelope(&snapshot).unwrap();
    let bytes = serde_json::to_vec(&observation).unwrap();
    assert_eq!(
        check_observation(&bytes),
        Err(EncodingError::ObservationLimit)
    );
    let decoded: FixtureObservation = serde_json::from_slice(&bytes).unwrap();
    let FixtureObservation::Retrieved {
        producer_canonical_bytes,
        ..
    } = decoded;
    let restored: CognitiveContextSnapshot =
        serde_json::from_slice(&producer_canonical_bytes).unwrap();
    assert_eq!(restored, snapshot);
}
