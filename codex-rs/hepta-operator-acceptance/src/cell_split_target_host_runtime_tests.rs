use super::*;
use crate::CellSplitTargetHardwareV1;
use crate::CellSplitTargetHostEventKindV1;
use std::fmt;

const PARENT: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const CHILD: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const ATTESTATION: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const TOMBSTONE: &str = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";

#[derive(Debug)]
struct FakeError(&'static str);
impl fmt::Display for FakeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

struct FakeRuntime {
    next_timestamp: u128,
    calls: Vec<&'static str>,
}
impl FakeRuntime {
    fn new() -> Self {
        Self {
            next_timestamp: 1_700_000_000_000_000_000,
            calls: Vec::new(),
        }
    }
    fn operation(&mut self, name: &'static str) -> CellSplitTargetHostOperationReceiptV1 {
        self.calls.push(name);
        self.next_timestamp += 1;
        let n = self.calls.len();
        CellSplitTargetHostOperationReceiptV1 {
            operation_id: format!("operation-{n}"),
            occurred_at_unix_nanos: self.next_timestamp,
            artifact_digest: if name == "load" {
                CHILD.to_string()
            } else {
                String::new()
            },
            route_digest: if name == "route" {
                "route-child".to_string()
            } else {
                String::new()
            },
            predecessor_digest: matches!(name, "route" | "rollback" | "resurrection")
                .then(|| "route-parent-fence".to_string())
                .unwrap_or_default(),
            tombstone_digest: matches!(name, "tombstone" | "resurrection")
                .then(|| TOMBSTONE.to_string())
                .unwrap_or_default(),
            fault_injection_digest: if name == "power-loss" {
                ATTESTATION.to_string()
            } else {
                String::new()
            },
            receipt_digest: format!("receipt-{n}"),
        }
    }
}
impl CellSplitTargetHostRuntimeV1 for FakeRuntime {
    type Error = FakeError;
    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("load"))
    }
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("route"))
    }
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("restart"))
    }
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("power-loss"))
    }
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("rollback"))
    }
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("tombstone"))
    }
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("resurrection"))
    }
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        Ok(vec![CellSplitTargetHostMeasurementV1 {
            operation: self.operation("resource"),
            sample: crate::CellSplitTargetResourceSampleV1 {
                hardware: CellSplitTargetHardwareV1::Cpu,
                hardware_model: "externally-reported-cpu".to_string(),
                measurement_source: "external-counter".to_string(),
                hardware_attestation_digest: ATTESTATION.to_string(),
                sample_count: 1,
                latency_micros: 1,
                memory_bytes: 1,
                communication_bytes: 1,
                training_micros: 1,
                migration_micros: 1,
            },
        }])
    }
}

fn recorder() -> CellSplitTargetHostEvidenceRecorderV1 {
    CellSplitTargetHostEvidenceRecorderV1::new(
        "split.runner.1",
        "host.external.1",
        "nonce.runner.1",
        ATTESTATION,
        7,
        8,
        PARENT,
        CHILD,
    )
    .expect("recorder")
}

#[test]
fn runner_orders_external_lifecycle_and_returns_unsigned_payload() {
    let payload = CellSplitTargetHostLifecycleRunnerV1::new(FakeRuntime::new(), recorder())
        .run()
        .expect("lifecycle");
    assert_eq!(payload.origin, "production-target-host");
    assert_eq!(payload.events.len(), 8);
    assert_eq!(
        payload
            .events
            .iter()
            .map(|event| event.event_kind)
            .collect::<Vec<_>>(),
        vec![
            CellSplitTargetHostEventKindV1::ArtifactLoaded,
            CellSplitTargetHostEventKindV1::ResourceMeasurement,
            CellSplitTargetHostEventKindV1::RouteCutover,
            CellSplitTargetHostEventKindV1::RestartRecovered,
            CellSplitTargetHostEventKindV1::PowerLossRecovered,
            CellSplitTargetHostEventKindV1::RollbackCompleted,
            CellSplitTargetHostEventKindV1::TombstoneCommitted,
            CellSplitTargetHostEventKindV1::NoResurrectionVerified,
        ]
    );
    assert_eq!(payload.events[0].artifact_digest, CHILD);
    assert_eq!(payload.events[4].fault_injection_digest, ATTESTATION);
    assert_eq!(payload.events[6].tombstone_digest, TOMBSTONE);
    assert_eq!(payload.evidence_digest.len(), 64);
}

struct EmptyRuntime;
impl CellSplitTargetHostRuntimeV1 for EmptyRuntime {
    type Error = FakeError;
    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Err(FakeError("no deployment owner"))
    }
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        unreachable!()
    }
}

#[test]
fn missing_external_owner_fails_before_any_production_payload_is_finished() {
    let error = CellSplitTargetHostLifecycleRunnerV1::new(EmptyRuntime, recorder())
        .run()
        .expect_err("deployment owner is required");
    assert!(error.to_string().contains("no deployment owner"));
}
