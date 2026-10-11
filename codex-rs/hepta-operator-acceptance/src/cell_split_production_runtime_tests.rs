use super::*;
use std::sync::Arc;

const DIGEST_A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const DIGEST_B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const DIGEST_C: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

fn config() -> ProductionTargetHostRuntimeConfig {
    ProductionTargetHostRuntimeConfig {
        split_id: "split.test".to_owned(),
        namespace: "runtime.test".to_owned(),
        target_host_id: "host.test".to_owned(),
        target_host_nonce: "nonce.test".to_owned(),
        parent_generation: 7,
        child_generation: 8,
        parent_artifact_digest: DIGEST_A.to_owned(),
        child_artifact_digest: DIGEST_B.to_owned(),
        parameter_bundle_digest: DIGEST_C.to_owned(),
        migration_digest: DIGEST_A.to_owned(),
        trust_root_digest: DIGEST_C.to_owned(),
        approved_power_loss: true,
        minimum_future_window_samples: 1,
        artifact_owner: None,
        route_owner: None,
        fault_injector: None,
        tombstone_owner: None,
        taskflow_owner: None,
        telemetry_owner: None,
        hardware_attestation_owner: None,
        learning_ledger_owner: None,
        future_window_evaluator_owner: None,
        evidence_signing_owner: None,
        canonical_packet_verifier_owner: None,
    }
}

#[derive(Debug)]
struct BoundArtifact(ProductionOwnerBindingV1);
impl ArtifactOwnerHandleV1 for BoundArtifact {
    fn binding(&self) -> &ProductionOwnerBindingV1 {
        &self.0
    }

    fn load_parent_child(
        &self,
        _request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1> {
        Err(ProductionExternalErrorV1 {
            detail: "test owner must not be called".to_owned(),
        })
    }
}

#[derive(Debug)]
struct RejectingCanonicalVerifier(ProductionOwnerBindingV1);

impl ProductionCanonicalPacketVerifierOwnerHandleV1 for RejectingCanonicalVerifier {
    fn binding(&self) -> &ProductionOwnerBindingV1 {
        &self.0
    }

    fn verify_canonical_packet(
        &self,
        _request: &ProductionOwnerRequestV1,
        _packet: &CellSplitProductionPacketV1,
    ) -> Result<ProductionCanonicalPacketVerificationReceiptV1, ProductionExternalErrorV1> {
        Ok(ProductionCanonicalPacketVerificationReceiptV1 {
            verifier_id: "verifier.test".to_owned(),
            canonical_packet_digest: "0".repeat(64),
            signed_envelope_digest: DIGEST_A.to_owned(),
            canonical_packet_verified: false,
            signed_envelope_verified: true,
        })
    }
}

#[derive(Debug)]
struct AcceptingCanonicalVerifier(ProductionOwnerBindingV1);

impl ProductionCanonicalPacketVerifierOwnerHandleV1 for AcceptingCanonicalVerifier {
    fn binding(&self) -> &ProductionOwnerBindingV1 {
        &self.0
    }

    fn verify_canonical_packet(
        &self,
        _request: &ProductionOwnerRequestV1,
        packet: &CellSplitProductionPacketV1,
    ) -> Result<ProductionCanonicalPacketVerificationReceiptV1, ProductionExternalErrorV1> {
        let mut packet = packet.clone();
        packet.canonical_verification = None;
        let digest = super::canonical_json(&packet)
            .map(|bytes| super::sha256(&bytes))
            .map_err(|error| ProductionExternalErrorV1 {
                detail: error.to_string(),
            })?;
        Ok(ProductionCanonicalPacketVerificationReceiptV1 {
            verifier_id: "verifier.test".to_owned(),
            canonical_packet_digest: digest,
            signed_envelope_digest: DIGEST_A.to_owned(),
            canonical_packet_verified: true,
            signed_envelope_verified: true,
        })
    }
}

#[test]
fn missing_owner_fails_closed_before_lifecycle_receipt() {
    let mut runtime = ProductionTargetHostRuntime::new(config());
    let error = runtime
        .load_child_artifact()
        .expect_err("artifact owner is required");
    assert_eq!(
        error,
        CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "artifact" }
    );
    assert_eq!(runtime.phase(), None);
    assert!(!runtime.packet().schema.is_empty());
    let blocked = runtime.blocked_packet();
    assert!(!blocked.production_evidence);
    assert!(blocked.blocked_inputs.contains(&"artifact".to_owned()));
}

#[test]
fn wrong_trust_root_is_structured_and_does_not_call_owner() {
    let mut configuration = config();
    configuration.artifact_owner = Some(Arc::new(BoundArtifact(ProductionOwnerBindingV1 {
        owner_id: "artifact-owner".to_owned(),
        namespace: configuration.namespace.clone(),
        trust_root_digest: DIGEST_A.to_owned(),
    })));
    let mut runtime = ProductionTargetHostRuntime::new(configuration);
    let error = runtime
        .load_child_artifact()
        .expect_err("wrong trust root must fail closed");
    assert_eq!(
        error,
        CellSplitTargetHostRuntimeErrorV1::WrongTrustRoot { owner: "artifact" }
    );
    assert_eq!(runtime.phase(), None);
}

#[test]
fn lifecycle_enum_has_exactly_fourteen_steps() {
    let steps = [
        CellSplitProductionLifecycleStepV1::OwnersBound,
        CellSplitProductionLifecycleStepV1::ArtifactsLoaded,
        CellSplitProductionLifecycleStepV1::RouteCutover,
        CellSplitProductionLifecycleStepV1::Dispatched,
        CellSplitProductionLifecycleStepV1::CleanRestarted,
        CellSplitProductionLifecycleStepV1::ApprovedPowerLoss,
        CellSplitProductionLifecycleStepV1::Recovered,
        CellSplitProductionLifecycleStepV1::RolledBack,
        CellSplitProductionLifecycleStepV1::Tombstoned,
        CellSplitProductionLifecycleStepV1::OldGenerationRejected,
        CellSplitProductionLifecycleStepV1::FutureWindowEvaluated,
        CellSplitProductionLifecycleStepV1::EvidenceSigned,
        CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
        CellSplitProductionLifecycleStepV1::IndependentlyVerified,
    ];
    assert_eq!(steps.len(), 14);
    assert!(steps.windows(2).all(|pair| pair[0] < pair[1]));
}

#[test]
fn error_is_displayable_without_exposing_external_secrets() {
    let error = CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
        input: "observer-signing",
    };
    let rendered = error.to_string();
    assert!(rendered.contains("observer-signing"));
    assert!(!rendered.contains("private"));
}

#[test]
fn canonical_verifier_gate_blocks_unverified_envelope() {
    let mut configuration = config();
    configuration.canonical_packet_verifier_owner = Some(Arc::new(RejectingCanonicalVerifier(
        ProductionOwnerBindingV1 {
            owner_id: "verifier-owner".to_owned(),
            namespace: configuration.namespace.clone(),
            trust_root_digest: configuration.trust_root_digest.clone(),
        },
    )));
    let mut runtime = ProductionTargetHostRuntime::new(configuration);
    runtime.step = Some(CellSplitProductionLifecycleStepV1::IndependentlyVerified);

    assert!(!runtime.verify_canonical_packet_and_signed_envelope());
    assert!(runtime.packet().canonical_verification.is_none());
    let blocked = runtime.blocked_packet();
    assert!(!blocked.production_evidence);
}

#[test]
fn canonical_verifier_gate_accepts_exact_packet() {
    let mut configuration = config();
    configuration.canonical_packet_verifier_owner = Some(Arc::new(AcceptingCanonicalVerifier(
        ProductionOwnerBindingV1 {
            owner_id: "verifier-owner".to_owned(),
            namespace: configuration.namespace.clone(),
            trust_root_digest: configuration.trust_root_digest.clone(),
        },
    )));
    let mut runtime = ProductionTargetHostRuntime::new(configuration);
    runtime.step = Some(CellSplitProductionLifecycleStepV1::IndependentlyVerified);

    assert!(runtime.verify_canonical_packet_and_signed_envelope());
    let verification = runtime
        .packet()
        .canonical_verification
        .as_ref()
        .expect("successful verification is retained");
    assert!(verification.canonical_packet_verified);
    assert!(verification.signed_envelope_verified);
    assert_eq!(verification.canonical_packet_digest.len(), 64);
}

#[test]
fn v1_packet_json_defaults_v2_fields() {
    let packet: CellSplitProductionPacketV1 = serde_json::from_str(&format!(
        r#"{{"schema":"{CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1}"}}"#
    ))
    .expect("legacy packet remains readable");
    assert_eq!(packet.schema, CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1);
    assert!(packet.transient_receipts.taskflow_run_receipt.is_none());
    assert!(packet.canonical_verification.is_none());
}

#[test]
fn v1_blocked_and_lifecycle_json_default_transient_receipts() {
    let blocked: CellSplitProductionBlockedPacketV1 = serde_json::from_str(
        r#"{"schema":"hepta.learning.cell-split.production-target-host-runtime.v1","splitId":"split.test","targetHostId":"host.test","blockedInputs":[],"reason":"blocked","productionEvidence":false}"#,
    )
    .expect("legacy blocked packet remains readable");
    assert!(blocked.transient_receipts.taskflow_run_receipt.is_none());

    let lifecycle: CellSplitProductionLifecycleReceiptV1 = serde_json::from_str(
        r#"{"schema":"hepta.learning.cell-split.production-target-host-runtime.v1","splitId":"split.test","targetHostId":"host.test","finalStep":"independently-verified","receiptChainDigest":"digest","productionEvidence":false,"blockedInputs":[]}"#,
    )
    .expect("legacy lifecycle receipt remains readable");
    assert!(
        lifecycle
            .transient_receipts
            .learning_ledger_witness_receipt
            .is_none()
    );
}

#[derive(Debug)]
struct TransientOwners(ProductionOwnerBindingV1);

impl TaskFlowOwnerHandleV1 for TransientOwners {
    fn binding(&self) -> &ProductionOwnerBindingV1 {
        &self.0
    }

    fn run(
        &self,
        _request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1> {
        Ok(test_receipt(
            "taskflow-run",
            CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
            "run-digest",
            super::ZERO_DIGEST,
        ))
    }

    fn replay(
        &self,
        _request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionTaskFlowReplayReceiptV1, ProductionExternalErrorV1> {
        Ok(ProductionTaskFlowReplayReceiptV1 {
            operation: test_receipt(
                "taskflow-replay",
                CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
                "replay-digest",
                super::ZERO_DIGEST,
            ),
            taskflow: TaskFlowEventChainPacketV1 {
                taskflow_run_digest: "run-digest".to_owned(),
                event_chain_digest: DIGEST_A.to_owned(),
                replay_receipt_digest: DIGEST_B.to_owned(),
                event_count: 1,
            },
        })
    }
}

impl LearningLedgerOwnerHandleV1 for TransientOwners {
    fn binding(&self) -> &ProductionOwnerBindingV1 {
        &self.0
    }

    fn append_witness(
        &self,
        _request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1> {
        Ok(test_receipt(
            "ledger-witness",
            CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
            "ledger-digest",
            super::ZERO_DIGEST,
        ))
    }

    fn replay(
        &self,
        _request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionLedgerReplayReceiptV1, ProductionExternalErrorV1> {
        Ok(ProductionLedgerReplayReceiptV1 {
            operation: test_receipt(
                "ledger-replay",
                CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
                "ledger-replay-digest",
                super::ZERO_DIGEST,
            ),
            frontier: LearningLedgerWitnessFrontierPacketV1 {
                ledger_namespace: "runtime.test".to_owned(),
                predecessor_frontier_digest: DIGEST_A.to_owned(),
                witness_frontier_digest: DIGEST_B.to_owned(),
                replay_receipt_digest: DIGEST_C.to_owned(),
            },
        })
    }
}

fn test_receipt(
    operation_id: &str,
    step: CellSplitProductionLifecycleStepV1,
    receipt_digest: &str,
    predecessor_receipt_digest: &str,
) -> ProductionOwnerOperationReceiptV1 {
    ProductionOwnerOperationReceiptV1 {
        operation_id: operation_id.to_owned(),
        step,
        occurred_at_unix_nanos: 1,
        generation: 8,
        predecessor_receipt_digest: predecessor_receipt_digest.to_owned(),
        artifact_digest: DIGEST_B.to_owned(),
        route_digest: DIGEST_C.to_owned(),
        tombstone_digest: DIGEST_A.to_owned(),
        witness_digest: DIGEST_B.to_owned(),
        receipt_digest: receipt_digest.to_owned(),
    }
}

#[test]
fn replay_step_retains_owner_transient_receipts() {
    let mut configuration = config();
    let binding = ProductionOwnerBindingV1 {
        owner_id: "transient-owner".to_owned(),
        namespace: configuration.namespace.clone(),
        trust_root_digest: configuration.trust_root_digest.clone(),
    };
    configuration.taskflow_owner = Some(Arc::new(TransientOwners(binding.clone())));
    configuration.learning_ledger_owner = Some(Arc::new(TransientOwners(binding)));
    let mut runtime = ProductionTargetHostRuntime::new(configuration);
    runtime.step = Some(CellSplitProductionLifecycleStepV1::EvidenceSigned);

    runtime
        .replay_taskflow_and_ledger()
        .expect("owner replay should complete");

    assert_eq!(
        runtime
            .packet()
            .transient_receipts
            .taskflow_run_receipt
            .as_ref()
            .map(|receipt| receipt.operation_id.as_str()),
        Some("taskflow-run")
    );
    assert_eq!(
        runtime
            .packet()
            .transient_receipts
            .learning_ledger_witness_receipt
            .as_ref()
            .map(|receipt| receipt.operation_id.as_str()),
        Some("ledger-witness")
    );
}

#[test]
fn public_lifecycle_fails_closed_without_external_bindings() {
    let mut runtime = ProductionTargetHostRuntime::new(config());
    let error = runtime
        .run_production_lifecycle()
        .expect_err("unbound production lifecycle must fail closed");
    assert_eq!(
        error,
        CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "artifact" }
    );
    assert_eq!(runtime.phase(), None);
    assert_eq!(
        runtime.blocked_packet().schema,
        CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V2
    );
}

#[test]
fn blocked_packet_retains_transient_owner_receipts() {
    let mut runtime = ProductionTargetHostRuntime::new(config());
    let receipt = |operation_id: &str| ProductionOwnerOperationReceiptV1 {
        operation_id: operation_id.to_owned(),
        step: CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
        occurred_at_unix_nanos: 1,
        generation: 8,
        predecessor_receipt_digest: DIGEST_A.to_owned(),
        artifact_digest: DIGEST_B.to_owned(),
        route_digest: DIGEST_C.to_owned(),
        tombstone_digest: DIGEST_A.to_owned(),
        witness_digest: DIGEST_B.to_owned(),
        receipt_digest: DIGEST_C.to_owned(),
    };
    runtime.packet.transient_receipts.taskflow_run_receipt = Some(receipt("run"));
    runtime
        .packet
        .transient_receipts
        .learning_ledger_witness_receipt = Some(receipt("ledger"));
    runtime
        .packet
        .transient_receipts
        .tombstone_no_resurrection_receipt = Some(receipt("tombstone"));

    let blocked = runtime.blocked_packet();
    assert_eq!(
        blocked.transient_receipts,
        runtime.packet.transient_receipts
    );
}
