//! Bounded execution evidence. DTOs are claims until the actual ledger owner
//! resolves a current independent Outcome with this exact canonical digest.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ProductionLedgerError;

#[path = "procedure_evidence_codec.rs"]
mod codec;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureArtifactV1 {
    pub id: StableId,
    pub content_digest: Digest32,
    pub byte_length: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureArgumentV1 {
    pub name: StableId,
    pub value: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProcedureModelV1 {
    NoModel,
    Artifact(ProcedureArtifactV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureEnvironmentV1 {
    pub runtime: ProcedureArtifactV1,
    pub executable: ProcedureArtifactV1,
    pub model: ProcedureModelV1,
    pub context: Vec<ProcedureArgumentV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureStepV1 {
    pub id: StableId,
    pub operation: StableId,
    pub arguments: Vec<ProcedureArgumentV1>,
    pub input_artifacts: Vec<StableId>,
    pub output_artifacts: Vec<StableId>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcedureCheckResultV1 {
    Unknown,
    Failed,
    Satisfied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureCheckV1 {
    pub id: StableId,
    pub predicate: String,
    pub arguments: Vec<ProcedureArgumentV1>,
    pub observed_at: u64,
    pub result: ProcedureCheckResultV1,
    pub observations: Vec<ProcedureArtifactV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcedureStepDispositionV1 {
    Skipped,
    Failed,
    Completed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureTraceStepV1 {
    pub step_id: StableId,
    pub sequence: u32,
    pub started_at: u64,
    pub finished_at: u64,
    pub disposition: ProcedureStepDispositionV1,
    pub inputs: Vec<ProcedureArtifactV1>,
    pub outputs: Vec<ProcedureArtifactV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureExecutionEvidenceV1 {
    pub procedure_id: StableId,
    pub profile_id: StableId,
    pub decision_record_id: StableId,
    pub episode_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub observer_id: StableId,
    pub environment: ProcedureEnvironmentV1,
    pub checker: ProcedureArtifactV1,
    pub steps: Vec<ProcedureStepV1>,
    pub preconditions: Vec<ProcedureCheckV1>,
    pub success_criteria: Vec<ProcedureCheckV1>,
    pub execution_started_at: u64,
    pub execution_finished_at: u64,
    pub observer_checked_at: u64,
    pub trace: Vec<ProcedureTraceStepV1>,
    pub final_outputs: Vec<ProcedureArtifactV1>,
}

impl ProcedureExecutionEvidenceV1 {
    /// Exact ordered plan, environment, checker and predicate definitions,
    /// without run-specific observations. The Generator and host profile bind it.
    pub fn contract_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        Ok(Digest32::of_bytes(&self.contract_bytes()?))
    }

    pub fn contract_bytes(&self) -> Result<Vec<u8>, ProductionLedgerError> {
        codec::contract(self)
    }

    /// Exactly the bytes whose SHA-256 must equal `Outcome.support_digest`.
    /// The Outcome event digest is excluded, avoiding a circular hash.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, ProductionLedgerError> {
        codec::execution(self)
    }

    pub fn canonical_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        Ok(Digest32::of_bytes(&self.canonical_bytes()?))
    }

    pub(crate) fn validate_successful_execution(&self) -> Result<(), ProductionLedgerError> {
        if self.trace.len() != self.steps.len()
            || self.execution_started_at > self.execution_finished_at
            || self.execution_finished_at > self.observer_checked_at
        {
            return Err(invalid("incomplete procedure trace or execution time"));
        }
        let mut artifacts = BTreeMap::new();
        for artifact in [
            &self.environment.runtime,
            &self.environment.executable,
            &self.checker,
        ] {
            record_artifact(&mut artifacts, artifact)?;
        }
        if let ProcedureModelV1::Artifact(artifact) = &self.environment.model {
            record_artifact(&mut artifacts, artifact)?;
        }
        let mut declared_outputs = BTreeSet::new();
        for step in &self.steps {
            if step.output_artifacts.is_empty()
                || step
                    .output_artifacts
                    .iter()
                    .any(|id| !declared_outputs.insert(id))
            {
                return Err(invalid("procedure output identities must be unique"));
            }
        }
        let mut produced = BTreeSet::new();
        let mut previous_end = self.execution_started_at;
        for (index, (step, trace)) in self.steps.iter().zip(&self.trace).enumerate() {
            if trace.sequence as usize != index + 1
                || trace.step_id != step.id
                || trace.disposition != ProcedureStepDispositionV1::Completed
                || trace.started_at < previous_end
                || trace.started_at > trace.finished_at
                || trace.finished_at > self.execution_finished_at
                || trace
                    .inputs
                    .iter()
                    .map(|a| &a.id)
                    .ne(step.input_artifacts.iter())
                || trace
                    .outputs
                    .iter()
                    .map(|a| &a.id)
                    .ne(step.output_artifacts.iter())
            {
                return Err(invalid("procedure steps and actual trace differ"));
            }
            for artifact in &trace.inputs {
                if declared_outputs.contains(&artifact.id) && !produced.contains(&artifact.id) {
                    return Err(invalid("procedure used output before producing it"));
                }
            }
            for artifact in trace.inputs.iter().chain(&trace.outputs) {
                record_artifact(&mut artifacts, artifact)?;
            }
            produced.extend(trace.outputs.iter().map(|a| &a.id));
            previous_end = trace.finished_at;
        }
        for check in &self.preconditions {
            if check.result != ProcedureCheckResultV1::Satisfied
                || check.observations.is_empty()
                || check.observed_at > self.execution_started_at
            {
                return Err(invalid(
                    "procedure precondition not established before execution",
                ));
            }
        }
        for check in &self.success_criteria {
            if check.result != ProcedureCheckResultV1::Satisfied
                || check.observations.is_empty()
                || check.observed_at < self.execution_finished_at
                || check.observed_at > self.observer_checked_at
            {
                return Err(invalid(
                    "procedure success criterion not independently observed",
                ));
            }
        }
        for artifact in self
            .preconditions
            .iter()
            .chain(&self.success_criteria)
            .flat_map(|check| &check.observations)
        {
            record_artifact(&mut artifacts, artifact)?;
        }
        if self
            .trace
            .last()
            .is_none_or(|trace| trace.outputs != self.final_outputs)
        {
            return Err(invalid(
                "procedure final outputs differ from actual last step",
            ));
        }
        Ok(())
    }
}

fn record_artifact<'a>(
    artifacts: &mut BTreeMap<&'a StableId, &'a ProcedureArtifactV1>,
    artifact: &'a ProcedureArtifactV1,
) -> Result<(), ProductionLedgerError> {
    if artifacts
        .insert(&artifact.id, artifact)
        .is_some_and(|prior| prior != artifact)
    {
        return Err(invalid(
            "procedure artifact identity changed within execution",
        ));
    }
    Ok(())
}

pub(super) fn invalid(reason: &'static str) -> ProductionLedgerError {
    ProductionLedgerError::Binding(reason)
}
