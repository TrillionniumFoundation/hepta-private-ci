//! Private fixed-purpose records. Requests contain identity and action only.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCellQ24MaterialCommandReceiptV1;
use super::OriginalCellQ24MaterialReceiptConfigV1;
use super::Role;
use super::evidence_wire;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.original-q24-material.command.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action {
    Execute,
    Readback,
}

fn role_name(role: Role) -> &'static str {
    match role {
        Role::Experience => "experience",
        Role::Dataset => "dataset",
    }
}

pub(super) fn context_binding(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    at: u64,
) -> Result<Digest32, Error> {
    let initial = LearningIterationCoordinatorV1::new(
        config.initial.request.clone(),
        config.initial.owners.clone(),
    )?;
    config.scope.validate_snapshot(&config.initial)?;
    let policy = config.rule.inclusion_policy_digest(&config.initial)?;
    if initial.snapshot() != &config.initial
        || initial.next_stage() != Some(LearningIterationStageV1::Experience)
        || config.initial.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.initial.request.envelope.objective_digest != config.verifier.objective_digest()
        || config.freeze_plan.objective_digest != config.verifier.objective_digest()
        || config.freeze_plan.inclusion_policy_digest != policy
        || config.freeze_evidence.role != LearningEvidenceRoleV1::Evaluator
        || config.freeze_evidence.trust_digest != config.verifier.trust_digest()
        || config.freeze_evidence.scope_digest != config.verifier.scope_digest()
        || config.freeze_evidence.objective_digest != config.verifier.objective_digest()
        || config.experience_signer.principal.principal_id != config.initial.owners.experience
        || config.dataset_signer.principal.principal_id != config.initial.owners.dataset
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        || at < config.freeze_evidence.issued_at
        || at >= config.freeze_evidence.expires_at
    {
        return Err(Error::Binding("complete original Material context"));
    }
    for signer in [&config.experience_signer, &config.dataset_signer] {
        config
            .verifier
            .require_signer_binding(LearningEvidenceRoleV1::Observer, signer, at)?;
    }
    let mut original_freeze = config.freeze_evidence.signing_bytes();
    original_freeze.extend_from_slice(&config.freeze_evidence.signature);
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-material-command.v1\0",
        config.initial.head_digest.as_array(),
        config.scope.binding().as_array(),
        policy.as_array(),
        config.freeze_plan.snapshot_id.as_str().as_bytes(),
        config.freeze_plan.objective_digest.as_array(),
        config.freeze_plan.inclusion_policy_digest.as_array(),
        Digest32::of_bytes(&original_freeze).as_array(),
        config.verifier.trust_digest().as_array(),
        config.verifier.scope_digest().as_array(),
        config.verifier.objective_digest().as_array(),
        config
            .experience_signer
            .principal
            .principal_id
            .as_str()
            .as_bytes(),
        config
            .dataset_signer
            .principal
            .principal_id
            .as_str()
            .as_bytes(),
        &config.experience_signer.verifying_key,
        &config.dataset_signer.verifying_key,
        &config.maximum_signature_lifetime_seconds.to_be_bytes(),
    ]))
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub initial_head: String,
    pub operation_id: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub stage: String,
    pub action: Action,
}

impl Request {
    pub(super) fn new(
        config: &OriginalCellQ24MaterialReceiptConfigV1,
        role: Role,
        binding: Digest32,
        request_id: u64,
        action: Action,
    ) -> Self {
        Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            initial_head: config.initial.head_digest.to_string(),
            operation_id: config.initial.request.operation_id.to_string(),
            scope_binding: config.scope.binding().to_string(),
            actor_id: config.initial.owners.owner(role.stage()).to_string(),
            stage: role_name(role).into(),
            action,
        }
    }

    pub(super) fn require_context(
        &self,
        config: &OriginalCellQ24MaterialReceiptConfigV1,
        role: Role,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1
            || self.operation != OPERATION
            || self.request_id != request_id
            || self.binding != binding.to_string()
            || self.initial_head != config.initial.head_digest.to_string()
            || self.operation_id != config.initial.request.operation_id.as_str()
            || self.scope_binding != config.scope.binding().to_string()
            || self.actor_id != config.initial.owners.owner(role.stage()).as_str()
            || self.stage != role_name(role)
        {
            return Err(Error::Binding("same role-fixed Material request"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub initial_head: String,
    pub operation_id: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub stage: String,
    pub action: Action,
    pub result: CommandResult,
}

impl Response {
    pub(super) fn from_request(request: &Request, result: CommandResult) -> Self {
        Self {
            schema: request.schema,
            operation: request.operation.clone(),
            request_id: request.request_id,
            binding: request.binding.clone(),
            initial_head: request.initial_head.clone(),
            operation_id: request.operation_id.clone(),
            scope_binding: request.scope_binding.clone(),
            actor_id: request.actor_id.clone(),
            stage: request.stage.clone(),
            action: request.action,
            result,
        }
    }

    pub(super) fn require_request(&self, request: &Request) -> Result<(), Error> {
        if self.schema != request.schema
            || self.operation != request.operation
            || self.request_id != request.request_id
            || self.binding != request.binding
            || self.initial_head != request.initial_head
            || self.operation_id != request.operation_id
            || self.scope_binding != request.scope_binding
            || self.actor_id != request.actor_id
            || self.stage != request.stage
            || self.action != request.action
        {
            return Err(Error::Binding("same role-fixed Material response"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum CommandResult {
    Completed {
        snapshot: String,
        evidence: Vec<evidence_wire::Evidence>,
    },
    Missing,
    Pending,
    Busy,
    Expired,
    ReadbackRequired,
    Uncertain,
}

pub(super) fn encode_completed(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    role: Role,
    completed: OriginalCellQ24MaterialCommandReceiptV1,
    at: u64,
) -> Result<CommandResult, Error> {
    let completed = authenticate_cut(config, role, completed, at)?;
    let bytes = encode_original_owner_snapshot_v1(&completed.snapshot)?;
    Ok(CommandResult::Completed {
        snapshot: STANDARD_NO_PAD.encode(bytes),
        evidence: completed
            .evidence
            .iter()
            .map(evidence_wire::Evidence::from_original)
            .collect(),
    })
}

pub(super) fn decode_completed(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    role: Role,
    snapshot: String,
    evidence: Vec<evidence_wire::Evidence>,
    at: u64,
) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
    if snapshot.len() > 10_924 || evidence.is_empty() || evidence.len() > 2 {
        return Err(Error::Binding("bounded original Material cut"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(&snapshot)
        .map_err(|_| Error::Binding("original Material cut encoding"))?;
    if STANDARD_NO_PAD.encode(&bytes) != snapshot {
        return Err(Error::Binding("canonical original Material cut"));
    }
    let snapshot = decode_original_owner_snapshot_v1(&bytes)?;
    let evidence = evidence
        .into_iter()
        .map(|value| {
            value
                .decode()
                .map_err(|_| Error::Binding("original Observer encoding"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    authenticate_cut(
        config,
        role,
        OriginalCellQ24MaterialCommandReceiptV1 {
            snapshot,
            evidence,
            original_context: context_binding(config, at)?,
        },
        at,
    )
}

pub(super) fn authenticate_cut(
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    role: Role,
    completed: OriginalCellQ24MaterialCommandReceiptV1,
    at: u64,
) -> Result<OriginalCellQ24MaterialCommandReceiptV1, Error> {
    let expected_context = context_binding(config, at)?;
    if completed.original_context != expected_context {
        return Err(Error::Binding("same original Material configuration and freeze"));
    }
    let expected = match role {
        Role::Experience => 1,
        Role::Dataset => 2,
    };
    if completed.snapshot.request != config.initial.request
        || completed.snapshot.owners != config.initial.owners
        || completed.snapshot.receipts.len() != expected
        || completed.evidence.len() != expected
    {
        return Err(Error::Binding("exact original Material prefix"));
    }
    LearningIterationCoordinatorV1::from_snapshot(completed.snapshot.clone())?;
    config.scope.validate_snapshot(&completed.snapshot)?;
    for (index, (receipt, signed)) in completed
        .snapshot
        .receipts
        .iter()
        .zip(&completed.evidence)
        .enumerate()
    {
        let signer = if index == 0 {
            &config.experience_signer
        } else {
            &config.dataset_signer
        };
        let stage = if index == 0 {
            LearningIterationStageV1::Experience
        } else {
            LearningIterationStageV1::Dataset
        };
        let expires_at = signed
            .issued_at
            .checked_add(config.maximum_signature_lifetime_seconds)
            .ok_or(Error::Binding(
                "original Material signature window overflow",
            ))?
            .min(signer.principal.expires_at)
            .min(config.freeze_evidence.expires_at);
        if receipt.observation.stage() != stage
            || receipt.actor_id != signer.principal.principal_id
            || receipt.observed_unix_seconds != signed.issued_at
            || signed.issued_at > at
            || signed.issued_at < config.freeze_evidence.issued_at
            || signed.expires_at != expires_at
            || receipt.evidence_digest != completed.snapshot.receipts[0].evidence_digest
        {
            return Err(Error::Binding(
                "original Material actor, provenance and window",
            ));
        }
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let verified =
            config
                .verifier
                .verify(LearningEvidenceRoleV1::Observer, signed, &payload, at)?;
        if verified.principal() != &signer.principal
            || verified.controller_id() != &signer.controller_id
        {
            return Err(Error::Binding("original registered Observer"));
        }
    }
    Ok(completed)
}
