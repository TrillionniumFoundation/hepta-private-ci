use super::*;
use crate::durable::canonical_json;
use ed25519_dalek::SigningKey;
use std::collections::BTreeMap;

const PARENT: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const CHILD: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const TOMBSTONE: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const ATTESTATION: &str = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";

fn event(
    recorder: &CellSplitTargetHostEvidenceRecorderV1,
    kind: CellSplitTargetHostEventKindV1,
    sequence: u64,
) -> CellSplitTargetHostEventV1 {
    let payload = &recorder.payload;
    let mut result = CellSplitTargetHostEventV1 {
        sequence,
        event_kind: kind,
        occurred_at_unix_nanos: 1_700_000_000_000_000_000 + sequence as u128,
        split_id: payload.split_id.clone(),
        target_host_id: payload.target_host_id.clone(),
        parent_generation: payload.parent_generation,
        child_generation: payload.child_generation,
        operation_id: format!("operation-{sequence}"),
        artifact_digest: if kind == CellSplitTargetHostEventKindV1::ArtifactLoaded {
            CHILD.to_string()
        } else {
            String::new()
        },
        route_digest: if kind == CellSplitTargetHostEventKindV1::RouteCutover {
            "child-route-receipt".to_string()
        } else {
            String::new()
        },
        predecessor_digest: if matches!(
            kind,
            CellSplitTargetHostEventKindV1::RouteCutover
                | CellSplitTargetHostEventKindV1::RollbackCompleted
                | CellSplitTargetHostEventKindV1::NoResurrectionVerified
        ) {
            "parent-route-fence".to_string()
        } else {
            String::new()
        },
        tombstone_digest: if matches!(
            kind,
            CellSplitTargetHostEventKindV1::TombstoneCommitted
                | CellSplitTargetHostEventKindV1::NoResurrectionVerified
        ) {
            TOMBSTONE.to_string()
        } else {
            String::new()
        },
        fault_injection_digest: if kind == CellSplitTargetHostEventKindV1::PowerLossRecovered {
            ATTESTATION.to_string()
        } else {
            String::new()
        },
        receipt_digest: format!("receipt-{sequence}"),
        resource: None,
        previous_event_digest: payload
            .events
            .last()
            .map_or(ZERO_DIGEST.to_string(), |item| item.event_digest.clone()),
        event_digest: String::new(),
    };
    if kind == CellSplitTargetHostEventKindV1::ResourceMeasurement {
        result.resource = Some(CellSplitTargetResourceSampleV1 {
            hardware: CellSplitTargetHardwareV1::Cpu,
            hardware_model: "test-cpu".to_string(),
            measurement_source: "linux-perf-counter".to_string(),
            hardware_attestation_digest: ATTESTATION.to_string(),
            sample_count: 3,
            latency_micros: 12,
            memory_bytes: 4096,
            communication_bytes: 2048,
            training_micros: 20,
            migration_micros: 8,
        });
    }
    result
}

fn complete_recorder() -> CellSplitTargetHostEvidenceV1 {
    let mut recorder = CellSplitTargetHostEvidenceRecorderV1::new(
        "split.production.1",
        "host.arm64.01",
        "nonce-production-1",
        ATTESTATION,
        7,
        8,
        PARENT,
        CHILD,
    )
    .expect("recorder");
    let kinds = [
        CellSplitTargetHostEventKindV1::ArtifactLoaded,
        CellSplitTargetHostEventKindV1::ResourceMeasurement,
        CellSplitTargetHostEventKindV1::RouteCutover,
        CellSplitTargetHostEventKindV1::RestartRecovered,
        CellSplitTargetHostEventKindV1::PowerLossRecovered,
        CellSplitTargetHostEventKindV1::ResourceMeasurement,
        CellSplitTargetHostEventKindV1::RollbackCompleted,
        CellSplitTargetHostEventKindV1::TombstoneCommitted,
        CellSplitTargetHostEventKindV1::NoResurrectionVerified,
    ];
    for (index, kind) in kinds.into_iter().enumerate() {
        let mut item = event(&recorder, kind, index as u64 + 1);
        if kind == CellSplitTargetHostEventKindV1::ResourceMeasurement && index == 5 {
            item.resource.as_mut().expect("resource").hardware = CellSplitTargetHardwareV1::Gpu;
            item.resource.as_mut().expect("resource").hardware_model = "test-gpu".to_string();
        }
        recorder.append(item).expect("append event");
    }
    recorder.finish().expect("finish evidence")
}

#[test]
fn generation_overflow_is_rejected_before_evidence_recording() {
    let result = CellSplitTargetHostEvidenceRecorderV1::new(
        "split.overflow",
        "host.overflow",
        "nonce-overflow",
        ATTESTATION,
        u64::MAX,
        u64::MAX,
        PARENT,
        CHILD,
    );
    assert!(matches!(
        result,
        Err(CellSplitTargetHostEvidenceErrorV1::Invalid(_))
    ));
}

fn key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

fn policy(host: &SigningKey, observer: &SigningKey) -> CellSplitTargetHostEvidenceTrustPolicyV1 {
    CellSplitTargetHostEvidenceTrustPolicyV1 {
        host_keys: BTreeMap::from([("host-signer".to_string(), host.verifying_key())]),
        observer_keys: BTreeMap::from([("observer-signer".to_string(), observer.verifying_key())]),
    }
}

#[test]
fn trust_policy_json_round_trips_public_keys_without_signing() {
    let host = key(23);
    let observer = key(29);
    let trust = policy(&host, &observer);
    let bytes = trust.to_json_bytes().expect("encode trust policy");
    let decoded = CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(&bytes)
        .expect("decode trust policy");
    assert_eq!(decoded.host_keys, trust.host_keys);
    assert_eq!(decoded.observer_keys, trust.observer_keys);
}

#[test]
fn trust_policy_json_rejects_unknown_fields_and_malformed_keys() {
    let host = key(31);
    let observer = key(37);
    let trust = policy(&host, &observer);
    let mut value: serde_json::Value =
        serde_json::from_slice(&trust.to_json_bytes().expect("encode policy")).expect("value");
    value["unexpected"] = serde_json::Value::Bool(true);
    let bytes = serde_json::to_vec(&value).expect("tampered policy");
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(&bytes).is_err());

    let mut malformed: CellSplitTargetHostEvidenceTrustPolicyFileV1 =
        serde_json::from_slice(&trust.to_json_bytes().expect("encode policy"))
            .expect("policy file");
    malformed
        .host_keys
        .insert("bad-host".to_string(), BASE64.encode([0_u8; 31]));
    let bytes = serde_json::to_vec(&malformed).expect("malformed policy");
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(&bytes).is_err());
}

#[test]
fn signed_production_evidence_replays_and_measures_cpu_and_gpu() {
    let payload = complete_recorder();
    let host = key(3);
    let observer = key(7);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("sign");
    let bytes = canonical_json(&envelope).expect("canonical envelope");
    let receipt = verify_cell_split_target_host_evidence_json(&bytes, &policy(&host, &observer))
        .expect("production gate");
    let adapter = CellSplitTargetHostEvidenceAdapterV1::new(policy(&host, &observer));
    let adapter_receipt = adapter.ingest_json(&bytes).expect("adapter ingest");
    assert_eq!(adapter_receipt, receipt);
    assert!(receipt.production_gate_passed);
    assert_eq!(receipt.event_count, 9);
    assert_eq!(receipt.resource_sample_count, 2);
    assert_eq!(receipt.hardware.len(), 2);
    assert!(!receipt.evidence_digest.is_empty());
}

#[test]
fn signed_production_evidence_store_reopens_only_after_verified_atomic_write() {
    let payload = complete_recorder();
    let host = key(37);
    let observer = key(41);
    let trust = policy(&host, &observer);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("sign");
    let directory_guard = tempfile::tempdir().expect("tempdir");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            directory_guard.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("private tempdir");
    }
    let directory = directory_guard
        .path()
        .canonicalize()
        .expect("canonical tempdir");
    let path = directory.join("target-host-evidence.json");
    let stored = CellSplitTargetHostEvidenceStoreV1::persist(&path, &envelope, &trust)
        .expect("durably store verified evidence");
    let (reopened, replayed) =
        CellSplitTargetHostEvidenceStoreV1::reopen(&path, &trust).expect("reopen evidence");
    assert_eq!(reopened, envelope);
    assert_eq!(replayed, stored);

    let mut tampered = std::fs::read(&path).expect("read stored evidence");
    tampered[0] ^= 1;
    std::fs::write(&path, tampered).expect("tamper evidence");
    assert!(CellSplitTargetHostEvidenceStoreV1::reopen(&path, &trust).is_err());
}

#[test]
fn source_simulation_is_rejected_even_when_signed() {
    let mut payload = complete_recorder();
    payload.origin = SIMULATION_ORIGIN.to_string();
    let host = key(11);
    let observer = key(13);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect_err("simulation must not be signable");
    assert!(envelope.to_string().contains("production payload"));
}

#[test]
fn tampered_json_fails_hash_chain_before_signature_acceptance() {
    let payload = complete_recorder();
    let host = key(17);
    let observer = key(19);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("sign");
    let mut value = serde_json::to_value(envelope).expect("value");
    value["payload"]["events"][0]["artifactDigest"] =
        serde_json::Value::String(CHILD.replace('b', "e"));
    let bytes = serde_json::to_vec(&value).expect("tampered json");
    assert!(
        verify_cell_split_target_host_evidence_json(&bytes, &policy(&host, &observer)).is_err()
    );
}

#[test]
fn missing_observer_and_simulated_resource_are_rejected() {
    let payload = complete_recorder();
    let host = key(23);
    let envelope = payload
        .sign("host-signer", &host, std::iter::empty())
        .expect("host-only envelope can be constructed");
    let empty_policy = CellSplitTargetHostEvidenceTrustPolicyV1 {
        host_keys: BTreeMap::from([("host-signer".to_string(), host.verifying_key())]),
        observer_keys: BTreeMap::new(),
    };
    let error = verify_cell_split_target_host_evidence(&envelope, &empty_policy)
        .expect_err("observer required");
    assert!(error.to_string().contains("observer"));
}

#[test]
fn route_restart_power_loss_rollback_tombstone_and_no_resurrection_are_required() {
    let payload = complete_recorder();
    assert!(
        payload
            .events
            .iter()
            .any(|event| event.event_kind == CellSplitTargetHostEventKindV1::PowerLossRecovered)
    );
    let host = key(29);
    let observer = key(31);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("sign");
    let receipt = verify_cell_split_target_host_evidence(&envelope, &policy(&host, &observer))
        .expect("all lifecycle witnesses");
    assert_eq!(receipt.target_host_id, "host.arm64.01");
}

#[test]
fn recorder_exposes_next_event_context_for_external_host_adapters() {
    let mut recorder = CellSplitTargetHostEvidenceRecorderV1::new(
        "split.production.context",
        "host.arm64.context",
        "nonce-context",
        ATTESTATION,
        7,
        8,
        PARENT,
        CHILD,
    )
    .expect("recorder");
    assert_eq!(recorder.event_count(), 0);
    let (sequence, previous) = recorder.next_event_context();
    assert_eq!(sequence, 1);
    assert_eq!(previous, ZERO_DIGEST);

    let mut first = event(
        &recorder,
        CellSplitTargetHostEventKindV1::ArtifactLoaded,
        sequence,
    );
    first.previous_event_digest = previous;
    recorder.append(first).expect("first event");

    assert_eq!(recorder.event_count(), 1);
    let (next_sequence, next_previous) = recorder.next_event_context();
    assert_eq!(next_sequence, 2);
    assert_ne!(next_previous, ZERO_DIGEST);
}
