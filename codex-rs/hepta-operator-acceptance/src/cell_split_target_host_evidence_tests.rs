use super::*;
use crate::durable::canonical_json;
use ed25519_dalek::SigningKey;
use std::collections::BTreeMap;

const PARENT: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const CHILD: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const TOMBSTONE: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const ATTESTATION: &str = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
const CHILD_ROUTE: &str = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const PARENT_ROUTE: &str = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";

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
        artifact_digest: CHILD.to_string(),
        route_digest: match kind {
            CellSplitTargetHostEventKindV1::RouteCutover
            | CellSplitTargetHostEventKindV1::RestartRecovered
            | CellSplitTargetHostEventKindV1::PowerLossRecovered => {
                CHILD_ROUTE.to_string()
            }
            CellSplitTargetHostEventKindV1::RollbackCompleted
            | CellSplitTargetHostEventKindV1::TombstoneCommitted
            | CellSplitTargetHostEventKindV1::NoResurrectionVerified => {
                PARENT_ROUTE.to_string()
            }
            _ => String::new(),
        },
        predecessor_digest: match kind {
            CellSplitTargetHostEventKindV1::RouteCutover => PARENT_ROUTE.to_string(),
            CellSplitTargetHostEventKindV1::RollbackCompleted => {
                CHILD_ROUTE.to_string()
            }
            CellSplitTargetHostEventKindV1::TombstoneCommitted
            | CellSplitTargetHostEventKindV1::NoResurrectionVerified => {
                PARENT_ROUTE.to_string()
            }
            _ => String::new(),
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
        receipt_digest: crate::durable::sha256(format!("receipt-{sequence}").as_bytes()),
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
fn target_host_trust_file_requires_out_of_band_exact_sha256_pin() {
    let trust = policy(&key(71), &key(73));
    let bytes = trust.to_json_bytes().expect("canonical trust policy");
    let digest = crate::durable::sha256(&bytes);
    let directory = tempfile::tempdir().expect("private directory");
    let path = directory.path().join("target-host-trust-policy.json");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(
            directory.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("private directory");
    }
    std::fs::write(&path, &bytes).expect("policy");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .expect("private policy");
    }
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_file(&path).is_err());
    let load_pinned = |pin: &str| {
        CellSplitTargetHostEvidenceTrustPolicyV1::from_json_file_pinned(&path, pin)
    };
    assert!(load_pinned(&"aa".repeat(32)).is_err());
    assert!(load_pinned(&digest.to_uppercase()).is_err());
    let pinned = load_pinned(&digest).expect("independent policy pin");
    assert_eq!(pinned.host_keys, trust.host_keys);
    assert_eq!(pinned.observer_keys, trust.observer_keys);

    let substituted = policy(&key(79), &key(83))
        .to_json_bytes()
        .expect("valid alternate policy");
    std::fs::write(&path, substituted).expect("out-of-band substitution");
    assert!(
        load_pinned(&digest).is_err(),
        "a different valid trust root is not the externally pinned trust root",
    );
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
fn host_observer_keys_must_be_independent_and_signer_aliases_unique() {
    let host = key(41);
    let observer = key(43);
    let shared = policy(&host, &host);
    assert!(shared.to_json_bytes().is_err());
    let mut duplicate = policy(&host, &observer);
    duplicate
        .observer_keys
        .insert("observer-alias".to_string(), observer.verifying_key());
    assert!(duplicate.to_json_bytes().is_err());

    let mut file = CellSplitTargetHostEvidenceTrustPolicyFileV1 {
        schema: CELL_SPLIT_TARGET_HOST_TRUST_POLICY_SCHEMA_V1.to_string(),
        schema_version: 1,
        host_keys: BTreeMap::from([(
            "host-signer".to_string(),
            BASE64.encode(host.verifying_key().to_bytes()),
        )]),
        observer_keys: BTreeMap::from([(
            "observer-signer".to_string(),
            BASE64.encode(observer.verifying_key().to_bytes()),
        )]),
    };
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(
        &canonical_json(&file).expect("independent canonical keys"),
    )
    .is_ok());
    file.observer_keys.insert(
        "observer-alias".to_string(),
        BASE64.encode(observer.verifying_key().to_bytes()),
    );
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(
        &canonical_json(&file).expect("duplicate observer key"),
    )
    .is_err());
    file.observer_keys.clear();
    file.observer_keys.insert(
        "observer-signer".to_string(),
        BASE64.encode(host.verifying_key().to_bytes()),
    );
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(
        &canonical_json(&file).expect("shared host and observer key"),
    )
    .is_err());
    file.observer_keys.insert(
        "observer-signer".to_string(),
        BASE64.encode([0_u8; 32]),
    );
    assert!(CellSplitTargetHostEvidenceTrustPolicyV1::from_json_bytes(
        &canonical_json(&file).expect("invalid or weak observer key"),
    )
    .is_err());
}

#[test]
fn target_host_gate_rejects_zero_and_noncanonical_digests() {
    let mut zero = complete_recorder();
    zero.target_host_attestation_digest = ZERO_DIGEST.to_string();
    assert!(replay_payload(&zero).is_err());

    let mut noncanonical = complete_recorder();
    noncanonical.child_artifact_digest = CHILD.to_uppercase();
    assert!(replay_payload(&noncanonical).is_err());
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
fn signed_production_evidence_store_is_create_only_idempotent_and_reopens_original() {
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

    // Identical original evidence is safe to replay, but no different signed
    // report may reuse its durable path. This is an anti-overwrite guarantee,
    // not an external anti-rollback witness for whole-directory restoration.
    let original_bytes = std::fs::read(&path).expect("original durable evidence");
    assert_eq!(
        CellSplitTargetHostEvidenceStoreV1::persist(&path, &envelope, &trust)
            .expect("idempotent exact original bytes"),
        stored,
    );
    assert_eq!(
        std::fs::read(&path).expect("replayed durable bytes"),
        original_bytes,
    );

    let second_observer = key(43);
    let mut rotated_trust = trust.clone();
    rotated_trust.observer_keys.insert(
        "observer-secondary".to_string(),
        second_observer.verifying_key(),
    );
    let different_signed_history = payload
        .sign(
            "host-signer",
            &host,
            [("observer-secondary".to_string(), second_observer)],
        )
        .expect("independently signed alternate history");
    assert!(
        verify_cell_split_target_host_evidence(&different_signed_history, &rotated_trust)
            .is_ok(),
        "both histories are individually valid but cannot share one witness path",
    );
    assert!(
        CellSplitTargetHostEvidenceStoreV1::persist(
            &path,
            &different_signed_history,
            &rotated_trust,
        )
        .is_err(),
        "another valid signature is not authority to overwrite original evidence",
    );
    assert_eq!(
        std::fs::read(&path).expect("original must survive rejected overwrite"),
        original_bytes,
    );
    assert_eq!(
        CellSplitTargetHostEvidenceStoreV1::reopen(&path, &trust)
            .expect("original history remains verifiable")
            .0,
        envelope,
    );

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


/// A signed host lifecycle report and a four-signer coordinator transcript
/// may each verify independently while referring to unrelated operations.
/// The Observer must sign their exact pairing and confirm every live owner.
fn signed_owner_transcript_for_host(
    payload: &CellSplitTargetHostEvidenceV1,
) -> (
    crate::CellSplitExecutionTranscriptV1,
    crate::CellSplitOwnerTrustV1,
) {
    use ed25519_dalek::Signer as _;

    let plan = crate::CellSplitExecutionPlanV1 {
        split_id: payload.split_id.clone(),
        scope_digest: "11".repeat(32),
        parent_generation: payload.parent_generation,
        child_generation: payload.child_generation,
        parent_artifact_digest: payload.parent_artifact_digest.clone(),
        child_artifact_digest: payload.child_artifact_digest.clone(),
        ndu_snapshot_digest: "22".repeat(32),
        route_fence_digest: "33".repeat(32),
        owner_ids: [
            "independent-artifact-owner".into(),
            "independent-migration-owner".into(),
            "independent-cns-owner".into(),
            "independent-supervisor-owner".into(),
        ],
    };
    let keys = [51_u8, 52, 53, 54].map(key);
    let trusted = crate::CellSplitOwnerTrustV1::new(
        &plan,
        std::array::from_fn(|index| keys[index].verifying_key()),
    ).expect("four original owners are distinct");
    let plan_digest = plan.digest().expect("frozen plan");
    let mut predecessor = plan_digest.clone();
    let mut receipts = Vec::new();
    for (index, step) in [
        crate::CellSplitExecutionStepV1::ArtifactCas,
        crate::CellSplitExecutionStepV1::ChildStateMigration,
        crate::CellSplitExecutionStepV1::CnsRouteCutover,
        crate::CellSplitExecutionStepV1::SupervisorGenerationFence,
    ].into_iter().enumerate() {
        let idempotency_key = crate::durable::sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                plan_digest, step.index(), predecessor,
            ).as_bytes(),
        );
        let intent = crate::CellSplitExecutionIntentV1 {
            schema: "hepta.learning.cell-split.execution-owner.v1".into(),
            plan_digest: plan_digest.clone(),
            step,
            owner_id: plan.owner_ids[index].clone(),
            idempotency_key,
            previous_receipt_digest: predecessor.clone(),
        };
        let owner_bytes = match index {
            #[cfg(unix)]
            2 => {
                // Independent CNS runtime original, bound to the exact host
                // route before the outer CNS effect signer seals its receipt.
                let mut original = crate::CellSplitCnsRuntimeCommitV1 {
                    idempotency_key: intent.idempotency_key.clone(),
                    cns_id: "cns.fixture".to_string(),
                    predecessor_route_digest: PARENT_ROUTE.to_string(),
                    successor_route_digest: CHILD_ROUTE.to_string(),
                    predecessor_generation: plan.parent_generation,
                    successor_generation: plan.child_generation,
                    authority_epoch: 7,
                    committed_sequence: 3,
                    original_runtime_receipt_bytes: Vec::new(),
                    original_runtime_signature_bytes: Vec::new(),
                };
                original.original_runtime_receipt_bytes =
                    crate::CellSplitCnsRuntimeAttestationV1::for_commit(
                        &plan, &original,
                    )
                    .canonical_bytes()
                    .expect("typed original CNS runtime");
                original.original_runtime_signature_bytes = key(71)
                    .sign(&original.original_runtime_receipt_bytes)
                    .to_bytes()
                    .to_vec();
                canonical_json(&original).expect("original signed CNS cutover")
            }
            #[cfg(unix)]
            3 => {
                // The Supervisor original journal is signed with a *distinct*
                // key and a domain-separated payload, not the outer owner key.
                let mut checkpoint = serde_json::json!({
                    "schemaVersion": 1,
                    "operationId": plan.split_id,
                    "domainId": "scope.fixture",
                    "sourceWriter": "cell.parent",
                    "targetWriter": "cell.child",
                    "oldGeneration": plan.parent_generation,
                    "newGeneration": plan.child_generation,
                    "authorityEpoch": 7,
                    "migrationPlanDigest": "a1".repeat(32),
                    "schemaDigest": "a2".repeat(32),
                    "rollbackPredecessorDigest": "a3".repeat(32),
                    "revision": 10,
                    "phase": "retired",
                    "outboxWatermark": 42,
                    "unknownEffectCount": 0,
                    "evidenceDigest": "a4".repeat(32),
                    "previousReceiptDigest": "a5".repeat(32),
                    "receiptDigest": "00".repeat(32),
                });
                let decode = |value: serde_json::Value| {
                    serde_json::from_value::<crate::cell_split_observer_join::OriginalSupervisorCheckpointV1>(
                        value,
                    )
                    .expect("complete durable handoff schema")
                };
                let digest = decode(checkpoint.clone())
                    .content_digest_v1()
                    .expect("journal digest");
                checkpoint["receiptDigest"] = serde_json::json!(digest);
                // The actual Supervisor serializes its ordered persisted
                // checkpoint struct, not a sorted generic JSON Value.
                let checkpoint_bytes = serde_json::to_vec(&decode(checkpoint))
                    .expect("original Supervisor journal checkpoint");
                let mut signing_bytes =
                    b"hepta.supervisor.cell-split.original-journal.v1\0".to_vec();
                signing_bytes.extend_from_slice(
                    &(intent.idempotency_key.len() as u64).to_be_bytes(),
                );
                signing_bytes.extend_from_slice(intent.idempotency_key.as_bytes());
                signing_bytes.extend_from_slice(
                    &(checkpoint_bytes.len() as u64).to_be_bytes(),
                );
                signing_bytes.extend_from_slice(&checkpoint_bytes);
                let original = crate::CellSplitSupervisorCommitV1 {
                    idempotency_key: intent.idempotency_key.clone(),
                    domain_id: "scope.fixture".to_string(),
                    handoff_plan_digest: "aa".repeat(32),
                    old_generation: plan.parent_generation,
                    new_generation: plan.child_generation,
                    authority_epoch: 7,
                    committed_revision: 10,
                    original_checkpoint_bytes: checkpoint_bytes,
                    original_checkpoint_signature_bytes: key(72)
                        .sign(&signing_bytes)
                        .to_bytes()
                        .to_vec(),
                };
                canonical_json(&original).expect("original signed terminal journal")
            }
            _ => canonical_json(&intent).expect("fixture original receipt"),
        };
        let mut receipt = crate::CellSplitExecutionReceiptV1 {
            intent,
            owner_sequence: if index == 3 { 10 } else { index as u64 + 1 },
            output_digest: crate::durable::sha256(&owner_bytes),
            owner_receipt_bytes: owner_bytes,
            owner_signature_bytes: Vec::new(),
            receipt_digest: String::new(),
        };
        receipt.owner_signature_bytes = keys[index]
            .sign(&crate::cell_split_execution_signing_payload_v1(&receipt).expect("payload"))
            .to_bytes()
            .to_vec();
        receipt.receipt_digest = crate::cell_split_execution_receipt_digest_v1(&receipt)
            .expect("original receipt digest");
        predecessor = receipt.receipt_digest.clone();
        receipts.push(receipt);
    }
    let mut digest_bytes = b"hepta.learning.cell-split.verified-transcript.v1\0".to_vec();
    digest_bytes.extend_from_slice(&canonical_json(&plan).expect("canonical plan"));
    digest_bytes.extend_from_slice(&canonical_json(&receipts).expect("original receipts"));
    let transcript = crate::CellSplitExecutionTranscriptV1 {
        plan,
        receipts,
        transcript_digest: crate::durable::sha256(&digest_bytes),
    };
    (transcript, trusted)
}

/// Bind real stage identities before the host and Observer sign the report.
/// Previously the positive fixture used unrelated event IDs and receipt hashes;
/// that made a correctly signed but disconnected lifecycle look acceptable.
fn bound_host_owner_fixture(
    host: &SigningKey,
    observer: &SigningKey,
) -> (
    CellSplitSignedTargetHostEvidenceV1,
    crate::CellSplitExecutionTranscriptV1,
    crate::CellSplitOwnerTrustV1,
) {
    let mut payload = complete_recorder();
    let (transcript, trust) = signed_owner_transcript_for_host(&payload);
    for event in &mut payload.events {
        let receipt = match event.event_kind {
            CellSplitTargetHostEventKindV1::ArtifactLoaded => {
                Some(&transcript.receipts[0])
            }
            CellSplitTargetHostEventKindV1::RouteCutover => {
                Some(&transcript.receipts[2])
            }
            _ => None,
        };
        if let Some(original) = receipt {
            event.operation_id = original.intent.idempotency_key.clone();
            event.receipt_digest = original.receipt_digest.clone();
        }
    }
    let mut predecessor = ZERO_DIGEST.to_string();
    for event in &mut payload.events {
        event.previous_event_digest = predecessor;
        event.event_digest = event_digest(event).expect("bound event");
        predecessor = event.event_digest.clone();
    }
    payload.evidence_digest = evidence_digest(&payload).expect("bound evidence");
    let envelope = payload
        .sign(
            "host-signer",
            host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("independent signed host and Observer report");
    (envelope, transcript, trust)
}

fn signed_observer_join_fixture(
    envelope: &CellSplitSignedTargetHostEvidenceV1,
    transcript: &crate::CellSplitExecutionTranscriptV1,
    host: &SigningKey,
    observer: &SigningKey,
) -> crate::CellSplitSignedObserverJoinV1 {
    use ed25519_dalek::Signer as _;

    let payload = crate::cell_split_observer_join_payload_v1(transcript, envelope)
        .expect("identical host and split identities");
    let signing_bytes = crate::cell_split_observer_join_signing_payload_v1(&payload)
        .expect("observer pairing domain");
    let signature = |id: &str, key: &SigningKey| CellSplitTargetHostSignatureV1 {
        signer_id: id.to_string(),
        verifying_key_base64: BASE64.encode(key.verifying_key().to_bytes()),
        signature_base64: BASE64.encode(key.sign(&signing_bytes).to_bytes()),
    };
    crate::CellSplitSignedObserverJoinV1 {
        schema: crate::CELL_SPLIT_OBSERVER_JOIN_SCHEMA_V1.into(),
        payload,
        host_signature: signature("host-signer", host),
        observer_signature: signature("observer-signer", observer),
    }
}

struct CurrentEffectFixture {
    committed: BTreeMap<String, crate::CellSplitExecutionReceiptV1>,
    verification_count: usize,
}

impl CurrentEffectFixture {
    fn new(transcript: &crate::CellSplitExecutionTranscriptV1) -> Self {
        Self {
            committed: transcript.receipts.iter().map(|receipt| {
                (receipt.intent.idempotency_key.clone(), receipt.clone())
            }).collect(),
            verification_count: 0,
        }
    }
}

impl crate::CellSplitExecutionPortV1 for CurrentEffectFixture {
    type Error = &'static str;

    fn preflight_uncommitted(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        Err("observer cannot prepare an effect")
    }

    fn execute(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<crate::CellSplitExecutionReceiptV1, Self::Error> {
        Err("observer cannot execute an effect")
    }

    fn reconcile(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<Option<crate::CellSplitExecutionReceiptV1>, Self::Error> {
        Err("observer cannot reconcile a mutation")
    }

    fn verify_committed(
        &mut self,
        intent: &crate::CellSplitExecutionIntentV1,
        receipt: &crate::CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error> {
        self.verification_count += 1;
        if self.committed.get(&intent.idempotency_key) == Some(receipt) {
            Ok(())
        } else {
            Err("real owner effect no longer current")
        }
    }
}

#[test]
fn observer_join_rejects_independently_signed_disconnected_operations() {
    let host = key(3);
    let observer = key(7);
    let (original, transcript, _) = bound_host_owner_fixture(&host, &observer);
    let variants = [
        ("artifact-operation", CellSplitTargetHostEventKindV1::ArtifactLoaded, true),
        ("artifact-receipt", CellSplitTargetHostEventKindV1::ArtifactLoaded, false),
        ("cns-operation", CellSplitTargetHostEventKindV1::RouteCutover, true),
        ("cns-receipt", CellSplitTargetHostEventKindV1::RouteCutover, false),
    ];
    for (name, stage, change_operation) in variants {
        let mut payload = original.payload.clone();
        let event = payload.events.iter_mut()
            .find(|record| record.event_kind == stage)
            .expect("required host lifecycle operation");
        if change_operation {
            event.operation_id = format!("independently-signed-unrelated-{name}");
        } else {
            event.receipt_digest =
                crate::durable::sha256(format!("independent-host-{name}").as_bytes());
        }
        let mut predecessor = ZERO_DIGEST.to_string();
        for event in &mut payload.events {
            event.previous_event_digest = predecessor;
            event.event_digest = event_digest(event).expect("new signed event digest");
            predecessor = event.event_digest.clone();
        }
        payload.evidence_digest =
            evidence_digest(&payload).expect("new independent host chain");
        let unrelated = payload.sign(
            "host-signer", &host,
            [("observer-signer".to_string(), observer.clone())],
        ).expect("otherwise valid independent host/Observer evidence");
        assert!(
            verify_cell_split_target_host_evidence(
                &unrelated, &policy(&host, &observer),
            ).is_ok(),
            "{name}: host and observer evidence must be independently valid",
        );
        assert!(matches!(
            crate::cell_split_observer_join_payload_v1(&transcript, &unrelated),
            Err(crate::CellSplitObserverJoinErrorV1::Invalid(
                "host lifecycle is not bound to original Artifact CAS and CNS owner receipts"
            ))
        ), "{name}: a valid signature on an unrelated operation must fail the join");
    }
}

/// Source fixture for an independent Observer's retained checkpoint witness.
/// Production must read an authenticated monotonic store before signing.
#[cfg(unix)]
fn signed_supervisor_minimum_witness(
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    transcript: &crate::CellSplitExecutionTranscriptV1,
    signer: &SigningKey,
    minimum_digest: &str,
) -> CellSplitTargetHostSignatureV1 {
    use ed25519_dalek::Signer as _;

    let journal: crate::CellSplitSupervisorCommitV1 =
        serde_json::from_slice(&transcript.receipts[3].owner_receipt_bytes)
            .expect("original Supervisor receipt");
    let message = crate::cell_split_supervisor_minimum_signing_payload_v1(
        &transcript.plan,
        evidence,
        &journal,
        minimum_digest,
    )
    .expect("minimum witness signing payload");
    CellSplitTargetHostSignatureV1 {
        signer_id: "observer-signer".into(),
        verifying_key_base64: BASE64.encode(signer.verifying_key().to_bytes()),
        signature_base64: BASE64.encode(signer.sign(&message).to_bytes()),
    }
}

#[cfg(unix)]
#[test]
fn deep_observer_join_checks_independent_cns_and_supervisor_originals() {
    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, owner_trust) =
        bound_host_owner_fixture(&host, &observer);
    let join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );
    let external_cns = key(71).verifying_key();
    let external_supervisor = key(72).verifying_key();
    let pinned_checkpoint_digest = {
        let signed: crate::CellSplitSupervisorCommitV1 =
            serde_json::from_slice(&transcript.receipts[3].owner_receipt_bytes)
                .expect("Supervisor commit");
        let checkpoint: serde_json::Value =
            serde_json::from_slice(&signed.original_checkpoint_bytes)
                .expect("checkpoint");
        checkpoint["receiptDigest"].as_str().expect("checkpoint digest").to_owned()
    };
    let minimum_signature = signed_supervisor_minimum_witness(
        &envelope,
        &transcript,
        &observer,
        &pinned_checkpoint_digest,
    );
    let trust = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &external_cns,
        supervisor_original_journal_key: &external_supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    let mut current = CurrentEffectFixture::new(&transcript);
    let accepted = crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join,
            &transcript,
            &owner_trust,
            &envelope,
            &policy(&host, &observer),
            &trust,
            &mut current,
        ).expect("original CNS, original terminal journal and four current owners");
    assert_eq!(current.verification_count, 4);
    assert!(accepted.independently_signed_original_runtime_and_journal);
    assert_eq!(
        accepted.supervisor_minimum_checkpoint_digest,
        pinned_checkpoint_digest,
    );
    assert_eq!(
        accepted.supervisor_minimum_observer_witness_digest,
        crate::durable::sha256(
            &canonical_json(&minimum_signature).expect("minimum witness"),
        ),
    );
    // Correct terminal checkpoint bytes plus an attacker-issued "minimum"
    // are not independent anti-rollback evidence. The matching digest alone
    // must not pass the original Observer's pinned signer boundary.
    let forged_witness = signed_supervisor_minimum_witness(
        &envelope,
        &transcript,
        &key(19),
        &pinned_checkpoint_digest,
    );
    let forged_minimum = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &external_cns,
        supervisor_original_journal_key: &external_supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &forged_witness,
    };
    let mut rejected = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &forged_minimum, &mut rejected,
        ).is_err());
    assert_eq!(rejected.verification_count, 0);

    // A genuinely signed minimum belongs to a specific host execution.
    // Replaying it against a different host nonce cannot reauthorize the
    // current four-owner transcript even if the journal digest is identical.
    let mut unrelated_execution = envelope.clone();
    unrelated_execution.payload.target_host_nonce.push_str("-other");
    let replay_witness = signed_supervisor_minimum_witness(
        &unrelated_execution,
        &transcript,
        &observer,
        &pinned_checkpoint_digest,
    );
    let replayed_minimum = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &external_cns,
        supervisor_original_journal_key: &external_supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &replay_witness,
    };
    let mut rejected = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &replayed_minimum, &mut rejected,
        ).is_err());
    assert_eq!(rejected.verification_count, 0);

    let independently_stale = "aa".repeat(32);
    let stale_minimum = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &external_cns,
        supervisor_original_journal_key: &external_supervisor,
        supervisor_minimum_checkpoint_digest: &independently_stale,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    let mut rejected = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &stale_minimum, &mut rejected,
        ).is_err());
    assert_eq!(rejected.verification_count, 0);
    assert_eq!(accepted.join.split_id, transcript.plan.split_id);
    assert!(!accepted.production_activation_authorized);
    assert!(!accepted.join.production_activation_authorized);
    assert_eq!(
        accepted.original_cns_runtime_digest,
        crate::durable::sha256(
            &serde_json::from_slice::<crate::CellSplitCnsRuntimeCommitV1>(
                &transcript.receipts[2].owner_receipt_bytes,
            ).expect("typed cutover").original_runtime_receipt_bytes,
        ),
    );

    // A separately valid but unrelated CNS signing key must not be accepted.
    let incorrect_cns = key(73).verifying_key();
    let wrong_cns = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &incorrect_cns,
        supervisor_original_journal_key: &external_supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    let mut current = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join,
            &transcript,
            &owner_trust,
            &envelope,
            &policy(&host, &observer),
            &wrong_cns,
            &mut current,
        ).is_err());
    assert_eq!(current.verification_count, 0);

    let incorrect_supervisor = key(74).verifying_key();
    let wrong_supervisor = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &external_cns,
        supervisor_original_journal_key: &incorrect_supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join,
            &transcript,
            &owner_trust,
            &envelope,
            &policy(&host, &observer),
            &wrong_supervisor,
            &mut current,
        ).is_err());
    assert_eq!(current.verification_count, 0);

    // Host/Observer or outer effect owners cannot masquerade as the
    // separately pinned origin of a CNS/Supervisor runtime checkpoint.
    let reused_host = host.verifying_key();
    let reused_owner = key(54).verifying_key();
    let conflated = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &reused_host,
        supervisor_original_journal_key: &reused_owner,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_port_v1(
            &join,
            &transcript,
            &owner_trust,
            &envelope,
            &policy(&host, &observer),
            &conflated,
            &mut current,
        ).is_err());
    assert_eq!(current.verification_count, 0);
}

/// An uncooperative process can delete the separately retained minimum
/// while the Observer is fetching the four original owner signatures.
#[cfg(unix)]
struct RevokeMinimumDuringEffectRead {
    inner: CurrentEffectFixture,
    minimum_path: std::path::PathBuf,
}

#[cfg(unix)]
impl crate::CellSplitExecutionPortV1 for RevokeMinimumDuringEffectRead {
    type Error = &'static str;

    fn preflight_uncommitted(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        Err("read-only Observer cannot prepare a minimum")
    }

    fn execute(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<crate::CellSplitExecutionReceiptV1, Self::Error> {
        Err("read-only Observer cannot execute a split")
    }

    fn reconcile(
        &mut self,
        _intent: &crate::CellSplitExecutionIntentV1,
    ) -> Result<Option<crate::CellSplitExecutionReceiptV1>, Self::Error> {
        Err("read-only Observer cannot reconcile a split")
    }

    fn verify_committed(
        &mut self,
        intent: &crate::CellSplitExecutionIntentV1,
        receipt: &crate::CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error> {
        self.inner.verify_committed(intent, receipt)?;
        if self.inner.verification_count == 2 {
            std::fs::remove_file(&self.minimum_path)
                .map_err(|_| "independent minimum revocation failed")?;
        }
        Ok(())
    }
}

#[cfg(unix)]
struct IndependentlyAdmittedJournalMinimum;

#[cfg(unix)]
impl crate::CellSplitSupervisorMinimumAdmissionPortV1 for IndependentlyAdmittedJournalMinimum {
    type Error = &'static str;

    fn verify_original_minimum(
        &mut self,
        _subject: &crate::CellSplitSupervisorMinimumSubjectV1,
    ) -> Result<(), Self::Error> {
        // Source-only test witness. Real admission reads original journal,
        // independent Selector/NDU and an external monotonic minimum.
        Ok(())
    }
}

#[cfg(unix)]
#[test]
fn production_deep_join_requires_fresh_independent_minimum_store() {
    use std::fs;
    use std::os::unix::fs::PermissionsExt as _;

    use crate::CellSplitSupervisorMinimumFileStoreV1;

    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, owner_trust) =
        bound_host_owner_fixture(&host, &observer);
    let join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );
    let cns_key = key(71).verifying_key();
    let journal_key = key(72).verifying_key();
    let minimum_store_signer = key(93);
    let minimum_store_key = minimum_store_signer.verifying_key();
    let journal: crate::CellSplitSupervisorCommitV1 = serde_json::from_slice(
        &transcript.receipts[3].owner_receipt_bytes,
    ).expect("original journal");
    let checkpoint: serde_json::Value = serde_json::from_slice(
        &journal.original_checkpoint_bytes,
    ).expect("canonical terminal checkpoint");
    let minimum_digest = checkpoint["receiptDigest"].as_str()
        .expect("signed checkpoint minimum").to_owned();
    let minimum_signature = signed_supervisor_minimum_witness(
        &envelope, &transcript, &observer, &minimum_digest,
    );
    let runtime_trust = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &cns_key,
        supervisor_original_journal_key: &journal_key,
        supervisor_minimum_checkpoint_digest: &minimum_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    let subject = crate::CellSplitSupervisorMinimumSubjectV1 {
        split_id: transcript.plan.split_id.clone(),
        target_host_id: envelope.payload.target_host_id.clone(),
        target_host_nonce: envelope.payload.target_host_nonce.clone(),
        plan_digest: transcript.plan.digest().expect("frozen plan"),
        host_evidence_digest: envelope.payload.evidence_digest.clone(),
        journal_domain_id: journal.domain_id.clone(),
        journal_idempotency_key: journal.idempotency_key.clone(),
        journal_authority_epoch: journal.authority_epoch,
        journal_revision: journal.committed_revision,
        original_checkpoint_bytes_digest:
            crate::durable::sha256(&journal.original_checkpoint_bytes),
        minimum_checkpoint_digest: minimum_digest,
    };

    let root = tempfile::tempdir().expect("external minimum root");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
        .expect("independent private storage");
    let mut external = CellSplitSupervisorMinimumFileStoreV1::open(
        root.path(), minimum_store_signer,
    ).expect("separate owner");
    let mut current = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_minimum_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &runtime_trust,
            &minimum_store_key, &mut external, &mut current,
        ).is_err(), "a signed old checkpoint does not replace a current store");
    assert_eq!(current.verification_count, 0);

    external
        .publish_once(&subject, &mut IndependentlyAdmittedJournalMinimum)
        .expect("durable independent minimum");
    let mut current = CurrentEffectFixture::new(&transcript);
    let accepted = crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_minimum_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &runtime_trust,
            &minimum_store_key, &mut external, &mut current,
        ).expect("current minimum and four original owner observations");
    assert!(accepted.live_minimum_readback_digest.is_some());
    assert_eq!(current.verification_count, 4);
    assert!(!accepted.production_activation_authorized);

    let mut denied = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_minimum_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &runtime_trust,
            &observer.verifying_key(), &mut external, &mut denied,
        ).is_err(), "minimum signer cannot reuse the Observer key");
    assert_eq!(denied.verification_count, 0);
    let mut denied = CurrentEffectFixture::new(&transcript);
    denied.committed.clear();
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_minimum_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &runtime_trust,
            &minimum_store_key, &mut external, &mut denied,
        ).is_err(), "fresh minimum cannot conceal revoked owner receipts");
    assert_eq!(denied.verification_count, 1);

    // The signed minimum must also remain live *after* the four individual
    // effect readbacks. A revoked file between the first and final challenges
    // must not be laundered into a successful deep Observer receipt.
    let mut interrupted = RevokeMinimumDuringEffectRead {
        inner: CurrentEffectFixture::new(&transcript),
        minimum_path: root.path().join("independent-supervisor-minimum.json"),
    };
    assert!(crate::cell_split_observer_join::
        verify_cell_split_observer_join_deep_with_minimum_port_v1(
            &join, &transcript, &owner_trust, &envelope,
            &policy(&host, &observer), &runtime_trust,
            &minimum_store_key, &mut external, &mut interrupted,
        ).is_err());
    assert_eq!(interrupted.inner.verification_count, 4);
}

#[cfg(unix)]
#[test]
fn deep_observer_rejects_signed_nonterminal_supervisor_checkpoint() {
    use ed25519_dalek::Signer as _;

    let host = key(3);
    let observer = key(7);
    let (envelope, mut transcript, owner_trust) =
        bound_host_owner_fixture(&host, &observer);
    let outer = &mut transcript.receipts[3];
    let mut journal: crate::CellSplitSupervisorCommitV1 =
        serde_json::from_slice(&outer.owner_receipt_bytes)
            .expect("original Supervisor receipt");
    let mut checkpoint: serde_json::Value =
        serde_json::from_slice(&journal.original_checkpoint_bytes)
            .expect("signed journal checkpoint");
    checkpoint["phase"] = serde_json::json!("route_published");
    let mutated: crate::cell_split_observer_join::OriginalSupervisorCheckpointV1 =
        serde_json::from_value(checkpoint).expect("valid nonterminal shape");
    journal.original_checkpoint_bytes =
        serde_json::to_vec(&mutated).expect("nonterminal journal");
    let mut payload = b"hepta.supervisor.cell-split.original-journal.v1\0".to_vec();
    payload.extend_from_slice(&(journal.idempotency_key.len() as u64).to_be_bytes());
    payload.extend_from_slice(journal.idempotency_key.as_bytes());
    payload.extend_from_slice(&(journal.original_checkpoint_bytes.len() as u64).to_be_bytes());
    payload.extend_from_slice(&journal.original_checkpoint_bytes);
    journal.original_checkpoint_signature_bytes =
        key(72).sign(&payload).to_bytes().to_vec();

    // Update the complete independently valid outer Supervisor signature
    // and the full coordinator transcript digest. A stale hash cannot be
    // the reason this nonterminal original is refused.
    outer.owner_receipt_bytes = canonical_json(&journal).expect("typed original");
    outer.output_digest = crate::durable::sha256(&outer.owner_receipt_bytes);
    outer.owner_signature_bytes = key(54)
        .sign(&crate::cell_split_execution_signing_payload_v1(outer)
            .expect("outer signing payload"))
        .to_bytes()
        .to_vec();
    outer.receipt_digest = crate::cell_split_execution_receipt_digest_v1(outer)
        .expect("outer verified receipt digest");
    let mut frame = b"hepta.learning.cell-split.verified-transcript.v1\0".to_vec();
    frame.extend_from_slice(&canonical_json(&transcript.plan).expect("plan"));
    frame.extend_from_slice(&canonical_json(&transcript.receipts).expect("receipts"));
    transcript.transcript_digest = crate::durable::sha256(&frame);
    crate::verify_cell_split_execution_transcript_signatures_v1(&transcript, &owner_trust)
        .expect("outer signature and predecessor chain remain valid");
    let join = signed_observer_join_fixture(&envelope, &transcript, &host, &observer);
    let cns = key(71).verifying_key();
    let supervisor = key(72).verifying_key();
    let pinned_checkpoint_digest = {
        let signed: crate::CellSplitSupervisorCommitV1 =
            serde_json::from_slice(&transcript.receipts[3].owner_receipt_bytes)
                .expect("Supervisor commit");
        let checkpoint: serde_json::Value =
            serde_json::from_slice(&signed.original_checkpoint_bytes)
                .expect("checkpoint");
        checkpoint["receiptDigest"].as_str().expect("checkpoint digest").to_owned()
    };
    let minimum_signature = signed_supervisor_minimum_witness(
        &envelope,
        &transcript,
        &observer,
        &pinned_checkpoint_digest,
    );
    let runtime = crate::CellSplitObserverOriginalRuntimeTrustV1 {
        cns_original_runtime_key: &cns,
        supervisor_original_journal_key: &supervisor,
        supervisor_minimum_checkpoint_digest: &pinned_checkpoint_digest,
        supervisor_minimum_observer_signature: &minimum_signature,
    };
    let mut current = CurrentEffectFixture::new(&transcript);
    assert!(matches!(
        crate::cell_split_observer_join::verify_cell_split_observer_join_deep_with_port_v1(
            &join,
            &transcript,
            &owner_trust,
            &envelope,
            &policy(&host, &observer),
            &runtime,
            &mut current,
        ),
        Err(crate::CellSplitObserverJoinErrorV1::Invalid(
            "signed original Supervisor checkpoint is not a terminal handoff"
        ))
    ));
    assert_eq!(current.verification_count, 0);
}

#[test]
fn independent_observer_join_requires_all_four_current_owners() {
    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, trust) = bound_host_owner_fixture(&host, &observer);
    let signed_join = signed_observer_join_fixture(&envelope, &transcript, &host, &observer);
    let target_policy = policy(&host, &observer);
    let mut current = CurrentEffectFixture::new(&transcript);

    let receipt = crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &signed_join, &transcript, &trust,
        &envelope, &target_policy, &mut current,
    ).expect("four original effect owners + independently signed target-host pairing");
    assert_eq!(current.verification_count, 4);
    assert!(receipt.four_current_owner_readbacks);
    assert!(receipt.independently_signed_host_and_observer);
    assert!(!receipt.production_activation_authorized);

    // An unrelated or revoked external owner invalidates the joined proof,
    // even though the earlier host and observer signatures are unchanged.
    assert!(current.committed.remove(&transcript.receipts[2].intent.idempotency_key).is_some());
    assert!(crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &signed_join, &transcript, &trust,
        &envelope, &target_policy, &mut current,
    ).is_err());
}

#[test]
fn observer_join_rejects_mixed_host_and_effect_lineage_before_remote_reads() {
    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, trust) = bound_host_owner_fixture(&host, &observer);
    let mut signed_join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );
    let target_policy = policy(&host, &observer);
    let mut current = CurrentEffectFixture::new(&transcript);

    signed_join.payload.owner_receipt_digests[1] = "ff".repeat(32);
    assert!(crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &signed_join, &transcript, &trust,
        &envelope, &target_policy, &mut current,
    ).is_err());
    assert_eq!(current.verification_count, 0);

    let mut signed_join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );
    signed_join.observer_signature.signature_base64 = BASE64.encode([0_u8; 64]);
    assert!(crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &signed_join, &transcript, &trust,
        &envelope, &target_policy, &mut current,
    ).is_err());
    assert_eq!(current.verification_count, 0);

    let mut changed = transcript.clone();
    changed.plan.child_artifact_digest = "99".repeat(32);
    assert!(crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &signed_join, &changed, &trust,
        &envelope, &target_policy, &mut current,
    ).is_err());
    assert_eq!(current.verification_count, 0);
}


#[test]
fn observer_join_rejects_reused_effect_owner_as_host_signer() {
    // Signing key 51 also belongs to the first CellSplit effect owner.
    // Trusting the key as a host signer as well must not create an
    // independently observed production cross-attestation.
    let duplicated_host = key(51);
    let observer = key(7);
    let (envelope, transcript, trust) =
        bound_host_owner_fixture(&duplicated_host, &observer);
    let join = signed_observer_join_fixture(
        &envelope,
        &transcript,
        &duplicated_host,
        &observer,
    );
    let mut current = CurrentEffectFixture::new(&transcript);
    assert!(crate::cell_split_observer_join::verify_cell_split_observer_join_with_port_v1(
        &join,
        &transcript,
        &trust,
        &envelope,
        &policy(&duplicated_host, &observer),
        &mut current,
    ).is_err());
    assert_eq!(current.verification_count, 0);
}


#[cfg(unix)]
#[test]
fn observer_public_gate_refuses_independently_rekeyed_rpc_transport() {
    use std::time::Duration;

    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, trust) = bound_host_owner_fixture(&host, &observer);
    let signed_join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );
    let root = tempfile::tempdir().expect("local sockets not opened");
    let endpoints = std::array::from_fn(|index| {
        root.path().join(format!("absent-owner-{index}.sock"))
    });
    // These are four strong but DIFFERENT keys from the original owner
    // signatures in the transcript. The join must refuse before connecting.
    let wrong_keys = [61_u8, 62, 63, 64].map(|seed| {
        key(seed).verifying_key()
    });
    let mut untrusted = crate::CellSplitUnixEffectPortV1::new(
        endpoints,
        wrong_keys,
        Duration::from_secs(1),
    ).expect("well-shaped but untrusted transport");
    let result = crate::verify_cell_split_observer_join_v1(
        &signed_join,
        &transcript,
        &trust,
        &envelope,
        &policy(&host, &observer),
        &mut untrusted,
    );
    assert!(matches!(
        result,
        Err(crate::CellSplitObserverJoinErrorV1::Invalid(
            "live RPC trust pins differ from four original effect owners"
        ))
    ));
}


#[cfg(unix)]
#[test]
fn observer_public_gate_rechecks_four_distinct_pinned_signed_sockets() {
    use ed25519_dalek::Signer as _;
    use std::os::unix::net::UnixListener;
    use std::thread;
    use std::time::Duration;

    use crate::cell_split_effect_rpc::receive_frame;
    use crate::cell_split_effect_rpc::send_frame;

    let host = key(3);
    let observer = key(7);
    let (envelope, transcript, frozen_keys) =
        bound_host_owner_fixture(&host, &observer);
    let join = signed_observer_join_fixture(
        &envelope, &transcript, &host, &observer,
    );

    // Protocol-only test fixtures: these are four actual Unix owner sockets
    // producing independently signed nonce challenges, NOT deployed owners.
    let root = tempfile::tempdir().expect("socket root");
    let mut endpoints = Vec::new();
    let mut handles = Vec::new();
    for (index, receipt) in transcript.receipts.iter().cloned().enumerate() {
        let endpoint = root.path().join(format!("owner-{index}.sock"));
        let listener = UnixListener::bind(&endpoint).expect("effect owner socket");
        endpoints.push(endpoint);
        handles.push(thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("independent observer read");
            let request: crate::CellSplitEffectRpcRequestV1 =
                receive_frame(&mut stream).expect("readback request");
            assert_eq!(request.action, crate::CellSplitEffectRpcActionV1::ReadBack);
            assert_eq!(request.intent, receipt.intent);
            let mut proof = crate::CellSplitEffectReadbackV1 {
                schema: crate::CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1.into(),
                intent: receipt.intent.clone(),
                challenge_nonce: request.challenge_nonce.expect("fresh challenge"),
                committed_receipt_digest: Some(receipt.receipt_digest.clone()),
                state_digest: Some(receipt.output_digest.clone()),
                read_sequence: receipt.owner_sequence,
                owner_signature_bytes: Vec::new(),
            };
            proof.owner_signature_bytes = key(51 + index as u8)
                .sign(&crate::cell_split_effect_readback_signing_payload_v1(&proof)
                    .expect("readback signing payload"))
                .to_bytes()
                .to_vec();
            let response = crate::CellSplitEffectRpcResponseV1 {
                schema: crate::CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
                action: crate::CellSplitEffectRpcActionV1::ReadBack,
                receipt: Some(receipt),
                readback: Some(proof),
                error: None,
            };
            send_frame(&mut stream, &response).expect("original signed receipt response");
        }));
    }
    let pinned = [51_u8, 52, 53, 54].map(|seed| key(seed).verifying_key());
    let endpoints: [std::path::PathBuf; 4] = endpoints.try_into().expect("four sockets");
    let mut actual_port = crate::CellSplitUnixEffectPortV1::new(
        endpoints, pinned, Duration::from_secs(3),
    ).expect("four independent pinned socket readers");
    let result = crate::verify_cell_split_observer_join_v1(
        &join,
        &transcript,
        &frozen_keys,
        &envelope,
        &policy(&host, &observer),
        &mut actual_port,
    ).expect("public verifier uses all four real nonce-bound transports");
    assert!(result.four_current_owner_readbacks);
    assert!(!result.production_activation_authorized);
    for handle in handles {
        handle.join().expect("effect reader thread");
    }
}


/// Recomputing a consistent hash chain is not evidence that the underlying
/// lifecycle actually used one route/child identity. A separately held host
/// signer must not be able to notarize disconnected stages as one Split.
#[test]
fn independently_rehashed_mismatched_lifecycle_stages_are_rejected() {
    let cases: &[(CellSplitTargetHostEventKindV1, &str)] = &[
        (CellSplitTargetHostEventKindV1::RestartRecovered, "recovery-route"),
        (CellSplitTargetHostEventKindV1::PowerLossRecovered, "recovery-route"),
        (CellSplitTargetHostEventKindV1::RollbackCompleted, "rollback-predecessor"),
        (CellSplitTargetHostEventKindV1::TombstoneCommitted, "tombstone-route"),
        (CellSplitTargetHostEventKindV1::NoResurrectionVerified, "wrong-tombstone"),
        (CellSplitTargetHostEventKindV1::NoResurrectionVerified, "wrong-parent-route"),
        (CellSplitTargetHostEventKindV1::RestartRecovered, "wrong-child-artifact"),
    ];
    for &(kind, mutation) in cases {
        let mut payload = complete_recorder();
        let matching = payload
            .events
            .iter_mut()
            .find(|event| event.event_kind == kind)
            .expect("fixture has every required lifecycle event");
        match mutation {
            "recovery-route" => {
                matching.route_digest = crate::durable::sha256(b"unrelated-live-route");
            }
            "rollback-predecessor" => {
                matching.predecessor_digest = crate::durable::sha256(b"unrelated-active-route");
            }
            "tombstone-route" | "wrong-parent-route" => {
                matching.route_digest = crate::durable::sha256(b"unrelated-parent-route");
            }
            "wrong-tombstone" => matching.tombstone_digest = PARENT.to_string(),
            "wrong-child-artifact" => matching.artifact_digest = PARENT.to_string(),
            _ => unreachable!("named negative fixture"),
        }
        // Rebuild every event hash and the envelope digest after tampering,
        // so rejection cannot be attributed merely to stale checksums.
        let mut predecessor = ZERO_DIGEST.to_string();
        for event in &mut payload.events {
            event.previous_event_digest = predecessor;
            event.event_digest = event_digest(event).expect("canonical forged event");
            predecessor = event.event_digest.clone();
        }
        payload.evidence_digest = evidence_digest(&payload).expect("fresh forged digest");
        let rejection = replay_payload(&payload);
        assert!(rejection.is_err(), "{mutation}: signed lineage was accepted");
        let host = key(59);
        let observer = key(61);
        assert!(
            payload
                .sign(
                    "host-signer",
                    &host,
                    [("observer-signer".to_string(), observer.clone())],
                )
                .is_err(),
            "{mutation}: apparently complete source must not become signed target-host evidence",
        );
        // A compromised evidence producer may bypass our sign() helper and
        // sign arbitrary canonical bytes with otherwise trusted keys. The
        // independent verifier must still reject the coherent-looking chain.
        let forged_bytes = payload.canonical_bytes().expect("forged canonical payload");
        let forged = CellSplitSignedTargetHostEvidenceV1 {
            schema: CELL_SPLIT_SIGNED_TARGET_HOST_EVIDENCE_SCHEMA_V1.to_string(),
            schema_version: 1,
            signature_algorithm: CELL_SPLIT_TARGET_HOST_EVIDENCE_SIGNATURE_ALGORITHM_V1.to_string(),
            payload,
            host_signature: sign_payload("host-signer".to_string(), &host, &forged_bytes),
            observer_signatures: vec![sign_payload(
                "observer-signer".to_string(),
                &observer,
                &forged_bytes,
            )],
        };
        assert!(
            verify_cell_split_target_host_evidence(&forged, &policy(&host, &observer)).is_err(),
            "{mutation}: independently verified signatures must not launder a broken lifecycle",
        );
    }
}


#[test]
fn target_host_ingest_rejects_noncanonical_json_even_if_signatures_verify() {
    let payload = complete_recorder();
    let host = key(109);
    let observer = key(113);
    let envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("properly signed evidence");
    let policy = policy(&host, &observer);
    let canonical = envelope.canonical_bytes().expect("canonical transport");
    assert!(verify_cell_split_target_host_evidence_json(&canonical, &policy).is_ok());
    let pretty = serde_json::to_vec_pretty(&envelope).expect("equivalent pretty JSON");
    assert_ne!(pretty, canonical);
    assert!(
        verify_cell_split_target_host_evidence_json(&pretty, &policy)
            .expect_err("noncanonical transport must not be ingested")
            .to_string()
            .contains("not canonical"),
    );
}

#[test]
fn bounded_target_host_envelope_refuses_synthetic_and_excessive_observers() {
    let host = key(73);
    let observer = key(79);
    let trust = policy(&host, &observer);
    let payload = complete_recorder();
    let mut envelope = payload
        .sign(
            "host-signer",
            &host,
            [("observer-signer".to_string(), observer.clone())],
        )
        .expect("legitimate signed evidence");
    assert!(verify_cell_split_target_host_evidence(&envelope, &trust).is_ok());
    for index in 0..MAX_OBSERVER_SIGNATURES {
        envelope.observer_signatures.push(sign_payload(
            format!("untrusted-observer-{index}"),
            &key(90 + index as u8),
            &payload.canonical_bytes().expect("original canonical payload"),
        ));
    }
    assert!(
        verify_cell_split_target_host_evidence(&envelope, &trust)
            .expect_err("unbounded observer key fan-out cannot be verified")
            .to_string()
            .contains("bounded independent observer"),
    );
    let oversized_json = vec![b' '; MAX_EVIDENCE_BYTES + 1];
    assert!(
        verify_cell_split_target_host_evidence_json(&oversized_json, &trust)
            .expect_err("oversized bytes should be rejected before JSON parse")
            .to_string()
            .contains("bounded input"),
    );
    let mut synthetic = complete_recorder();
    let metric = synthetic
        .events
        .iter_mut()
        .find(|event| event.event_kind == CellSplitTargetHostEventKindV1::ResourceMeasurement)
        .expect("resource");
    metric.resource
        .as_mut()
        .expect("sample")
        .measurement_source = "Externally-SYNTHETIC-counter".to_string();
    let mut previous = ZERO_DIGEST.to_string();
    for event in &mut synthetic.events {
        event.previous_event_digest = previous;
        event.event_digest = event_digest(event).expect("rehash");
        previous = event.event_digest.clone();
    }
    synthetic.evidence_digest = evidence_digest(&synthetic).expect("recompute envelope digest");
    assert!(
        synthetic
            .sign(
                "host-signer",
                &host,
                [("observer-signer".to_string(), observer)],
            )
            .is_err(),
        "resigned mixed-case synthetic resources cannot count as target-host measurements",
    );
}

#[test]
fn a_well_formed_hash_chain_does_not_launder_a_nondigest_operation_receipt() {
    let mut forged = complete_recorder();
    forged.events[0].receipt_digest = "operation receipt from another system".to_string();
    let mut previous = ZERO_DIGEST.to_string();
    for event in &mut forged.events {
        event.previous_event_digest = previous;
        event.event_digest = event_digest(event).expect("validly rehashed event");
        previous = event.event_digest.clone();
    }
    forged.evidence_digest = evidence_digest(&forged).expect("matching envelope hash");
    assert!(replay_payload(&forged).is_err());
    let host = key(101);
    let observer = key(103);
    assert!(
        forged
            .sign(
                "host-signer",
                &host,
                [("observer-signer".to_string(), observer)],
            )
            .is_err(),
    );
}


#[test]
fn same_third_party_route_in_rollback_and_tombstone_still_fails() {
    let mut payload = complete_recorder();
    let unrelated_parent = crate::durable::sha256(b"attacker-replaced-original-parent-route");
    assert_ne!(unrelated_parent, PARENT_ROUTE);
    assert_ne!(unrelated_parent, CHILD_ROUTE);
    for event in &mut payload.events {
        match event.event_kind {
            CellSplitTargetHostEventKindV1::RollbackCompleted => {
                event.route_digest = unrelated_parent.clone();
            }
            CellSplitTargetHostEventKindV1::TombstoneCommitted
            | CellSplitTargetHostEventKindV1::NoResurrectionVerified => {
                event.route_digest = unrelated_parent.clone();
                event.predecessor_digest = unrelated_parent.clone();
            }
            _ => {}
        }
    }
    let mut previous = ZERO_DIGEST.to_string();
    for event in &mut payload.events {
        event.previous_event_digest = previous;
        event.event_digest = event_digest(event).expect("validly rehashed lifecycle");
        previous = event.event_digest.clone();
    }
    payload.evidence_digest = evidence_digest(&payload).expect("validly rehashed envelope");
    let bytes = payload.canonical_bytes().expect("canonical forged bytes");
    let host = key(127);
    let observer = key(131);
    let envelope = CellSplitSignedTargetHostEvidenceV1 {
        schema: CELL_SPLIT_SIGNED_TARGET_HOST_EVIDENCE_SCHEMA_V1.to_string(),
        schema_version: 1,
        signature_algorithm: CELL_SPLIT_TARGET_HOST_EVIDENCE_SIGNATURE_ALGORITHM_V1.to_string(),
        payload,
        host_signature: sign_payload("host-signer".to_string(), &host, &bytes),
        observer_signatures: vec![sign_payload(
            "observer-signer".to_string(),
            &observer,
            &bytes,
        )],
    };
    assert!(
        verify_cell_split_target_host_evidence(&envelope, &policy(&host, &observer)).is_err(),
        "a fully signed tombstone on a third route cannot replace the original parent",
    );
}

#[test]
fn signed_host_cannot_launder_extra_gpu_or_npu_sample_in_lifecycle_event() {
    let mut payload = complete_recorder();
    // Construct a report signed by BOTH trusted parties, with a valid hash
    // chain, but with an extra fabricated NPU sample attached to ArtifactLoaded
    // rather than a typed resource measurement operation.
    let mut extra = payload
        .events
        .iter()
        .find_map(|event| event.resource.clone())
        .expect("existing real-format resource sample");
    extra.hardware = CellSplitTargetHardwareV1::Npu;
    extra.hardware_model = "different-unmeasured-hardware".to_string();
    payload.events[0].resource = Some(extra);
    let mut previous = ZERO_DIGEST.to_string();
    for event in &mut payload.events {
        event.previous_event_digest = previous;
        event.event_digest = event_digest(event).expect("rehashed event");
        previous = event.event_digest.clone();
    }
    payload.evidence_digest = evidence_digest(&payload).expect("rehashed payload");

    let host = key(101);
    let observer = key(103);
    let payload_bytes = payload.canonical_bytes().expect("canonical payload");
    let envelope = CellSplitSignedTargetHostEvidenceV1 {
        schema: CELL_SPLIT_SIGNED_TARGET_HOST_EVIDENCE_SCHEMA_V1.to_string(),
        schema_version: 1,
        signature_algorithm: CELL_SPLIT_TARGET_HOST_EVIDENCE_SIGNATURE_ALGORITHM_V1.to_string(),
        host_signature: sign_payload("host-signer".to_string(), &host, &payload_bytes),
        observer_signatures: vec![sign_payload(
            "observer-signer".to_string(),
            &observer,
            &payload_bytes,
        )],
        payload,
    };
    let error = verify_cell_split_target_host_evidence(
        &envelope,
        &policy(&host, &observer),
    )
    .expect_err("signed lifecycle data must not masquerade as hardware measurements");
    assert!(
        error
            .to_string()
            .contains("resource sample is not a ResourceMeasurement event")
    );
}
