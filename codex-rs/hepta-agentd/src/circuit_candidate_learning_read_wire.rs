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
use super::OriginalCircuitCandidateLearningReadContextV1 as Context;
use super::OriginalCircuitCandidateLearningReadbackV1 as Readback;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-circuit-candidate.current-read.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Mode {
    Selection,
    NextUse,
}

impl Mode {
    fn name(self) -> &'static [u8] {
        match self {
            Self::Selection => b"selection",
            Self::NextUse => b"next_use",
        }
    }
}

pub(super) fn mode(context: &Context) -> Result<Mode, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(context.prefix.clone())?;
    context.scope().validate_snapshot(&context.prefix)?;
    let model = context.model();
    let decision = LearningIterationCoordinatorV1::from_snapshot(model.snapshot().clone())?;
    let candidate = decision
        .candidate()
        .ok_or(Error::Binding("original positive trained Candidate"))?;
    if model.snapshot().receipts.len() != 5
        || context.decision() != model.snapshot()
        || decision.next_stage() != Some(LearningIterationStageV1::Selection)
        || decision.next_task_bundle() != Some(candidate)
        || candidate == &context.prefix.request.selected_bundle
        || context.prefix.request != model.snapshot().request
        || context.prefix.owners != model.snapshot().owners
        || !context.prefix.receipts.starts_with(&model.snapshot().receipts)
        || !matches!(
            model.snapshot().receipts[2].observation,
            LearningIterationObservationV1::Training { .. }
        )
        || !matches!(
            model.snapshot().receipts[3].observation,
            LearningIterationObservationV1::Evaluation {
                disposition: codex_hepta_learning_artifacts::LearningEvaluationDispositionV1::Qualified,
                ..
            }
        )
        || !matches!(
            model.snapshot().receipts[4].observation,
            LearningIterationObservationV1::Proposal {
                disposition: codex_hepta_learning_artifacts::LearningProposalDispositionV1::UpdateCandidates,
                ..
            }
        )
    {
        return Err(Error::Binding("exact original positive Model read profile"));
    }
    match (
        context.prefix.receipts.len(),
        coordinator.next_stage(),
        context.selection_evidence.as_ref(),
    ) {
        (5, Some(LearningIterationStageV1::Selection), None)
            if &context.prefix == model.snapshot() => Ok(Mode::Selection),
        (6, Some(LearningIterationStageV1::NextUse), Some(_))
            if coordinator.next_task_bundle() == Some(candidate) => Ok(Mode::NextUse),
        _ => Err(Error::Binding("exact positive Model or Selection prefix")),
    }
}

pub(super) fn authenticate(
    context: &Context,
    at: u64,
) -> Result<Vec<codex_hepta_learning_ledger::VerifiedLearningEvidenceV1>, Error> {
    crate::OriginalCircuitModelPublicationContextV1::authenticate(context.publication.as_ref(), at, false)
        .map_err(|_| Error::Binding("full original Model and four predecessor windows"))?;
    let selected_mode = mode(context)?;
    let snapshot = &context.prefix;
    let verifier = context.verifier();
    if snapshot.owners.evidence_trust_digest != verifier.trust_digest()
        || snapshot.request.envelope.objective_digest != verifier.objective_digest()
    {
        return Err(Error::Binding("original positive published read trust"));
    }
    let mut verified = Vec::with_capacity(3);
    for (index, role, signed, expected_actor) in [
        (2, LearningEvidenceRoleV1::Generator, context.training_attestation(), &snapshot.owners.trainer),
        (3, LearningEvidenceRoleV1::Evaluator, context.evaluation_attestation(), &snapshot.owners.evaluator),
    ] {
        let receipt = &snapshot.receipts[index];
        let original = verifier.verify(
            role,
            signed,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            at,
        )?;
        if &original.principal().principal_id != expected_actor
            || &receipt.actor_id != expected_actor
            || receipt.observed_unix_seconds > signed.issued_at
            || receipt.observed_unix_seconds > at
        {
            return Err(Error::Binding("original positive predecessor actor and time"));
        }
        for prior in &verified {
            verify_signed_actor_separation(prior, &original, at)?;
        }
        verified.push(original);
    }
    if selected_mode == Mode::NextUse {
        let signed = context.selection_evidence.as_ref()
            .ok_or(Error::Binding("actual original positive Selector signature"))?;
        let receipt = &snapshot.receipts[5];
        let original = verifier.verify(
            LearningEvidenceRoleV1::Selector,
            signed,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            at,
        )?;
        if original.principal().principal_id != snapshot.owners.selector
            || receipt.actor_id != snapshot.owners.selector
            || receipt.observed_unix_seconds != signed.issued_at
            || receipt.observed_unix_seconds > at
        {
            return Err(Error::Binding("original positive Selector actor and time"));
        }
        for prior in &verified {
            verify_signed_actor_separation(prior, &original, at)?;
        }
        verified.push(original);
    }
    Ok(verified)
}

pub(super) fn context_binding(context: &Context, at: u64) -> Result<Digest32, Error> {
    authenticate(context, at)?;
    let original = context.model();
    let predecessors = context.original_predecessors();
    let (record, model_context) = crate::OriginalCellQ24ModelCommandReceiptV1::original_record_for_root(original, predecessors)
        .map_err(|_| Error::Binding("complete opaque original Model record"))?;
    let mut signatures = Vec::new();
    for signed in predecessors.iter().chain(context.selection_evidence.iter()) {
        let bytes = signed.signing_bytes();
        signatures.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
        signatures.extend_from_slice(&bytes);
        signatures.extend_from_slice(&signed.signature);
    }
    let prefix = encode_original_owner_snapshot_v1(&context.prefix)?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-circuit-candidate-current-read.v1\0",
        mode(context)?.name(),
        &prefix,
        context.scope().binding().as_array(),
        context.verifier().trust_digest().as_array(),
        context.verifier().scope_digest().as_array(),
        context.verifier().objective_digest().as_array(),
        original.material_digest().as_array(),
        model_context.as_array(),
        record,
        &signatures,
    ]))
}

pub(super) fn decision(context: &Context) -> Result<LearningIterationCoordinatorV1, Error> {
    mode(context)?;
    Ok(LearningIterationCoordinatorV1::from_snapshot(context.decision().clone())?)
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
    pub(super) fn new(
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<Self, Error> {
        Ok(Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            prefix_head: context.prefix.head_digest.to_string(),
            operation_id: context.prefix.request.operation_id.to_string(),
            mode: mode(context)?,
        })
    }

    pub(super) fn require_context(
        &self,
        context: &Context,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        let expected = Self::new(context, binding, request_id)?;
        if self.schema != expected.schema
            || self.operation != expected.operation
            || self.request_id != expected.request_id
            || self.binding != expected.binding
            || self.prefix_head != expected.prefix_head
            || self.operation_id != expected.operation_id
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
        if self.request.schema != original.schema
            || self.request.operation != original.operation
            || self.request.request_id != original.request_id
            || self.request.binding != original.binding
            || self.request.prefix_head != original.prefix_head
            || self.request.operation_id != original.operation_id
            || self.request.mode != original.mode
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
    Selection {
        bundle: String,
        selection: String,
    },
    NextUse {
        bundle: String,
        principal: String,
        agent: String,
        cell: String,
        run: String,
        checkpoint: String,
        selection: String,
        committed: String,
        cutover: String,
    },
}

impl OriginalRead {
    pub(super) fn from_original(read: Readback) -> Result<Self, Error> {
        let observation = match read.observation {
            LearningIterationObservationV1::Selection {
                candidate_bundle,
                selection_digest,
            } => Observation::Selection {
                bundle: candidate_bundle.to_string(),
                selection: selection_digest.to_string(),
            },
            LearningIterationObservationV1::NextUse {
                candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt,
            } => Observation::NextUse {
                bundle: candidate_bundle.to_string(),
                principal: state_partition.principal_id.to_string(),
                agent: state_partition.agent_id.to_string(),
                cell: state_partition.cell_id.to_string(),
                run: state_partition.run_id.to_string(),
                checkpoint: checkpoint_digest.to_string(),
                selection: selection_digest.to_string(),
                committed: committed_step_receipt.to_string(),
                cutover: state_cutover_receipt.to_string(),
            },
            _ => return Err(Error::Binding("unexpected original read observation")),
        };
        Ok(Self {
            publication: read.publication.to_string(),
            source_input: read.source_input.to_string(),
            source_publication: read.source_publication.map(|value| value.to_string()),
            observation,
        })
    }

    pub(super) fn decode(self, context: &Context) -> Result<Readback, Error> {
        let publication = digest(&self.publication)?;
        let source_input = digest(&self.source_input)?;
        let source_publication = self.source_publication.as_deref().map(digest).transpose()?;
        let decision = decision(context)?;
        let candidate = decision.candidate()
            .ok_or(Error::Binding("original positive Candidate"))?
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        let observation = match (mode(context)?, self.observation) {
            (Mode::Selection, Observation::Selection { bundle, selection }) => {
                if digest(&bundle)? != candidate || source_publication.is_some() {
                    return Err(Error::Binding("original positive selection"));
                }
                LearningIterationObservationV1::Selection {
                    candidate_bundle: candidate,
                    selection_digest: digest(&selection)?,
                }
            }
            (
                Mode::NextUse,
                Observation::NextUse {
                    bundle,
                    principal,
                    agent,
                    cell,
                    run,
                    checkpoint,
                    selection,
                    committed,
                    cutover,
                },
            ) => {
                let state_partition = CellStatePartitionV1 {
                    principal_id: id(principal)?,
                    agent_id: id(agent)?,
                    cell_id: id(cell)?,
                    run_id: id(run)?,
                };
                let selection = digest(&selection)?;
                let expected = &context.prefix.receipts[5].observation;
                if digest(&bundle)? != candidate
                    || source_publication.is_none()
                    || state_partition.principal_id != context.prefix.request.principal_id
                    || state_partition.agent_id != context.prefix.request.agent_id
                    || state_partition.cell_id != context.prefix.request.cell_id
                    || state_partition.run_id == context.prefix.request.source_run_id
                    || !matches!(expected, LearningIterationObservationV1::Selection {
                        candidate_bundle, selection_digest
                    } if *candidate_bundle == candidate && *selection_digest == selection)
                {
                    return Err(Error::Binding("original committed positive task"));
                }
                LearningIterationObservationV1::NextUse {
                    candidate_bundle: candidate,
                    state_partition,
                    checkpoint_digest: digest(&checkpoint)?,
                    selection_digest: selection,
                    committed_step_receipt: digest(&committed)?,
                    state_cutover_receipt: digest(&cutover)?,
                }
            }
            _ => return Err(Error::Binding("original read mode")),
        };
        context.scope().validate_observation(&observation)?;
        Ok(Readback {
            observation,
            publication,
            source_input,
            source_publication,
        })
    }
}

fn digest(text: &str) -> Result<Digest32, Error> {
    let digest: Digest32 = text
        .parse()
        .map_err(|_| Error::Binding("read digest encoding"))?;
    if digest.is_zero() || digest.to_string() != text {
        return Err(Error::Binding("canonical nonempty read digest"));
    }
    Ok(digest)
}

fn id(text: String) -> Result<StableId, Error> {
    StableId::new(text).map_err(|_| Error::Binding("read scope identity"))
}
