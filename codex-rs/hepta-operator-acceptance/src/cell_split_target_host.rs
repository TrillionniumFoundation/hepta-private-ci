//! Target-host qualification harness for DecisionCell split lifecycle.
//!
//! The harness is intentionally a source qualification fixture. It exercises
//! fencing, restart/replay, rollback and no-resurrection invariants using a
//! durable JSON report, but it cannot claim that a production host, hardware
//! fault injector, CNS deployment or signed external observer ran the path.

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use thiserror::Error;

const SCHEMA: &str = "hepta.learning.cell-split.target-host-qualification.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CellSplitQualificationOriginV1 {
    SourceSimulation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CellSplitQualificationStateV1 {
    Proposed,
    Canary,
    Retained,
    Quarantined,
    Retired,
    RolledBack,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CellSplitTargetHostQualificationReportV1 {
    pub schema: String,
    pub origin: CellSplitQualificationOriginV1,
    pub split_id: String,
    pub target_host_id: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub state: CellSplitQualificationStateV1,
    pub dispatch_receipt_digest: String,
    pub old_route_fence_digest: String,
    pub restart_receipt_digest: String,
    pub rollback_receipt_digest: String,
    pub tombstone_digest: String,
    pub resource_budget_units: u64,
    pub resource_observed_units: u64,
    pub gates: CellSplitTargetHostGatesV1,
    pub production_evidence: bool,
    pub production_activation_authorized: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CellSplitTargetHostGatesV1 {
    pub child_artifact_load: bool,
    pub route_dispatch_receipt: bool,
    pub restart_recovery: bool,
    pub rollback_to_predecessor: bool,
    pub no_resurrection: bool,
    pub resource_budget: bool,
    pub external_observer_attested: bool,
    pub hardware_fault_injected: bool,
}

#[derive(Debug, Error)]
pub enum CellSplitTargetHostErrorV1 {
    #[error("invalid target-host fixture: {0}")]
    Invalid(&'static str),
    #[error("target-host report I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("target-host report encoding failed: {0}")]
    Encoding(#[from] serde_json::Error),
}

#[derive(Clone, Debug)]
pub struct CellSplitTargetHostHarnessV1 {
    report: CellSplitTargetHostQualificationReportV1,
    lifecycle_counter: u64,
    retired: bool,
    quarantined: bool,
}

impl CellSplitTargetHostHarnessV1 {
    pub fn new(
        split_id: impl Into<String>,
        target_host_id: impl Into<String>,
        parent_generation: u64,
        child_generation: u64,
        resource_budget_units: u64,
    ) -> Result<Self, CellSplitTargetHostErrorV1> {
        let split_id = split_id.into();
        let target_host_id = target_host_id.into();
        if split_id.is_empty()
            || target_host_id.is_empty()
            || parent_generation == 0
            || child_generation != parent_generation.saturating_add(1)
            || resource_budget_units == 0
        {
            return Err(CellSplitTargetHostErrorV1::Invalid(
                "identity/generation/budget",
            ));
        }
        Ok(Self {
            report: CellSplitTargetHostQualificationReportV1 {
                schema: SCHEMA.to_string(),
                origin: CellSplitQualificationOriginV1::SourceSimulation,
                split_id,
                target_host_id,
                parent_generation,
                child_generation,
                state: CellSplitQualificationStateV1::Proposed,
                dispatch_receipt_digest: String::new(),
                old_route_fence_digest: String::new(),
                restart_receipt_digest: String::new(),
                rollback_receipt_digest: String::new(),
                tombstone_digest: String::new(),
                resource_budget_units,
                resource_observed_units: 0,
                gates: CellSplitTargetHostGatesV1 {
                    child_artifact_load: false,
                    route_dispatch_receipt: false,
                    restart_recovery: false,
                    rollback_to_predecessor: false,
                    no_resurrection: false,
                    resource_budget: false,
                    external_observer_attested: false,
                    hardware_fault_injected: false,
                },
                production_evidence: false,
                production_activation_authorized: false,
            },
            lifecycle_counter: 0,
            retired: false,
            quarantined: false,
        })
    }

    #[must_use]
    pub fn report(&self) -> &CellSplitTargetHostQualificationReportV1 {
        &self.report
    }

    pub fn load_child_artifact(
        &mut self,
        artifact_digest: &str,
    ) -> Result<(), CellSplitTargetHostErrorV1> {
        if artifact_digest.is_empty() {
            return Err(CellSplitTargetHostErrorV1::Invalid("child artifact"));
        }
        self.report.gates.child_artifact_load = true;
        Ok(())
    }

    pub fn dispatch(
        &mut self,
        old_route_digest: &str,
        child_route_digest: &str,
        observed_resource_units: u64,
    ) -> Result<(), CellSplitTargetHostErrorV1> {
        if self.report.state != CellSplitQualificationStateV1::Proposed
            || old_route_digest.is_empty()
            || child_route_digest.is_empty()
            || !self.report.gates.child_artifact_load
            || observed_resource_units > self.report.resource_budget_units
        {
            return Err(CellSplitTargetHostErrorV1::Invalid("dispatch precondition"));
        }
        self.report.old_route_fence_digest = hex_digest(old_route_digest.as_bytes());
        self.report.dispatch_receipt_digest = hex_digest(
            format!(
                "dispatch:{}:{}:{}",
                self.report.split_id, old_route_digest, child_route_digest
            )
            .as_bytes(),
        );
        self.report.resource_observed_units = observed_resource_units;
        self.report.gates.route_dispatch_receipt = true;
        self.report.gates.resource_budget = true;
        self.report.state = CellSplitQualificationStateV1::Canary;
        self.lifecycle_counter = self.lifecycle_counter.saturating_add(1);
        Ok(())
    }

    pub fn restart(&mut self) -> Result<(), CellSplitTargetHostErrorV1> {
        if self.report.dispatch_receipt_digest.is_empty() {
            return Err(CellSplitTargetHostErrorV1::Invalid(
                "restart before dispatch",
            ));
        }
        self.report.restart_receipt_digest = hex_digest(
            format!(
                "restart:{}:{}:{}",
                self.report.split_id, self.report.dispatch_receipt_digest, self.lifecycle_counter
            )
            .as_bytes(),
        );
        self.report.gates.restart_recovery = true;
        Ok(())
    }

    pub fn retain(&mut self) -> Result<(), CellSplitTargetHostErrorV1> {
        if self.report.state != CellSplitQualificationStateV1::Canary
            || !self.report.gates.restart_recovery
            || !self.report.gates.route_dispatch_receipt
        {
            return Err(CellSplitTargetHostErrorV1::Invalid("retain precondition"));
        }
        self.report.state = CellSplitQualificationStateV1::Retained;
        Ok(())
    }

    pub fn rollback(&mut self) -> Result<(), CellSplitTargetHostErrorV1> {
        if !matches!(
            self.report.state,
            CellSplitQualificationStateV1::Canary | CellSplitQualificationStateV1::Retained
        ) {
            return Err(CellSplitTargetHostErrorV1::Invalid("rollback state"));
        }
        self.report.rollback_receipt_digest = hex_digest(
            format!(
                "rollback:{}:{}",
                self.report.split_id, self.report.old_route_fence_digest
            )
            .as_bytes(),
        );
        self.report.gates.rollback_to_predecessor = true;
        self.report.state = CellSplitQualificationStateV1::RolledBack;
        self.report.gates.no_resurrection = !self.try_resurrect();
        Ok(())
    }

    pub fn quarantine(&mut self) -> Result<(), CellSplitTargetHostErrorV1> {
        if !matches!(
            self.report.state,
            CellSplitQualificationStateV1::Canary | CellSplitQualificationStateV1::Retained
        ) {
            return Err(CellSplitTargetHostErrorV1::Invalid("quarantine state"));
        }
        self.quarantined = true;
        self.report.state = CellSplitQualificationStateV1::Quarantined;
        self.report.gates.no_resurrection = !self.try_resurrect();
        Ok(())
    }

    pub fn retire(&mut self) -> Result<(), CellSplitTargetHostErrorV1> {
        if self.report.state != CellSplitQualificationStateV1::Retained {
            return Err(CellSplitTargetHostErrorV1::Invalid("retire state"));
        }
        self.report.tombstone_digest = hex_digest(
            format!(
                "tombstone:{}:{}",
                self.report.split_id, self.report.child_generation
            )
            .as_bytes(),
        );
        self.retired = true;
        self.report.state = CellSplitQualificationStateV1::Retired;
        self.report.gates.no_resurrection = !self.try_resurrect();
        Ok(())
    }

    #[must_use]
    pub fn try_resurrect(&self) -> bool {
        !self.retired
            && !self.quarantined
            && self.report.state != CellSplitQualificationStateV1::RolledBack
    }

    pub fn persist(&self, path: &Path) -> Result<(), CellSplitTargetHostErrorV1> {
        let bytes = serde_json::to_vec_pretty(&self.report)?;
        let temporary = path.with_extension("tmp");
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        if let Some(parent) = path.parent() {
            File::open(parent)?.sync_all()?;
        }
        Ok(())
    }

    pub fn reopen(path: &Path) -> Result<Self, CellSplitTargetHostErrorV1> {
        let report: CellSplitTargetHostQualificationReportV1 =
            serde_json::from_slice(&fs::read(path)?)?;
        if report.schema != SCHEMA
            || report.origin != CellSplitQualificationOriginV1::SourceSimulation
            || report.production_evidence
            || report.production_activation_authorized
            || report.gates.external_observer_attested
            || report.gates.hardware_fault_injected
            || report.split_id.is_empty()
            || report.target_host_id.is_empty()
            || report.parent_generation == 0
            || report.child_generation != report.parent_generation.saturating_add(1)
            || (report.state == CellSplitQualificationStateV1::Retired
                && report.tombstone_digest.is_empty())
            || (report.state == CellSplitQualificationStateV1::RolledBack
                && report.rollback_receipt_digest.is_empty())
        {
            return Err(CellSplitTargetHostErrorV1::Invalid("report schema/origin"));
        }
        let retired = report.state == CellSplitQualificationStateV1::Retired;
        let quarantined = report.state == CellSplitQualificationStateV1::Quarantined;
        Ok(Self {
            report,
            lifecycle_counter: 0,
            retired,
            quarantined,
        })
    }
}

fn hex_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(test)]
#[path = "cell_split_target_host_tests.rs"]
mod tests;
