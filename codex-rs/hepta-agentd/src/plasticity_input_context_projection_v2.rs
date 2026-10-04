//! Project complete original DTOs; final custody and owner checks stay in the
//! original loader. No source, writer, worker or current owner is opened here.
use super::*;
use codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2;
use codex_hepta_agent_components::neuron::encode_neuron_generation_material_v2;

/// Independently observed inputs for the existing context schema. Training
/// material/trust and the actual Serving Goal scope are separate domains.
pub struct ParameterInputContextProjectionV2<'a> {
    pub subject: &'a StableId,
    pub spawn_generation: u64,
    pub round: &'a crate::AgentdSelfIterationRoundV1,
    pub baseline_artifact: &'a StableId,
    pub baseline_material: &'a NeuronGenerationMaterialV2,
    pub baseline_material_source: (&'a Path, Digest32),
    pub artifact_snapshot_source: &'a Path,
    pub artifact_snapshot_receipt: RegistrySnapshotReceipt,
    pub dataset: &'a crate::PreparedParameterDatasetV1,
    pub ndu_journal_source: (&'a Path, Digest32),
    pub neuron_material: &'a NeuronGenerationMaterialV2,
    pub neuron_anchor: JournalAnchor,
    pub observed_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

/// Explicit dataset purpose; the signed Window is the independent E output,
/// while facts retain the first original held-owner observation unchanged.
pub enum ParameterInputContextDatasetV3<'a> {
    OriginalV2(&'a crate::PreparedParameterDatasetV1),
    WindowV3 {
        facts: &'a crate::PreparedParameterDatasetWindowV3,
        plan: &'a codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanV3,
        window: &'a codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotReceiptV3,
        evaluator: &'a codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1,
    },
}
/// Complete original Source pairs for an explicit frozen numerical-read purpose.
pub struct ParameterInputContextFrozenNeuronV3<'a> {
    pub checkpoint_response: (&'a Path, Digest32),
    pub goal_material: (&'a Path, Digest32),
}
/// Complete independently observed inputs; training and Serving domains stay
/// separate and all Sources are authenticated again by the original loader.
pub struct ParameterInputContextProjectionV3<'a> {
    pub subject: &'a StableId,
    pub spawn_generation: u64,
    pub round: &'a crate::AgentdSelfIterationRoundV1,
    pub baseline_artifact: &'a StableId,
    pub baseline_material: &'a NeuronGenerationMaterialV2,
    pub baseline_material_source: (&'a Path, Digest32),
    pub artifact_snapshot_source: &'a Path,
    pub artifact_snapshot_receipt: RegistrySnapshotReceipt,
    pub dataset: ParameterInputContextDatasetV3<'a>,
    pub frozen_neuron: Option<ParameterInputContextFrozenNeuronV3<'a>>,
    pub ndu_journal_source: (&'a Path, Digest32),
    pub neuron_material: &'a NeuronGenerationMaterialV2,
    pub neuron_anchor: JournalAnchor,
    pub observed_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

/// Preserve the original V2 inputs and bytes through the same projection body.
pub fn project_parameter_input_context_v2(
    template_bytes: &[u8],
    inputs: &ParameterInputContextProjectionV2<'_>,
) -> Result<Vec<u8>, AgentdError> {
    project_parameter_input_context_v3(
        template_bytes,
        &ParameterInputContextProjectionV3 {
            subject: inputs.subject,
            spawn_generation: inputs.spawn_generation,
            round: inputs.round,
            baseline_artifact: inputs.baseline_artifact,
            baseline_material: inputs.baseline_material,
            baseline_material_source: inputs.baseline_material_source,
            artifact_snapshot_source: inputs.artifact_snapshot_source,
            artifact_snapshot_receipt: inputs.artifact_snapshot_receipt,
            dataset: ParameterInputContextDatasetV3::OriginalV2(inputs.dataset),
            frozen_neuron: None,
            ndu_journal_source: inputs.ndu_journal_source,
            neuron_material: inputs.neuron_material,
            neuron_anchor: inputs.neuron_anchor,
            observed_at_unix_ms: inputs.observed_at_unix_ms,
            expires_at_unix_ms: inputs.expires_at_unix_ms,
        },
    )
}

/// Emit bounded whole context bytes using the original descriptor types. The
/// caller must publish an immutable protected Source; these bytes grant no
/// authority and cannot replace the loader's held Ledger/Neuron/CURRENT checks.
pub fn project_parameter_input_context_v3(
    template_bytes: &[u8],
    inputs: &ParameterInputContextProjectionV3<'_>,
) -> Result<Vec<u8>, AgentdError> {
    if template_bytes.is_empty() || template_bytes.len() as u64 > MAX_DESCRIPTOR_BYTES {
        return invalid("whole plasticity context template byte bound");
    }
    let mut d: ContextDescriptor = serde_json::from_slice(template_bytes)?;
    let material = inputs.baseline_material;
    let material_bytes = encode_neuron_generation_material_v2(material)
        .map_err(|e| AgentdError::Invalid(format!("full context baseline: {e}")))?;
    let goal = inputs.neuron_material;
    crate::validate_parameter_goal_material_projection_v3(material, goal)?;
    let now = inputs.observed_at_unix_ms;
    let expires = inputs.expires_at_unix_ms;
    if d.schema != "hepta.agentd.plasticity-input-context.v2"
        || d.agent_id != inputs.subject.as_str()
        || inputs.spawn_generation == 0
        || Digest32::of_bytes(&material_bytes) != inputs.baseline_material_source.1
        || inputs.baseline_material_source.1.is_zero()
        || inputs.ndu_journal_source.1.is_zero()
        || !inputs.baseline_material_source.0.is_absolute()
        || !inputs.artifact_snapshot_source.is_absolute()
        || !inputs.ndu_journal_source.0.is_absolute()
        || now < d.artifacts.observed_at
        || now < inputs.round.admitted_at_ms()
        || expires > d.artifacts.expires_at
        || expires > inputs.round.deadline_ms()
        || now >= expires
        || goal.scope.scope_digest.is_zero()
        || goal.scope.objective_digest.is_zero()
        || inputs.neuron_anchor.sequence == 0
        || inputs.neuron_anchor.checkpoint_digest.is_zero()
        || d.artifacts.current_owner.is_none()
    {
        return invalid("context projection identity/source/window/actual ACK");
    }
    let objective = material.scope.objective_digest;
    let verifier = build_verifier(&d.trust, objective)?;
    if verifier.scope_digest() != material.scope.scope_digest
        || digest(&d.objective_digest, "template objective")? != objective
    {
        return invalid("context projection cannot rewrite the learning trust domain");
    }
    let (dataset, installed_head, dataset_window) =
        dataset_projection::project(&inputs.dataset, &verifier, inputs.round, now)?;
    verify_dataset_snapshot_receipt_v3(&dataset, now)
        .map_err(|e| AgentdError::Invalid(format!("context dataset receipt: {e}")))?;
    verify_dataset_snapshot_receipt_v3(&dataset, expires - 1)
        .map_err(|e| AgentdError::Invalid(format!("context dataset window: {e}")))?;
    if dataset.snapshot.objective_digest != objective
        || dataset.producer.scope_digest != material.scope.scope_digest
        || dataset.producer.principal_id.as_str() != d.owner_policy.dataset_owner_id
        || d.ndu.owner_id != d.owner_policy.modulator_owner_id
        || d.neuron.owner_id != d.owner_policy.eligibility_owner_id
        || d.neuron.owner_id != d.owner_policy.parameter_signal_owner_id
        || inputs.artifact_snapshot_receipt.binding.is_zero()
        || inputs.artifact_snapshot_receipt.head_digest.is_zero()
        || inputs.artifact_snapshot_receipt.file_digest.is_zero()
        || inputs.artifact_snapshot_receipt.encoded_bytes == 0
        || inputs.artifact_snapshot_receipt.encoded_bytes > 64 * 1024 * 1024
    {
        return invalid("context projection whole dataset/policy/snapshot differs");
    }
    let _policy = build_owner_policy(&d.owner_policy)?;
    for binding in &d.signal_bindings {
        let _binding = signal_binding(binding)?;
    }
    let round_bytes = inputs.round.canonical_bytes()?;
    d.spawn_generation = inputs.spawn_generation;
    d.round_hex = crate::client::encode_hex(&round_bytes);
    d.predecessor_registry_head_digest = installed_head.to_string();
    d.baseline_id = inputs.baseline_artifact.to_string();
    d.baseline_material = ContextSource {
        path: inputs.baseline_material_source.0.to_path_buf(),
        digest: inputs.baseline_material_source.1.to_string(),
    };
    d.artifacts.path = inputs.artifact_snapshot_source.to_path_buf();
    let receipt = inputs.artifact_snapshot_receipt;
    d.artifacts.receipt = ArtifactSnapshotReceiptDescriptorV1 {
        binding: receipt.binding.to_string(),
        head_digest: receipt.head_digest.to_string(),
        file_digest: receipt.file_digest.to_string(),
        records: receipt.records,
        encoded_bytes: receipt.encoded_bytes,
    };
    d.artifacts.observed_at = now;
    d.artifacts.expires_at = expires;
    d.dataset = dataset_descriptor(&dataset);
    d.dataset_window = dataset_window;
    d.frozen_neuron = inputs
        .frozen_neuron
        .as_ref()
        .map(|frozen| {
            for (path, pin) in [frozen.checkpoint_response, frozen.goal_material] {
                if !path.is_absolute() || pin.is_zero() {
                    return invalid("frozen numerical-read Source/pin");
                }
            }
            Ok(dataset_window::FrozenNeuronDescriptorV3 {
                checkpoint_response: ContextSource {
                    path: frozen.checkpoint_response.0.to_path_buf(),
                    digest: frozen.checkpoint_response.1.to_string(),
                },
                goal_material: ContextSource {
                    path: frozen.goal_material.0.to_path_buf(),
                    digest: frozen.goal_material.1.to_string(),
                },
            })
        })
        .transpose()?;
    d.ndu.journal_path = inputs.ndu_journal_source.0.to_path_buf();
    d.ndu_journal_digest = inputs.ndu_journal_source.1.to_string();
    // Scope and ACK belong to the actual held Serving owner. The independent
    // training material and learning trust remain unchanged.
    d.neuron.journal_path = goal.generation_store.clone();
    d.neuron.scope_digest = goal.scope.scope_digest.to_string();
    d.neuron.objective_digest = goal.scope.objective_digest.to_string();
    d.neuron.max_records = goal.store_context.max_records;
    d.neuron.anchor_sequence = inputs.neuron_anchor.sequence;
    d.neuron.anchor_checkpoint_digest = inputs.neuron_anchor.checkpoint_digest.to_string();
    d.neuron.config = native_descriptor(&material.native);
    let bytes = serde_json::to_vec(&d)?;
    if bytes.len() as u64 > MAX_DESCRIPTOR_BYTES {
        return invalid("whole projected context byte bound");
    }
    Ok(bytes)
}

fn dataset_descriptor(dataset: &DatasetSnapshotReceiptV3) -> DatasetReceiptDescriptorV1 {
    let s = &dataset.snapshot;
    let p = &dataset.producer;
    DatasetReceiptDescriptorV1 {
        snapshot: DatasetSnapshotDescriptorV1 {
            snapshot_id: s.snapshot_id.to_string(),
            ledger_head_digest: s.ledger_head_digest.to_string(),
            objective_digest: s.objective_digest.to_string(),
            eligible_frontier: s.eligible_frontier,
            outcome_watermark: s.outcome_watermark,
            source_record_digests: s
                .source_record_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            pending_outcomes: s.pending_outcomes,
            censored_outcomes: s.censored_outcomes,
            dataset_digest: s.dataset_digest.to_string(),
        },
        producer: PrincipalDescriptorV1 {
            principal_id: p.principal_id.to_string(),
            credential_chain_digest: p.credential_chain_digest.to_string(),
            signing_key_digest: p.signing_key_digest.to_string(),
            scope_digest: p.scope_digest.to_string(),
            authority_epoch: p.authority_epoch,
            authenticated_at: p.authenticated_at,
            expires_at: p.expires_at,
        },
        correction_cut_digest: dataset.correction_cut_digest.to_string(),
        revocation_cut_digest: dataset.revocation_cut_digest.to_string(),
        inclusion_policy_digest: dataset.inclusion_policy_digest.to_string(),
    }
}

fn native_descriptor(n: &SparseConfig) -> SparseConfigDescriptorV1 {
    SparseConfigDescriptorV1 {
        model_digest: n.model_digest.to_string(),
        normalization_digest: n.normalization_digest.to_string(),
        generation: n.generation.get(),
        width: n.width,
        top_k: n.top_k,
        temporal_decay_q24: n.temporal_decay_q24,
        inhibition_gain_q24: n.inhibition_gain_q24,
        inhibition: n
            .inhibition
            .iter()
            .map(|e| InhibitoryEdgeDescriptorV1 {
                source: e.source,
                target: e.target,
                weight_q24: e.weight_q24,
            })
            .collect(),
        activity_decay_q24: n.activity_decay_q24,
        target_activity_q24: n.target_activity_q24,
        threshold_rate_q24: n.threshold_rate_q24,
        threshold_min_q24: n.threshold_min_q24,
        threshold_max_q24: n.threshold_max_q24,
        eligibility_decay_q24: n.eligibility_decay_q24,
    }
}

#[path = "plasticity_input_context_dataset_projection_v3.rs"]
mod dataset_projection;
