//! External-adapter lifecycle runner for DecisionCell target-host evidence.
//!
//! This module is an orchestration seam, not a target-host implementation. A
//! deployment owner supplies [`CellSplitTargetHostRuntimeV1`] with calls that
//! really load the child artifact, perform the CNS route cutover, recover from
//! restart/power loss, roll back, commit the tombstone, and verify that the old
//! generation cannot return. The runner only orders those calls and records
//! their externally returned receipts in the signed-evidence recorder.
//!
//! No method in this module fabricates a CAS commit, route dispatch, hardware
//! counter, fault injection or observer signature. A runtime adapter that
//! returns fixture/simulation receipts will be rejected later by the evidence
//! verifier, and this runner does not issue a production receipt.

use std::fmt::Display;

use thiserror::Error;

use crate::CellSplitTargetHostEventKindV1;
use crate::CellSplitTargetHostEvidenceErrorV1;
use crate::CellSplitTargetHostEvidenceRecorderV1;
use crate::CellSplitTargetHostEvidenceV1;
use crate::CellSplitTargetResourceSampleV1;

pub const CELL_SPLIT_TARGET_HOST_LIFECYCLE_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-lifecycle-runner.v1";

/// Receipt returned by one external target-host operation. The target-host
/// owner must bind these values to its durable artifact/CNS/fault/registry
/// receipt; the runner treats them as observations and never derives them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTargetHostOperationReceiptV1 {
    pub operation_id: String,
    pub occurred_at_unix_nanos: u128,
    pub artifact_digest: String,
    pub route_digest: String,
    pub predecessor_digest: String,
    pub tombstone_digest: String,
    pub fault_injection_digest: String,
    pub receipt_digest: String,
}

/// A hardware measurement paired with the target-host operation that produced
/// it. The sample must contain a non-simulation source and an attestation
/// digest; the evidence verifier applies the final target-host checks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTargetHostMeasurementV1 {
    pub operation: CellSplitTargetHostOperationReceiptV1,
    pub sample: CellSplitTargetResourceSampleV1,
}

/// Runtime owner implemented by the deployment host. Every method must call
/// the real owner and return its immutable receipt. In particular, the
/// `power_loss_recover` method must return a fault-injection witness from the
/// host, rather than a process-level restart result relabeled as power loss.
pub trait CellSplitTargetHostRuntimeV1 {
    type Error: Display;

    fn load_child_artifact(&mut self)
    -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;

    /// Return counters from the actual target host. The implementation may
    /// return one or more CPU/GPU/NPU samples, but an empty vector is rejected.
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error>;
}

/// Errors from the orchestration seam. An external owner failure is retained
/// as text only; it never becomes a production receipt.
#[derive(Debug, Error)]
pub enum CellSplitTargetHostLifecycleErrorV1 {
    #[error("target-host evidence recorder rejected operation: {0}")]
    Recorder(#[from] CellSplitTargetHostEvidenceErrorV1),
    #[error("target-host runtime owner failed: {0}")]
    Runtime(String),
    #[error("target-host runtime returned no resource measurements")]
    MissingResourceMeasurements,
}

/// Runs the externally supplied host lifecycle and returns an unsigned event
/// payload. The caller must pass the payload to the host signer and an
/// independent observer before the production adapter can issue a receipt.
pub struct CellSplitTargetHostLifecycleRunnerV1<R> {
    runtime: R,
    recorder: CellSplitTargetHostEvidenceRecorderV1,
}

impl<R> CellSplitTargetHostLifecycleRunnerV1<R>
where
    R: CellSplitTargetHostRuntimeV1,
{
    #[must_use]
    pub fn new(runtime: R, recorder: CellSplitTargetHostEvidenceRecorderV1) -> Self {
        Self { runtime, recorder }
    }

    /// Execute the required lifecycle in the same order enforced by the
    /// evidence verifier. Resource samples are inserted after artifact load;
    /// their timestamps and counters come from the external owner.
    pub fn run(
        mut self,
    ) -> Result<CellSplitTargetHostEvidenceV1, CellSplitTargetHostLifecycleErrorV1> {
        let load = self.call(CellSplitTargetHostRuntimeV1::load_child_artifact)?;
        self.append(CellSplitTargetHostEventKindV1::ArtifactLoaded, load, None)?;
        self.append_resources()?;

        let route = self.call(CellSplitTargetHostRuntimeV1::route_cutover)?;
        self.append(CellSplitTargetHostEventKindV1::RouteCutover, route, None)?;
        let restart = self.call(CellSplitTargetHostRuntimeV1::restart_recover)?;
        self.append(
            CellSplitTargetHostEventKindV1::RestartRecovered,
            restart,
            None,
        )?;
        let power_loss = self.call(CellSplitTargetHostRuntimeV1::power_loss_recover)?;
        self.append(
            CellSplitTargetHostEventKindV1::PowerLossRecovered,
            power_loss,
            None,
        )?;
        let rollback = self.call(CellSplitTargetHostRuntimeV1::rollback)?;
        self.append(
            CellSplitTargetHostEventKindV1::RollbackCompleted,
            rollback,
            None,
        )?;
        let tombstone = self.call(CellSplitTargetHostRuntimeV1::commit_tombstone)?;
        self.append(
            CellSplitTargetHostEventKindV1::TombstoneCommitted,
            tombstone,
            None,
        )?;
        let no_resurrection = self.call(CellSplitTargetHostRuntimeV1::verify_no_resurrection)?;
        self.append(
            CellSplitTargetHostEventKindV1::NoResurrectionVerified,
            no_resurrection,
            None,
        )?;

        self.recorder.finish().map_err(Into::into)
    }

    fn append_resources(&mut self) -> Result<(), CellSplitTargetHostLifecycleErrorV1> {
        let measurements = self.call(CellSplitTargetHostRuntimeV1::measure_resources)?;
        if measurements.is_empty() {
            return Err(CellSplitTargetHostLifecycleErrorV1::MissingResourceMeasurements);
        }
        for measurement in measurements {
            self.append(
                CellSplitTargetHostEventKindV1::ResourceMeasurement,
                measurement.operation,
                Some(measurement.sample),
            )?;
        }
        Ok(())
    }

    fn append(
        &mut self,
        kind: CellSplitTargetHostEventKindV1,
        operation: CellSplitTargetHostOperationReceiptV1,
        resource: Option<CellSplitTargetResourceSampleV1>,
    ) -> Result<(), CellSplitTargetHostLifecycleErrorV1> {
        let (sequence, previous_event_digest) = self.recorder.next_event_context();
        let event = crate::CellSplitTargetHostEventV1 {
            sequence,
            event_kind: kind,
            occurred_at_unix_nanos: operation.occurred_at_unix_nanos,
            split_id: self.recorder.split_id().to_string(),
            target_host_id: self.recorder.target_host_id().to_string(),
            parent_generation: self.recorder.parent_generation(),
            child_generation: self.recorder.child_generation(),
            operation_id: operation.operation_id,
            artifact_digest: operation.artifact_digest,
            route_digest: operation.route_digest,
            predecessor_digest: operation.predecessor_digest,
            tombstone_digest: operation.tombstone_digest,
            fault_injection_digest: operation.fault_injection_digest,
            receipt_digest: operation.receipt_digest,
            resource,
            previous_event_digest,
            event_digest: String::new(),
        };
        self.recorder.append(event).map_err(Into::into)
    }

    fn call<T, F>(&mut self, operation: F) -> Result<T, CellSplitTargetHostLifecycleErrorV1>
    where
        F: FnOnce(&mut R) -> Result<T, R::Error>,
    {
        operation(&mut self.runtime)
            .map_err(|error| CellSplitTargetHostLifecycleErrorV1::Runtime(error.to_string()))
    }
}

#[cfg(test)]
#[path = "cell_split_target_host_runtime_tests.rs"]
mod tests;
