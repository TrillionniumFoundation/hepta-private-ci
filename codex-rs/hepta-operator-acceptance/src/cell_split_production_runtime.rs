//! Stateful production lifecycle runtime.

use std::collections::BTreeMap;
use std::fmt;

use crate::CellSplitTargetHostMeasurementV1;
use crate::CellSplitTargetHostOperationReceiptV1;
use crate::CellSplitTargetHostRuntimeV1;

pub use super::cell_split_production_contract::*;

pub struct ProductionTargetHostRuntime {
    pub(crate) config: ProductionTargetHostRuntimeConfig,
    pub(crate) step: Option<CellSplitProductionLifecycleStepV1>,
    pub(crate) receipts:
        BTreeMap<CellSplitProductionLifecycleStepV1, ProductionOwnerOperationReceiptV1>,
    pub(crate) packet: CellSplitProductionPacketV1,
    pub(crate) measurements: Vec<ProductionResourceMeasurementV1>,
    pub(crate) aborted: bool,
}

impl Default for ProductionTargetHostRuntime {
    fn default() -> Self {
        Self::new(ProductionTargetHostRuntimeConfig::default())
    }
}

impl fmt::Debug for ProductionTargetHostRuntime {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionTargetHostRuntime")
            .field("split_id", &self.config.split_id)
            .field("target_host_id", &self.config.target_host_id)
            .field("step", &self.step)
            .field("receipt_count", &self.receipts.len())
            .field("aborted", &self.aborted)
            .finish()
    }
}

impl ProductionTargetHostRuntime {
    #[must_use]
    pub fn new(config: ProductionTargetHostRuntimeConfig) -> Self {
        Self {
            packet: CellSplitProductionPacketV1 {
                schema: CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1.to_string(),
                ..CellSplitProductionPacketV1::default()
            },
            config,
            step: None,
            receipts: BTreeMap::new(),
            measurements: Vec::new(),
            aborted: false,
        }
    }

    pub fn bind(
        config: ProductionTargetHostRuntimeConfig,
    ) -> Result<Self, CellSplitTargetHostRuntimeErrorV1> {
        let runtime = Self::new(config);
        runtime.ensure_bindings()?;
        Ok(runtime)
    }

    #[must_use]
    pub fn phase(&self) -> Option<CellSplitProductionLifecycleStepV1> {
        self.step
    }

    #[must_use]
    pub fn packet(&self) -> &CellSplitProductionPacketV1 {
        &self.packet
    }

    /// Return an explicit blocked packet when deployment-owned inputs are not
    /// connected.  This packet is diagnostic only and never production evidence.
    #[must_use]
    pub fn blocked_packet(&self) -> CellSplitProductionBlockedPacketV1 {
        let mut blocked_inputs = Vec::new();
        let config = &self.config;
        for (name, present) in [
            ("split-id", !config.split_id.is_empty()),
            ("namespace", !config.namespace.is_empty()),
            ("target-host-id", !config.target_host_id.is_empty()),
            ("target-host-nonce", !config.target_host_nonce.is_empty()),
            ("parent-generation", config.parent_generation != 0),
            (
                "child-generation-fence",
                config.child_generation == config.parent_generation.saturating_add(1),
            ),
            (
                "parent-artifact-digest",
                !config.parent_artifact_digest.is_empty(),
            ),
            (
                "child-artifact-digest",
                !config.child_artifact_digest.is_empty(),
            ),
            (
                "parameter-bundle-digest",
                !config.parameter_bundle_digest.is_empty(),
            ),
            ("migration-digest", !config.migration_digest.is_empty()),
            ("trust-root", !config.trust_root_digest.is_empty()),
            (
                "future-window-minimum",
                config.minimum_future_window_samples != 0,
            ),
            ("approved-power-loss", config.approved_power_loss),
        ] {
            if !present {
                blocked_inputs.push(name.to_owned());
            }
        }
        for (name, present) in [
            ("artifact", config.artifact_owner.is_some()),
            ("cns-route", config.route_owner.is_some()),
            ("fault-injector", config.fault_injector.is_some()),
            ("tombstone", config.tombstone_owner.is_some()),
            ("taskflow", config.taskflow_owner.is_some()),
            ("host-telemetry", config.telemetry_owner.is_some()),
            (
                "hardware-attestation",
                config.hardware_attestation_owner.is_some(),
            ),
            ("learning-ledger", config.learning_ledger_owner.is_some()),
            (
                "future-window-evaluator",
                config.future_window_evaluator_owner.is_some(),
            ),
            ("evidence-signing", config.evidence_signing_owner.is_some()),
        ] {
            if !present {
                blocked_inputs.push(name.to_owned());
            }
        }
        CellSplitProductionBlockedPacketV1 {
            schema: CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1.to_owned(),
            split_id: config.split_id.clone(),
            target_host_id: config.target_host_id.clone(),
            reason: if blocked_inputs.is_empty() {
                "owner or receipt validation is blocked".to_owned()
            } else {
                "required external owner/configuration is not bound".to_owned()
            },
            blocked_inputs,
            production_evidence: false,
        }
    }

    /// Abort is durable at the caller's owner boundary; this method only marks
    /// the local state so subsequent calls cannot be mistaken for a retry.
    pub fn abort(&mut self) {
        self.aborted = true;
    }

    pub fn run_production_lifecycle(
        &mut self,
    ) -> Result<CellSplitProductionLifecycleReceiptV1, CellSplitTargetHostRuntimeErrorV1> {
        self.ensure_bindings()?;
        self.bind_owners()?;
        self.load_artifacts()?;
        self.measure_resources()?;
        self.cutover_route()?;
        self.dispatch()?;
        self.clean_restart()?;
        self.approve_power_loss()?;
        self.recover()?;
        self.rollback()?;
        self.tombstone()?;
        self.reject_old_generation()?;
        self.evaluate_future_window()?;
        self.sign_evidence()?;
        self.replay_taskflow_and_ledger()?;
        self.independent_verify()?;
        let final_step =
            self.step
                .ok_or(CellSplitTargetHostRuntimeErrorV1::InvalidConfiguration(
                    "lifecycle did not advance",
                ))?;
        Ok(CellSplitProductionLifecycleReceiptV1 {
            schema: CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1.to_string(),
            split_id: self.config.split_id.clone(),
            target_host_id: self.config.target_host_id.clone(),
            final_step,
            receipt_chain_digest: self.receipt_chain_digest(),
            production_evidence: true,
            blocked_inputs: Vec::new(),
        })
    }
}

impl CellSplitTargetHostRuntimeV1 for ProductionTargetHostRuntime {
    type Error = CellSplitTargetHostRuntimeErrorV1;

    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_bindings()?;
        if self.step.is_none() {
            self.bind_owners()?;
        }
        self.load_artifacts()?;
        let receipt = self
            .receipt(CellSplitProductionLifecycleStepV1::ArtifactsLoaded)?
            .clone();
        Ok(operation_receipt(receipt))
    }

    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.cutover_route()?;
        self.dispatch()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::Dispatched)?
                .clone(),
        ))
    }

    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.clean_restart()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::CleanRestarted)?
                .clone(),
        ))
    }

    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.approve_power_loss()?;
        self.recover()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::Recovered)?
                .clone(),
        ))
    }

    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.rollback()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::RolledBack)?
                .clone(),
        ))
    }

    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.tombstone()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::Tombstoned)?
                .clone(),
        ))
    }

    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.reject_old_generation()?;
        Ok(operation_receipt(
            self.receipt(CellSplitProductionLifecycleStepV1::OldGenerationRejected)?
                .clone(),
        ))
    }

    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        self.ensure_bindings()?;
        if self.step.is_none() {
            self.bind_owners()?;
        }
        if self.step == Some(CellSplitProductionLifecycleStepV1::OwnersBound) {
            self.load_artifacts()?;
        }
        self.measure_resources()?;
        self.measurements
            .iter()
            .map(|measurement| {
                Ok(CellSplitTargetHostMeasurementV1 {
                    operation: operation_receipt(measurement.operation.clone()),
                    sample: measurement.sample.clone(),
                })
            })
            .collect()
    }
}

fn operation_receipt(
    receipt: ProductionOwnerOperationReceiptV1,
) -> CellSplitTargetHostOperationReceiptV1 {
    CellSplitTargetHostOperationReceiptV1 {
        operation_id: receipt.operation_id,
        occurred_at_unix_nanos: receipt.occurred_at_unix_nanos,
        artifact_digest: receipt.artifact_digest,
        route_digest: receipt.route_digest,
        predecessor_digest: receipt.predecessor_receipt_digest,
        tombstone_digest: receipt.tombstone_digest,
        fault_injection_digest: receipt.witness_digest,
        receipt_digest: receipt.receipt_digest,
    }
}

#[cfg(test)]
#[path = "cell_split_production_runtime_tests.rs"]
mod tests;
