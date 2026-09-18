//! Product objective admission and durable run-start publication.
//!
//! This facade sequences owner APIs but owns no durable facts. The caller
//! injects a sealed learning.ledger durable journal; successful publication is
//! one synced RunStart event. No model/tool/effect authority is created here.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::RunStartPublicationV1;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveConflictReceipt;
use codex_hepta_objective::ObjectiveFunctionV1;
use codex_hepta_objective::ObjectiveProjectionError;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::RunStartSnapshotError;
use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::project_objective_function_v1;
use codex_hepta_objective::validate_compiled_objective_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const HOST_ENVELOPE_DIGEST_DOMAIN: &[u8] = b"hepta.intelligence.host-envelope.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionRunBindingsV1 {
    pub record_id: StableId,
    pub run_id: StableId,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub runtime_body_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
    /// Exact predecessor of this durable record. An exact retry supplies the
    /// same predecessor as the original append.
    pub expected_ledger_predecessor: Digest32,
}

/// Minimal digest-bound handoff consumed by the runtime host.
///
/// Full objective/admission facts remain in the durable owner record and the
/// product publication receipt. Agentd receives only the frozen RunStart
/// binding, admission lineage and durable chain evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_start: RunStartSnapshotV1,
    pub profile_digest: Digest32,
    pub intent_digest: Digest32,
    pub admitted_source_digest: Digest32,
    pub runtime_body_digest: Digest32,
    pub deadline_unix_micros: Option<u64>,
    pub durable_sequence: u64,
    pub durable_event_digest: Digest32,
    pub durable_chain_digest: Digest32,
    pub run_start_digest: Digest32,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl IntelligenceHostEnvelopeV1 {
    pub fn validate(&self) -> Result<(), ProductionObjectiveError> {
        if self.authority.grants_any() {
            return Err(ProductionObjectiveError::AuthorityEscalation);
        }
        for (field, digest) in [
            ("profile", self.profile_digest),
            ("intent", self.intent_digest),
            ("admitted source", self.admitted_source_digest),
            ("runtime body", self.runtime_body_digest),
            ("durable event", self.durable_event_digest),
            ("durable chain", self.durable_chain_digest),
            ("run start", self.run_start_digest),
        ] {
            if digest.is_zero() {
                return Err(ProductionObjectiveError::EmptyHostDigest(field));
            }
        }
        if self.durable_sequence == 0 {
            return Err(ProductionObjectiveError::InvalidDurableSequence);
        }
        if self.run_start.digest() != self.run_start_digest {
            return Err(ProductionObjectiveError::RunStartDigestMismatch);
        }
        if self.envelope_digest != envelope_digest(self) {
            return Err(ProductionObjectiveError::EnvelopeDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionObjectiveStartReceiptV1 {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub objective_v1: ObjectiveFunctionV1,
    pub objective_v1_digest: Digest32,
    pub run_start: RunStartSnapshotV1,
    pub durable_append: AppendReceipt,
    pub host_envelope: IntelligenceHostEnvelopeV1,
}

impl ProductionObjectiveStartReceiptV1 {
    pub fn validate(&self) -> Result<(), ProductionObjectiveError> {
        if self.objective_admission.authority.grants_any() {
            return Err(ProductionObjectiveError::AuthorityEscalation);
        }
        if self.objective.disposition != CompileDisposition::Compiled {
            return Err(ProductionObjectiveError::InvalidPublishedDisposition);
        }
        validate_compiled_objective_v1(&self.objective.objective)
            .map_err(ProductionObjectiveError::CompiledObjective)?;
        let canonical_digest = self
            .objective_v1
            .digest()
            .map_err(ProductionObjectiveError::Projection)?;
        if canonical_digest != self.objective_v1_digest {
            return Err(ProductionObjectiveError::HostBindingMismatch);
        }
        self.run_start
            .validate_for_objective(&self.objective.objective, canonical_digest)
            .map_err(ProductionObjectiveError::RunStart)?;
        if self.objective.objective.source_digest
            != self.objective_admission.admitted_source_digest
        {
            return Err(ProductionObjectiveError::AdmissionBindingMismatch);
        }
        if self.host_envelope.run_start != self.run_start
            || self.host_envelope.profile_digest != self.objective_admission.profile_digest
            || self.host_envelope.intent_digest != self.objective_admission.intent_digest
            || self.host_envelope.admitted_source_digest
                != self.objective_admission.admitted_source_digest
            || self.host_envelope.deadline_unix_micros
                != self.objective_admission.deadline_unix_micros
            || self.host_envelope.durable_sequence != self.durable_append.sequence.get()
            || self.host_envelope.durable_event_digest != self.durable_append.event_digest
            || self.host_envelope.durable_chain_digest != self.durable_append.chain_digest
        {
            return Err(ProductionObjectiveError::HostBindingMismatch);
        }
        self.host_envelope.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionObjectiveDispositionV1 {
    Published(ProductionObjectiveStartReceiptV1),
    Conflict {
        admission: ObjectiveAdmissionReceiptV1,
        conflict: ObjectiveConflictReceipt,
    },
    ExplicitAbstain {
        admission: ObjectiveAdmissionReceiptV1,
        compile: ObjectiveCompileReceipt,
    },
}

#[derive(Debug)]
pub enum ProductionObjectiveError {
    Admission(ObjectiveAdmissionError),
    Projection(ObjectiveProjectionError),
    RunStart(RunStartSnapshotError),
    CompiledObjective(codex_hepta_objective::ObjectiveError),
    Durable(DurableLedgerError),
    AuthorityEscalation,
    InvalidPublishedDisposition,
    AdmissionBindingMismatch,
    HostBindingMismatch,
    EmptyHostDigest(&'static str),
    InvalidDurableSequence,
    RunStartDigestMismatch,
    EnvelopeDigestMismatch,
}

impl fmt::Display for ProductionObjectiveError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Admission(error) => write!(formatter, "objective admission failed: {error}"),
            Self::Projection(error) => write!(formatter, "objective V1 projection failed: {error}"),
            Self::RunStart(error) => write!(formatter, "run-start binding failed: {error}"),
            Self::CompiledObjective(error) => {
                write!(formatter, "compiled objective validation failed: {error}")
            }
            Self::Durable(error) => write!(formatter, "durable run-start publication failed: {error}"),
            Self::AuthorityEscalation => formatter.write_str("objective host envelope grants authority"),
            Self::InvalidPublishedDisposition => {
                formatter.write_str("published objective is not a compiled disposition")
            }
            Self::AdmissionBindingMismatch => {
                formatter.write_str("published objective is not bound to admitted source")
            }
            Self::HostBindingMismatch => {
                formatter.write_str("runtime host envelope differs from durable publication receipt")
            }
            Self::EmptyHostDigest(field) => write!(formatter, "host envelope {field} digest is zero"),
            Self::InvalidDurableSequence => formatter.write_str("host envelope durable sequence is zero"),
            Self::RunStartDigestMismatch => formatter.write_str("host envelope run-start digest mismatch"),
            Self::EnvelopeDigestMismatch => formatter.write_str("objective host envelope digest mismatch"),
        }
    }
}

impl StdError for ProductionObjectiveError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::Projection(error) => Some(error),
            Self::RunStart(error) => Some(error),
            Self::CompiledObjective(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::AuthorityEscalation
            | Self::InvalidPublishedDisposition
            | Self::AdmissionBindingMismatch
            | Self::HostBindingMismatch
            | Self::EmptyHostDigest(_)
            | Self::InvalidDurableSequence
            | Self::RunStartDigestMismatch
            | Self::EnvelopeDigestMismatch => None,
        }
    }
}

/// Authenticate, compile and atomically publish one product run start.
///
/// Conflict and explicit-abstain outcomes are returned without appending a
/// runnable snapshot. A successful compile is first revalidated, then the
/// immutable objective and RunStart snapshot are committed together through the
/// injected durable learning-ledger owner port.
pub fn prepare_intelligence_run_v1<J: DurableLearningJournal>(
    journal: &mut J,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ProductionRunBindingsV1,
) -> Result<ProductionObjectiveDispositionV1, ProductionObjectiveError> {
    if bindings.runtime_body_digest.is_zero() {
        return Err(ProductionObjectiveError::EmptyHostDigest("runtime body"));
    }
    let outcome = admit_and_compile_objective_v1(source, profile, context)
        .map_err(ProductionObjectiveError::Admission)?;
    let compile = match &outcome.compile_result {
        Ok(compile) => compile.clone(),
        Err(conflict) => {
            return Ok(ProductionObjectiveDispositionV1::Conflict {
                admission: outcome.receipt,
                conflict: conflict.clone(),
            });
        }
    };
    if compile.disposition == CompileDisposition::ExplicitAbstain {
        return Ok(ProductionObjectiveDispositionV1::ExplicitAbstain {
            admission: outcome.receipt,
            compile,
        });
    }

    validate_compiled_objective_v1(&compile.objective)
        .map_err(ProductionObjectiveError::CompiledObjective)?;
    let objective_v1 =
        project_objective_function_v1(source, &outcome).map_err(ProductionObjectiveError::Projection)?;
    let objective_v1_json = objective_v1
        .canonical_json()
        .map_err(ProductionObjectiveError::Projection)?;
    let objective_v1_digest = objective_v1
        .digest()
        .map_err(ProductionObjectiveError::Projection)?;
    let admission = outcome.receipt;
    let run_start = RunStartSnapshotV1::bind(
        bindings.run_id,
        &compile.objective,
        objective_v1_digest,
        bindings.preference_state_digest,
        bindings.model_tuple_digest,
        bindings.prompt_registry_digest,
        bindings.artifact_set_digest,
        bindings.authority_epoch,
        bindings.generation,
        bindings.fence_digest,
    )
    .map_err(ProductionObjectiveError::RunStart)?;

    let event = LedgerEvent::RunStart(Box::new(RunStartPublicationV1 {
        record_id: bindings.record_id,
        objective_v1_json,
        objective_v1_digest,
        runtime_body_digest: bindings.runtime_body_digest,
        admission: admission.clone(),
        compile: compile.clone(),
        run_start: run_start.clone(),
    }));
    let durable_append = journal
        .append(bindings.expected_ledger_predecessor, event)
        .map_err(ProductionObjectiveError::Durable)?;

    let mut host_envelope = IntelligenceHostEnvelopeV1 {
        run_start: run_start.clone(),
        profile_digest: admission.profile_digest,
        intent_digest: admission.intent_digest,
        admitted_source_digest: admission.admitted_source_digest,
        runtime_body_digest: bindings.runtime_body_digest,
        deadline_unix_micros: admission.deadline_unix_micros,
        durable_sequence: durable_append.sequence.get(),
        durable_event_digest: durable_append.event_digest,
        durable_chain_digest: durable_append.chain_digest,
        run_start_digest: run_start.digest(),
        envelope_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    host_envelope.envelope_digest = envelope_digest(&host_envelope);

    let receipt = ProductionObjectiveStartReceiptV1 {
        objective_admission: admission,
        objective: compile,
        run_start,
        objective_v1,
        objective_v1_digest,
        durable_append,
        host_envelope,
    };
    receipt.validate()?;
    Ok(ProductionObjectiveDispositionV1::Published(receipt))
}

fn envelope_digest(value: &IntelligenceHostEnvelopeV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(HOST_ENVELOPE_DIGEST_DOMAIN);
    push_id(&mut bytes, &value.run_start.run_id);
    for digest in [
        value.profile_digest,
        value.intent_digest,
        value.admitted_source_digest,
        value.runtime_body_digest,
        value.run_start.objective_digest,
        value.run_start.hard_constraint_digest,
        value.run_start.preference_state_digest,
        value.run_start.model_tuple_digest,
        value.run_start.prompt_registry_digest,
        value.run_start.artifact_set_digest,
        value.run_start.fence_digest,
        value.durable_event_digest,
        value.durable_chain_digest,
        value.run_start_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&value.run_start.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.run_start.generation.to_be_bytes());
    match value.deadline_unix_micros {
        Some(deadline) => {
            bytes.push(1);
            bytes.extend_from_slice(&deadline.to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&value.durable_sequence.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "production_objective_tests.rs"]
mod tests;
