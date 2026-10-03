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

/// Emit bounded whole context bytes using the original descriptor types. The
/// caller must publish an immutable protected Source; these bytes grant no
/// authority and cannot replace the loader's held Ledger/Neuron/CURRENT checks.
pub fn project_parameter_input_context_v2(
    template_bytes: &[u8],
    inputs: &ParameterInputContextProjectionV2<'_>,
) -> Result<Vec<u8>, AgentdError> {
    if template_bytes.is_empty() || template_bytes.len() as u64 > MAX_DESCRIPTOR_BYTES {
        return invalid("whole plasticity context template byte bound");
    }
    let mut d: ContextDescriptor = serde_json::from_slice(template_bytes)?;
    let material = inputs.baseline_material;
    let material_bytes = encode_neuron_generation_material_v2(material)
        .map_err(|e| AgentdError::Invalid(format!("full context baseline: {e}")))?;
    // Canonical whole comparison permits only the original Goal projection's
    // scope and three store paths. Runtime/native/body and every context limit
    // remain identical, rather than comparing a handful of digest handles.
    let goal = inputs.neuron_material;
    let mut neutral_goal = goal.clone();
    neutral_goal.scope = material.scope;
    neutral_goal.store_context.scope = material.scope;
    neutral_goal.index_context.scope = material.scope;
    neutral_goal.witness_context.scope = material.scope;
    neutral_goal
        .generation_store
        .clone_from(&material.generation_store);
    neutral_goal
        .runtime_index
        .clone_from(&material.runtime_index);
    neutral_goal.witness.clone_from(&material.witness);
    encode_neuron_generation_material_v2(goal)
        .map_err(|e| AgentdError::Invalid(format!("whole actual Goal material: {e}")))?;
    if encode_neuron_generation_material_v2(&neutral_goal)
        .map_err(|e| AgentdError::Invalid(e.to_string()))?
        != material_bytes
    {
        return invalid("actual Goal projection changed whole training runtime/native/body");
    }
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
    let dataset = inputs
        .dataset
        .dataset
        .native()
        .map_err(|e| AgentdError::Invalid(format!("whole context dataset: {e}")))?;
    verify_dataset_snapshot_receipt_v3(&dataset, now)
        .map_err(|e| AgentdError::Invalid(format!("context dataset receipt: {e}")))?;
    verify_dataset_snapshot_receipt_v3(&dataset, expires - 1)
        .map_err(|e| AgentdError::Invalid(format!("context dataset window: {e}")))?;
    let installed_head = digest(
        &inputs.dataset.installed_artifact_head,
        "held installed artifact head",
    )?;
    // Zero is a valid FIRST proposal predecessor, unlike an installed head.
    let _proposal_predecessor =
        Digest32::from_str(&inputs.dataset.proposal_registry_predecessor)
            .map_err(|_| AgentdError::Invalid("held proposal predecessor".into()))?;
    if dataset.snapshot.objective_digest != objective
        || dataset.snapshot.ledger_head_digest.to_string() != inputs.dataset.ledger_head_digest
        || dataset.snapshot.eligible_frontier > inputs.dataset.ledger_record_count
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
    // The raw freeze preimage is a complete unsigned owner fact, not a signer
    // grant. Preserve its original strict byte/hex bound, without truncation.
    if inputs.dataset.freeze_payload_hex.is_empty()
        || inputs.dataset.freeze_payload_hex.len() > crate::MAX_CONTROL_FRAME_BYTES as usize
        || !inputs.dataset.freeze_payload_hex.len().is_multiple_of(2)
        || inputs
            .dataset
            .freeze_payload_hex
            .bytes()
            .any(|c| !c.is_ascii_digit() && !(b'a'..=b'f').contains(&c))
    {
        return invalid("complete original dataset freeze bytes");
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
