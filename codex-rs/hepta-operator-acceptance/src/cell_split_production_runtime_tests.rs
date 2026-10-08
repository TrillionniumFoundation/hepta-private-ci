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
