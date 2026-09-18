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
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::RunStartSnapshotError;
use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
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
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
    /// Exact current durable ledger head supplied by the ledger owner.
    pub expected_ledger_predecessor: Digest32,
}

/// Digest-bound product handoff consumed by the runtime host.
///
/// The envelope contains no grant. Its authority posture is always DENY_ALL;
/// effect authorization remains a separate kernel boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub run_start: RunStartSnapshotV1,
    pub durable_append: AppendReceipt,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl IntelligenceHostEnvelopeV1 {
    pub fn validate(&self) -> Result<(), ProductionObjectiveError> {
        if self.authority.grants_any() || self.objective_admission.authority.grants_any() {
            return Err(ProductionObjectiveError::AuthorityEscalation);
        }
        if self.objective.disposition != CompileDisposition::Compiled {
            return Err(ProductionObjectiveError::InvalidPublishedDisposition);
        }
        validate_compiled_objective_v1(&self.objective.objective)
            .map_err(ProductionObjectiveError::CompiledObjective)?;
        self.run_start
            .validate_for_objective(&self.objective.objective)
            .map_err(ProductionObjectiveError::RunStart)?;
        if self.objective.objective.source_digest
            != self.objective_admission.admitted_source_digest
        {
            return Err(ProductionObjectiveError::AdmissionBindingMismatch);
        }
        if self.envelope_digest != envelope_digest(self) {
            return Err(ProductionObjectiveError::EnvelopeDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionObjectiveDispositionV1 {
    Published(IntelligenceHostEnvelopeV1),
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
    RunStart(RunStartSnapshotError),
    CompiledObjective(codex_hepta_objective::ObjectiveError),
    Durable(DurableLedgerError),
    AuthorityEscalation,
    InvalidPublishedDisposition,
    AdmissionBindingMismatch,
    EnvelopeDigestMismatch,
}

impl fmt::Display for ProductionObjectiveError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Admission(error) => write!(formatter, "objective admission failed: {error}"),
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
            Self::EnvelopeDigestMismatch => formatter.write_str("objective host envelope digest mismatch"),
        }
    }
}

impl StdError for ProductionObjectiveError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::RunStart(error) => Some(error),
            Self::CompiledObjective(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::AuthorityEscalation
            | Self::InvalidPublishedDisposition
            | Self::AdmissionBindingMismatch
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
    let outcome = admit_and_compile_objective_v1(source, profile, context)
        .map_err(ProductionObjectiveError::Admission)?;
    let admission = outcome.receipt;
    let compile = match outcome.compile_result {
        Ok(compile) => compile,
        Err(conflict) => {
            return Ok(ProductionObjectiveDispositionV1::Conflict {
                admission,
                conflict,
            });
        }
    };
    if compile.disposition == CompileDisposition::ExplicitAbstain {
        return Ok(ProductionObjectiveDispositionV1::ExplicitAbstain {
            admission,
            compile,
        });
    }

    validate_compiled_objective_v1(&compile.objective)
        .map_err(ProductionObjectiveError::CompiledObjective)?;
    let run_start = RunStartSnapshotV1::bind(
        bindings.run_id,
        &compile.objective,
        bindings.preference_state_digest,
        bindings.model_tuple_digest,
        bindings.prompt_registry_digest,
        bindings.artifact_set_digest,
        bindings.authority_epoch,
        bindings.generation,
        bindings.fence_digest,
    )
    .map_err(ProductionObjectiveError::RunStart)?;

    let event = LedgerEvent::RunStart(RunStartPublicationV1 {
        record_id: bindings.record_id,
        admission: admission.clone(),
        compile: compile.clone(),
        run_start: run_start.clone(),
    });
    let durable_append = journal
        .append(bindings.expected_ledger_predecessor, event)
        .map_err(ProductionObjectiveError::Durable)?;

    let mut envelope = IntelligenceHostEnvelopeV1 {
        objective_admission: admission,
        objective: compile,
        run_start,
        durable_append,
        envelope_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    envelope.envelope_digest = envelope_digest(&envelope);
    envelope.validate()?;
    Ok(ProductionObjectiveDispositionV1::Published(envelope))
}

fn envelope_digest(value: &IntelligenceHostEnvelopeV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(HOST_ENVELOPE_DIGEST_DOMAIN);
    push_id(&mut bytes, &value.run_start.run_id);
    for digest in [
        value.objective_admission.profile_digest,
        value.objective_admission.intent_digest,
        value.objective_admission.admitted_source_digest,
        value.objective.objective.semantic_digest,
        value.objective.objective.hard_constraint_digest,
        value.run_start.digest(),
        value.durable_append.event_digest,
        value.durable_append.chain_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&value.durable_append.sequence.get().to_be_bytes());
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
