//! Bind verified Memory text to a fixed unsigned Joint training worker.
//!
//! The original host still authenticates the task/current iteration, selected
//! artifact and durable job. These functions never spawn, register an owner,
//! sign a Training receipt, evaluate, select or publish a model. Completion
//! re-reads the real Memory/Ledger owners, but that observation is not a lease
//! or a distributed transaction with the original checkpoint/job owner.

use std::collections::BTreeMap;
use std::sync::Mutex;

use codex_hepta_infer_core::JointTensorPacketV1;
use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_neuron::inspect_joint_v4_generation_weights_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::JointMemoryTextReplayAdmissionV1;
use crate::JointMemoryTextReplayErrorV1;
use crate::JointVerifiedMemoryTextReplayV1;
use crate::UnpublishedJointV4BundleV1;
use crate::assemble_joint_v4_training_bundle_v1;
use crate::materialize_joint_verified_memory_text_v1;

#[path = "joint_text_training_readback.rs"]
mod readback;
#[path = "joint_text_training_wire.rs"]
mod wire;

#[derive(Debug, thiserror::Error)]
pub enum JointTextTrainingErrorV1 {
    #[error("Joint text training binding: {0}")]
    Binding(&'static str),
    #[error("Joint text training capacity")]
    Capacity,
    #[error("Joint text training encoding")]
    Encoding,
    #[error("Joint text training source revalidation: {0}")]
    Source(#[from] JointMemoryTextReplayErrorV1),
}

/// Values admitted by the original host. An execution-source digest pins the
/// seven fixed files and four absent package initializers; it selects no path.
#[derive(Clone, Debug)]
pub struct JointTextTrainingJobAdmissionV1 {
    pub candidate_artifact_id: StableId,
    pub steps: u64,
    pub learning_rate: f64,
    pub execution_source_digest: Digest32,
}

/// Immutable content binding, not an authenticated job or Training capability.
#[derive(Clone)]
pub struct PreparedJointTextTrainingRequestV1 {
    snapshot: LearningIterationSnapshotV1,
    source: JointVerifiedMemoryTextReplayV1,
    candidate_artifact_id: StableId,
    predecessor_metadata: BTreeMap<String, String>,
    predecessor_parameter_count: u64,
    predecessor_core_parameters: BTreeMap<String, Vec<f64>>,
    wire: wire::RequestWire,
    request_bytes: Vec<u8>,
    request_digest: Digest32,
    update_rule: Digest32,
}

impl PreparedJointTextTrainingRequestV1 {
    pub fn request_bytes(&self) -> &[u8] {
        &self.request_bytes
    }
    pub fn request_digest(&self) -> Digest32 {
        self.request_digest
    }
    pub fn update_rule_digest(&self) -> Digest32 {
        self.update_rule
    }
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// The original job owner must read these exact files under its own custody,
/// check its durable terminal state, and report any failed marker. Caller-
/// supplied bytes alone are not authenticated evidence of worker execution.
pub struct JointTextTrainingOutputBytesV1<'a> {
    pub started: &'a [u8],
    pub candidate: &'a [u8],
    pub observation: &'a [u8],
    pub completed: &'a [u8],
    pub failed: Option<&'a [u8]>,
}

/// Revalidated data and a canonical unpublished bundle, still unsigned.
#[derive(Clone, Debug, PartialEq)]
pub struct UnsignedJointTextTrainingCandidateV1 {
    bundle: UnpublishedJointV4BundleV1,
    request_digest: Digest32,
    observation_digest: Digest32,
    completion_digest: Digest32,
    completed_steps: u64,
    worker_wall_nanoseconds: u64,
    worker_cpu_nanoseconds: u64,
}

impl UnsignedJointTextTrainingCandidateV1 {
    pub fn bundle(&self) -> &UnpublishedJointV4BundleV1 {
        &self.bundle
    }
    pub fn request_digest(&self) -> Digest32 {
        self.request_digest
    }
    pub fn observation_digest(&self) -> Digest32 {
        self.observation_digest
    }
    pub fn completion_digest(&self) -> Digest32 {
        self.completion_digest
    }
    pub fn completed_steps(&self) -> u64 {
        self.completed_steps
    }
    pub fn worker_wall_nanoseconds(&self) -> u64 {
        self.worker_wall_nanoseconds
    }
    pub fn worker_cpu_nanoseconds(&self) -> u64 {
        self.worker_cpu_nanoseconds
    }
    /// Excludes host admission/queue/transfer and the final observation writes.
    /// It cannot fill the original Training stage's complete cost by itself.
    pub const fn worker_cost_scope(&self) -> &'static str {
        readback::COST_SCOPE
    }
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// The caller supplies an authenticated current snapshot and the actual chosen
/// predecessor bytes. Structural snapshot replay cannot establish freshness.
/// Source-run IDs stay distinct from the Ledger's run-snapshot digest.
pub fn prepare_joint_text_training_request_v1(
    snapshot: &LearningIterationSnapshotV1,
    source: &JointVerifiedMemoryTextReplayV1,
    predecessor_packet: &[u8],
    admission: JointTextTrainingJobAdmissionV1,
) -> Result<PreparedJointTextTrainingRequestV1, JointTextTrainingErrorV1> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
        .map_err(|_| JointTextTrainingErrorV1::Binding("structural iteration replay"))?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training) {
        return Err(JointTextTrainingErrorV1::Binding("Training stage"));
    }
    let Some(LearningIterationObservationV1::Dataset {
        snapshot_digest,
        rows,
        bytes,
        ..
    }) = snapshot.receipts.last().map(|receipt| &receipt.observation)
    else {
        return Err(JointTextTrainingErrorV1::Binding(
            "original Dataset observation",
        ));
    };
    let request = &snapshot.request;
    if source.dataset().snapshot.dataset_digest != *snapshot_digest
        || source.dataset_plan().objective_digest != request.envelope.objective_digest
        || source.consumer().agent_id().as_str() != request.agent_id.as_str()
        || source.records().is_empty()
        || source.records().len() > 4096
        || admission.candidate_artifact_id == request.selected_bundle.artifact_id
    {
        return Err(JointTextTrainingErrorV1::Binding(
            "original source and candidate identity",
        ));
    }
    if predecessor_packet.len() as u64 > request.budget.maximum_artifact_bytes {
        return Err(JointTextTrainingErrorV1::Capacity);
    }
    let inspected = inspect_joint_v4_generation_weights_v1(predecessor_packet)
        .map_err(|_| JointTextTrainingErrorV1::Binding("canonical physical predecessor"))?;
    let c = inspected.components();
    let actual_components = CellBundleComponentsV1 {
        base: c.base,
        organ_adapter: c.organ_adapter,
        cell_adapter: c.cell_adapter,
        heads: c.heads,
        composition: c.composition,
        encoder: c.encoder,
        tokenizer: c.tokenizer,
        normalizer: c.normalizer,
        calibration: c.calibration,
        numeric_profile: c.numeric_profile,
        output_schema: c.output_schema,
        state_schema: c.state_schema,
        state_semantics: c.state_semantics,
    };
    if actual_components != request.selected_bundle.components {
        return Err(JointTextTrainingErrorV1::Binding(
            "all thirteen predecessor components",
        ));
    }
    let packet = JointTensorPacketV1::decode(predecessor_packet)
        .map_err(|_| JointTextTrainingErrorV1::Encoding)?;
    if packet.text("core_state_profile").ok() != Some("persistent-v1") {
        return Err(JointTextTrainingErrorV1::Binding("persistent text profile"));
    }
    let selected = request
        .selected_bundle
        .digest()
        .map_err(|_| JointTextTrainingErrorV1::Binding("selected bundle"))?;
    let rate_bits = admission.learning_rate.to_bits();
    let wire = wire::RequestWire {
        schema: wire::REQUEST_SCHEMA.to_owned(),
        profile: wire::PROFILE.to_owned(),
        principal_id: request.principal_id.as_str().to_owned(),
        agent_id: request.agent_id.as_str().to_owned(),
        cell_id: request.cell_id.as_str().to_owned(),
        operation_id: request.operation_id.as_str().to_owned(),
        source_run_id: request.source_run_id.as_str().to_owned(),
        completed_task_receipt: wire::hex(request.completed_task_receipt),
        iteration_head: wire::hex(snapshot.head_digest),
        selected_bundle_digest: wire::hex(selected),
        selected_generation: request.selected_bundle.generation.get(),
        candidate_artifact_id: admission.candidate_artifact_id.as_str().to_owned(),
        evaluation_profile: wire::hex(request.evaluation_profile),
        dataset_digest: wire::hex(*snapshot_digest),
        dataset_observed_rows: u64::from(*rows),
        dataset_observed_bytes: *bytes,
        source_record_count: source.records().len() as u64,
        materialization_digest: wire::hex(source.mapping_digest()),
        materialization_profile_digest: wire::hex(source.profile_digest()),
        source_support_digest: source
            .source_use()
            .source_support_digest()
            .as_str()
            .to_owned(),
        source_content_sha256: source
            .source_use()
            .memory()
            .content_sha256
            .as_str()
            .to_owned(),
        source_revision: source.source_use().memory().id.revision,
        source_policy_revision: source.source_use().policy_revision(),
        predecessor_sha256: wire::hex(inspected.physical_weights_digest()),
        predecessor_bytes: inspected.weights_bytes(),
        execution_source_digest: wire::hex(admission.execution_source_digest),
        prefix: source.prefix().to_owned(),
        continuation: source.continuation().to_owned(),
        steps: admission.steps,
        learning_rate_f64_be: format!("{rate_bits:016x}"),
        maximum_dataset_rows: u64::from(request.budget.maximum_dataset_rows),
        maximum_dataset_bytes: request.budget.maximum_dataset_bytes,
        maximum_training_steps: request.budget.maximum_training_steps,
        maximum_training_milliseconds: request.budget.maximum_training_milliseconds,
        maximum_artifact_bytes: request.budget.maximum_artifact_bytes,
    };
    let request_bytes = wire.encode()?;
    Ok(PreparedJointTextTrainingRequestV1 {
        snapshot: snapshot.clone(),
        source: source.clone(),
        candidate_artifact_id: admission.candidate_artifact_id,
        predecessor_parameter_count: packet
            .tensors
            .values()
            .map(|tensor| tensor.data.len() as u64)
            .sum(),
        predecessor_core_parameters: packet
            .tensors
            .iter()
            .filter(|(name, _)| name.starts_with("core."))
            .map(|(name, tensor)| (name.clone(), tensor.data.clone()))
            .collect(),
        predecessor_metadata: packet.meta,
        request_digest: wire.binding_digest()?,
        update_rule: wire.update_rule()?,
        wire,
        request_bytes,
    })
}

/// Re-read the existing owners, check the original request/output byte closure,
/// and assemble without advancing Training. The real job owner must separately
/// reconcile status, verify current task/head authority and sign any receipt.
pub async fn revalidate_joint_text_training_output_v1(
    memory_owner: &CognitiveStore,
    ledger: &Mutex<LedgerWriter>,
    current_snapshot: &LearningIterationSnapshotV1,
    prepared: &PreparedJointTextTrainingRequestV1,
    output: JointTextTrainingOutputBytesV1<'_>,
) -> Result<UnsignedJointTextTrainingCandidateV1, JointTextTrainingErrorV1> {
    if current_snapshot != &prepared.snapshot {
        return Err(JointTextTrainingErrorV1::Binding(
            "original complete iteration snapshot",
        ));
    }
    let observed = readback::validate(&prepared.wire, &prepared.request_bytes, &output)?;
    let candidate_packet = JointTensorPacketV1::decode(output.candidate)
        .map_err(|_| JointTextTrainingErrorV1::Encoding)?;
    let parameter_count: u64 = candidate_packet
        .tensors
        .values()
        .map(|tensor| tensor.data.len() as u64)
        .sum();
    if candidate_packet.meta != prepared.predecessor_metadata
        || parameter_count != prepared.predecessor_parameter_count
        || observed
            .training
            .parameter_groups
            .iter()
            .map(|group| group.parameters)
            .sum::<u64>()
            != parameter_count
    {
        return Err(JointTextTrainingErrorV1::Binding(
            "fixed model metadata and scalar inventory",
        ));
    }
    let mut changed_core_parameters = 0_u64;
    for (name, before) in &prepared.predecessor_core_parameters {
        let after = candidate_packet
            .tensors
            .get(name)
            .ok_or(JointTextTrainingErrorV1::Binding(
                "complete core parameter inventory",
            ))?;
        if before.len() != after.data.len() {
            return Err(JointTextTrainingErrorV1::Binding("core parameter shape"));
        }
        changed_core_parameters += before
            .iter()
            .zip(&after.data)
            .filter(|(original, current)| original != current)
            .count() as u64;
    }
    if changed_core_parameters == 0
        || changed_core_parameters != observed.training.core_changed_parameters
    {
        return Err(JointTextTrainingErrorV1::Binding(
            "actual core scalar update count",
        ));
    }
    let fresh = materialize_joint_verified_memory_text_v1(
        memory_owner,
        ledger,
        JointMemoryTextReplayAdmissionV1 {
            consumer: prepared.source.consumer(),
            source: prepared.source.source_use(),
            dataset_plan: prepared.source.dataset_plan(),
            freeze_evidence: prepared.source.freeze_evidence(),
            expected_dataset_digest: prepared.source.dataset().snapshot.dataset_digest,
            maximum_source_records: prepared.source.records().len(),
            maximum_text_bytes: prepared.source.prefix().len()
                + prepared.source.continuation().len(),
        },
    )
    .await?;
    if fresh != prepared.source {
        return Err(JointTextTrainingErrorV1::Binding(
            "fresh Memory and signed Ledger owners",
        ));
    }
    let bundle = assemble_joint_v4_training_bundle_v1(
        current_snapshot,
        prepared.candidate_artifact_id.clone(),
        CellTrainingLineageV1 {
            source_bundle: wire::digest(&prepared.wire.selected_bundle_digest)?,
            dataset: fresh.dataset().snapshot.dataset_digest,
            update_rule: prepared.update_rule,
            evaluation_profile: current_snapshot.request.evaluation_profile,
        },
        output.candidate,
    )
    .map_err(|_| JointTextTrainingErrorV1::Binding("unpublished canonical candidate"))?;
    Ok(UnsignedJointTextTrainingCandidateV1 {
        bundle,
        request_digest: prepared.request_digest,
        observation_digest: Digest32::of_bytes(output.observation),
        completion_digest: Digest32::of_bytes(output.completed),
        completed_steps: observed.training.completed_steps,
        worker_wall_nanoseconds: observed.cost.wall_nanoseconds,
        worker_cpu_nanoseconds: observed.cost.cpu_nanoseconds,
    })
}

#[cfg(test)]
#[path = "joint_text_training_tests.rs"]
mod tests;
