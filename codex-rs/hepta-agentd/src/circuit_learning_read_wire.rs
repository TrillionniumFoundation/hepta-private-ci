//! Private, canonical fixed-mode records. No request uploads an observation.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCircuitLearningReadContextV1 as Context;
use super::OriginalCircuitLearningReadbackV1 as Readback;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-circuit.current-read.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Mode { Selection, NextUse }

impl Mode {
    fn name(self) -> &'static [u8] {
        match self { Self::Selection => b"selection", Self::NextUse => b"next_use" }
    }
}

pub(super) fn mode(context: &Context) -> Result<Mode, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(context.prefix.clone())?;
    context.scope.validate_snapshot(&context.prefix)?;
    if context.prefix.receipts.len() < 3
        || !matches!(context.prefix.receipts[2].observation,
            LearningIterationObservationV1::TrainingNoUpdateV2(_))
        || coordinator.next_task_bundle() != Some(&context.prefix.request.selected_bundle)
    {
        return Err(Error::Binding("only original TrainingNoUpdate read profile"));
    }
    match (context.prefix.receipts.len(), coordinator.next_stage(),
        context.selection_evidence.as_ref())
    {
        (3, Some(LearningIterationStageV1::Selection), None) => Ok(Mode::Selection),
        (4, Some(LearningIterationStageV1::NextUse), Some(_)) => Ok(Mode::NextUse),
        _ => Err(Error::Binding("exact original published read prefix")),
    }
}

pub(super) fn context_binding(context: &Context, at: u64) -> Result<Digest32, Error> {
    let mode = mode(context)?;
    let snapshot = &context.prefix;
    if snapshot.owners.evidence_trust_digest != context.verifier.trust_digest()
        || snapshot.request.envelope.objective_digest != context.verifier.objective_digest()
    {
        return Err(Error::Binding("original published read trust"));
    }
    let training_receipt = &snapshot.receipts[2];
    let training = context.verifier.verify(
        LearningEvidenceRoleV1::Generator, &context.training_evidence,
        &learning_iteration_receipt_signing_bytes_v1(training_receipt)?, at,
    )?;
    if training.principal().principal_id != training_receipt.actor_id {
        return Err(Error::Binding("original Generator read binding"));
    }
    let mut signatures = context.training_evidence.signing_bytes();
    signatures.extend_from_slice(&context.training_evidence.signature);
    if let Some(original) = &context.selection_evidence {
        let selection_receipt = &snapshot.receipts[3];
        let selection = context.verifier.verify(
            LearningEvidenceRoleV1::Selector, original,
            &learning_iteration_receipt_signing_bytes_v1(selection_receipt)?, at,
        )?;
        if selection.principal().principal_id != selection_receipt.actor_id {
            return Err(Error::Binding("original Selector read binding"));
        }
        verify_signed_actor_separation(&training, &selection, at)?;
        signatures.extend_from_slice(&original.signing_bytes());
        signatures.extend_from_slice(&original.signature);
    }
    // scope.binding() commits every field of the already-frozen scope; the
    // full canonical predecessor and full original signature bytes are separate
    // inputs. No new update rule, signature window or role authority is minted.
    let prefix = encode_original_owner_snapshot_v1(snapshot)?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-circuit-current-read.v1\0",
        mode.name(), &prefix, context.scope.binding().as_array(),
        context.verifier.trust_digest().as_array(),
        context.verifier.scope_digest().as_array(),
        context.verifier.objective_digest().as_array(), &signatures,
    ]))
}

pub(super) fn decision(context: &Context) -> Result<LearningIterationCoordinatorV1, Error> {
    let mut prefix = context.prefix.clone();
    if mode(context)? == Mode::NextUse {
        let selection = prefix.receipts.pop().ok_or(Error::Binding("original Selection"))?;
        prefix.head_digest = selection.predecessor;
    }
    Ok(LearningIterationCoordinatorV1::from_snapshot(prefix)?)
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub prefix_head: String,
    pub operation_id: String,
    pub mode: Mode,
}

impl Request {
    pub(super) fn new(context: &Context, binding: Digest32, request_id: u64) -> Result<Self, Error> {
        Ok(Self {
            schema: 1, operation: OPERATION.into(), request_id,
            binding: binding.to_string(), prefix_head: context.prefix.head_digest.to_string(),
            operation_id: context.prefix.request.operation_id.to_string(), mode: mode(context)?,
        })
    }

    pub(super) fn require_context(&self, context: &Context, binding: Digest32,
        request_id: u64) -> Result<(), Error>
    {
        let expected = Self::new(context, binding, request_id)?;
        if self.schema != expected.schema || self.operation != expected.operation
            || self.request_id != expected.request_id || self.binding != expected.binding
            || self.prefix_head != expected.prefix_head || self.operation_id != expected.operation_id
            || self.mode != expected.mode
        {
            return Err(Error::Binding("original fixed read request"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub read: OriginalRead,
}

impl Response {
    pub(super) fn require_request(&self, original: &Request) -> Result<(), Error> {
        if self.request.schema != original.schema || self.request.operation != original.operation
            || self.request.request_id != original.request_id || self.request.binding != original.binding
            || self.request.prefix_head != original.prefix_head
            || self.request.operation_id != original.operation_id || self.request.mode != original.mode
        {
            return Err(Error::Binding("original fixed read response"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalRead {
    pub publication: String,
    pub source_input: String,
    pub source_publication: Option<String>,
    pub observation: Observation,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Observation {
    Selection { bundle: String, selection: String },
    Retained {
        bundle: String, principal: String, agent: String, cell: String, run: String,
        checkpoint: String, selection: String, committed: String, publication: String,
    },
}

impl OriginalRead {
    pub(super) fn from_original(read: Readback) -> Result<Self, Error> {
        let observation = match read.observation {
            LearningIterationObservationV1::Selection { candidate_bundle, selection_digest } =>
                Observation::Selection { bundle: candidate_bundle.to_string(), selection: selection_digest.to_string() },
            LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, state_partition,
                checkpoint_digest, selection_digest, committed_step_receipt, task_owner_publication } =>
                Observation::Retained {
                    bundle: retained_bundle.to_string(), principal: state_partition.principal_id.to_string(),
                    agent: state_partition.agent_id.to_string(), cell: state_partition.cell_id.to_string(),
                    run: state_partition.run_id.to_string(), checkpoint: checkpoint_digest.to_string(),
                    selection: selection_digest.to_string(), committed: committed_step_receipt.to_string(),
                    publication: task_owner_publication.to_string(),
                },
            _ => return Err(Error::Binding("unexpected original read observation")),
        };
        Ok(Self { publication: read.publication.to_string(), source_input: read.source_input.to_string(),
            source_publication: read.source_publication.map(|value| value.to_string()), observation })
    }

    pub(super) fn decode(self, context: &Context) -> Result<Readback, Error> {
        let publication = digest(&self.publication)?;
        let source_input = digest(&self.source_input)?;
        let source_publication = self.source_publication.as_deref().map(digest).transpose()?;
        let baseline = context.prefix.request.selected_bundle.digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        let observation = match (mode(context)?, self.observation) {
            (Mode::Selection, Observation::Selection { bundle, selection }) => {
                if digest(&bundle)? != baseline || source_publication.is_some() {
                    return Err(Error::Binding("original retained selection"));
                }
                LearningIterationObservationV1::Selection {
                    candidate_bundle: baseline, selection_digest: digest(&selection)?,
                }
            }
            (Mode::NextUse, Observation::Retained { bundle, principal, agent, cell, run,
                checkpoint, selection, committed, publication: task_publication }) => {
                let state_partition = CellStatePartitionV1 {
                    principal_id: id(principal)?, agent_id: id(agent)?, cell_id: id(cell)?, run_id: id(run)?,
                };
                let selection = digest(&selection)?;
                let expected = &context.prefix.receipts[3].observation;
                if digest(&bundle)? != baseline || digest(&task_publication)? != publication
                    || source_publication.is_none()
                    || state_partition.principal_id != context.prefix.request.principal_id
                    || state_partition.agent_id != context.prefix.request.agent_id
                    || state_partition.cell_id != context.prefix.request.cell_id
                    || state_partition.run_id == context.prefix.request.source_run_id
                    || !matches!(expected, LearningIterationObservationV1::Selection {
                        candidate_bundle, selection_digest
                    } if *candidate_bundle == baseline && *selection_digest == selection)
                {
                    return Err(Error::Binding("original committed retained task"));
                }
                LearningIterationObservationV1::RetainedModelNextUse {
                    retained_bundle: baseline, state_partition, checkpoint_digest: digest(&checkpoint)?,
                    selection_digest: selection, committed_step_receipt: digest(&committed)?,
                    task_owner_publication: publication,
                }
            }
            _ => return Err(Error::Binding("original read mode")),
        };
        context.scope.validate_observation(&observation)?;
        Ok(Readback { observation, publication, source_input, source_publication })
    }
}

fn digest(text: &str) -> Result<Digest32, Error> {
    let digest: Digest32 = text.parse().map_err(|_| Error::Binding("read digest encoding"))?;
    if digest.is_zero() || digest.to_string() != text {
        return Err(Error::Binding("canonical nonempty read digest"));
    }
    Ok(digest)
}

fn id(text: String) -> Result<StableId, Error> {
    StableId::new(text).map_err(|_| Error::Binding("read scope identity"))
}
