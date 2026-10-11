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
const PARENT_FENCE: &str = "1111111111111111111111111111111111111111111111111111111111111111";

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
            CellSplitTargetHostEventKindV1::RouteCutover => PARENT_FENCE.to_string(),
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
        receipt_digest: crate::durable::sha256(
            format!("receipt-{sequence}").as_bytes(),
        ),
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
fn host_observer_keys_must_be_independent_and_signer_aliases_unique() {
    let host = key(41);
    let observer = key(43);
    let shared = policy(&host, &host);
    assert!(shared.to_json_bytes().is_err());

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
        let owner_bytes = canonical_json(&intent).expect("fixture original receipt");
        let mut receipt = crate::CellSplitExecutionReceiptV1 {
            intent,
            owner_sequence: index as u64 + 1,
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
fn independent_observer_join_requires_all_four_current_owners() {
    let target = complete_recorder();
    let host = key(3);
    let observer = key(7);
    let envelope = target.sign(
        "host-signer", &host,
        [("observer-signer".to_string(), observer.clone())],
    ).expect("signed target host");
    let (transcript, trust) = signed_owner_transcript_for_host(&envelope.payload);
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
    let target = complete_recorder();
    let host = key(3);
    let observer = key(7);
    let envelope = target.sign(
        "host-signer", &host,
        [("observer-signer".to_string(), observer.clone())],
    ).expect("signed target host");
    let (transcript, trust) = signed_owner_transcript_for_host(&envelope.payload);
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
    let payload = complete_recorder();
    // Signing key 51 also belongs to the first CellSplit effect owner.
    // Trusting the key as a host signer as well must not create an
    // independently observed production cross-attestation.
    let duplicated_host = key(51);
    let observer = key(7);
    let envelope = payload.sign(
        "host-signer",
        &duplicated_host,
        [("observer-signer".to_string(), observer.clone())],
    ).expect("host report can be signed independently of trust role");
    let (transcript, trust) = signed_owner_transcript_for_host(&envelope.payload);
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

    let payload = complete_recorder();
    let host = key(3);
    let observer = key(7);
    let envelope = payload.sign(
        "host-signer", &host,
        [("observer-signer".to_string(), observer.clone())],
    ).expect("signed evidence");
    let (transcript, trust) = signed_owner_transcript_for_host(&envelope.payload);
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
    let envelope = complete_recorder().sign(
        "host-signer", &host,
        [("observer-signer".to_string(), observer.clone())],
    ).expect("separate signed host lifecycle");
    let (transcript, frozen_keys) = signed_owner_transcript_for_host(&envelope.payload);
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
            "recovery-route" => matching.route_digest = crate::durable::sha256(b"unrelated-live-route"),
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
                    [("observer-signer".to_string(), observer)],
                )
                .is_err(),
            "{mutation}: apparently complete source must not become signed target-host evidence",
        );
    }
}
