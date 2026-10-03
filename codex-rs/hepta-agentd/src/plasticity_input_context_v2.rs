//! Reconstruct input facts for the same held plasticity owner. This reader
//! never opens a learning writer, proposal writer or Neuron store.
use super::*;
use crate::PlasticityNeuronEligibilityReaderV2;
use crate::plasticity_runtime::input_context::PlasticityInputContextV2;
use codex_hepta_agent_components::neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_agent_components::neuron::decode_neuron_generation_material_v2;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ContextDescriptor {
    schema: String,
    agent_id: String,
    spawn_generation: u64,
    round_hex: String,
    predecessor_registry_head_digest: String,
    baseline_id: String,
    objective_digest: String,
    baseline_material: ContextSource,
    artifacts: ArtifactSnapshotDescriptorV1,
    dataset: DatasetReceiptDescriptorV1,
    ndu: NduDescriptorV1,
    ndu_journal_digest: String,
    neuron: NeuronDescriptorV1,
    signal_bindings: Vec<SignalBindingDescriptorV1>,
    trust: TrustDescriptorV1,
    owner_policy: OwnerPolicyDescriptorV1,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ContextSource {
    path: PathBuf,
    digest: String,
}

pub(crate) fn load_input_context_v2(
    path: &Path,
    pin: Digest32,
    identity: &AgentdIdentity,
    ledger: &DurableLedger,
    neuron: Arc<crate::AgentdNeuronRuntimeV2Host>,
    now: u64,
) -> Result<PlasticityInputContextV2, AgentdError> {
    let bytes = protected_context_bytes(path, pin, MAX_DESCRIPTOR_BYTES)?;
    let d: ContextDescriptor = serde_json::from_slice(&bytes)?;
    if d.schema != "hepta.agentd.plasticity-input-context.v2"
        || d.agent_id != identity.agent_id.as_str()
        || d.spawn_generation != identity.spawn_generation
    {
        return invalid("plasticity input context identity/schema");
    }
    let round = crate::AgentdSelfIterationRoundV1::decode(&decode_round(&d.round_hex)?)?;
    let objective = digest(&d.objective_digest, "context objective")?;
    let material = decode_neuron_generation_material_v2(&protected_context_bytes(
        &d.baseline_material.path,
        digest(&d.baseline_material.digest, "baseline material source")?,
        MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
    )?)
    .map_err(|e| AgentdError::Invalid(format!("full context baseline: {e}")))?;
    let baseline = stable_id(&d.baseline_id, "context baseline")?;
    if material.scope.objective_digest != objective
        || material
            .native
            .digest()
            .map_err(|e| AgentdError::Invalid(e.to_string()))?
            != sparse_config(&d.neuron.config)?
                .digest()
                .map_err(|e| AgentdError::Invalid(e.to_string()))?
    {
        return invalid("plasticity context full baseline/native differs");
    }
    // Reuse the original authenticated snapshot codec. The receipt pins its
    // complete bytes; Root custody protects its independently chosen source.
    let _ = protected_context_bytes(
        &d.artifacts.path,
        digest(&d.artifacts.receipt.file_digest, "artifact file")?,
        u64::try_from(d.artifacts.receipt.encoded_bytes)
            .map_err(|_| AgentdError::Invalid("artifact bound".into()))?
            .min(64 * 1024 * 1024),
    )?;
    let artifacts = load_artifacts(&d.artifacts)?;
    let selected = artifacts
        .manifest(&baseline)
        .ok_or_else(|| AgentdError::Invalid("context baseline artifact missing".into()))?;
    validate_context_baseline_artifact(
        selected,
        material.runtime.generation,
        material.native.model_digest,
        material.scope.objective_digest,
    )?;
    let dataset = build_dataset_receipt(&d.dataset)?;
    if dataset.snapshot.objective_digest != objective
        || dataset.snapshot.ledger_head_digest
            != ledger
                .snapshot()
                .map_err(|e| AgentdError::Invalid(e.to_string()))?
                .head_digest
    {
        return invalid("context dataset differs from the same held learning ledger");
    }
    verify_dataset_snapshot_receipt_v3(&dataset, now)
        .map_err(|e| AgentdError::Invalid(format!("context dataset receipt: {e}")))?;
    if now < d.artifacts.observed_at || now >= d.artifacts.expires_at {
        return invalid("context artifact observation window");
    }
    let current = d
        .artifacts
        .current_owner
        .as_ref()
        .ok_or_else(|| AgentdError::Invalid("context CURRENT missing".into()))?
        .source()?;
    let policy_ids = [
        &d.artifacts.update_rule_artifact_id,
        &d.artifacts.mutation_policy_artifact_id,
        &d.artifacts.broadcast_artifact_id,
    ]
    .map(|s| stable_id(s, "context policy"));
    let [a, b, c] = policy_ids;
    let policy_ids = [a?, b?, c?];
    let owner_policy = build_owner_policy(&d.owner_policy)?;
    let current_artifacts =
        crate::plasticity_runtime::current_artifacts::PlasticityCurrentArtifactsV1::new(
            current,
            policy_ids.clone(),
            &artifacts,
            &owner_policy,
        )?;
    current_artifacts.verify(&artifacts, &baseline, now)?;
    let ndu = NduProjectionJournalV1::reopen(&protected_context_bytes(
        &d.ndu.journal_path,
        digest(&d.ndu_journal_digest, "context NDU source")?,
        MAX_NDU_JOURNAL_BYTES,
    )?)
    .map_err(|e| AgentdError::Invalid(format!("context NDU: {e}")))?;
    let scope = JournalScope {
        scope_digest: digest(&d.neuron.scope_digest, "actual V2 scope")?,
        objective_digest: digest(&d.neuron.objective_digest, "actual V2 objective")?,
    };
    let reader = PlasticityNeuronEligibilityReaderV2::new(
        neuron,
        crate::neuron_runtime_v2::AgentdNeuronGenerationIdV2::from_generation(
            material.runtime.generation,
        ),
        material
            .runtime
            .semantic_digest()
            .map_err(|e| AgentdError::Invalid(e.to_string()))?,
        material
            .body
            .semantic_digest()
            .map_err(|e| AgentdError::Invalid(e.to_string()))?,
        scope,
    )
    .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    let dynamic = PlasticityDynamicOwnerEvidenceResolverV1::with_neuron_reader(
        objective,
        digest(&d.ndu.subject_digest, "NDU subject")?,
        stable_id(&d.ndu.owner_id, "NDU owner")?,
        stable_id(&d.neuron.owner_id, "Neuron owner")?,
        Arc::new(RwLock::new(ndu)),
        d.ndu
            .modulator_values_raw_q32
            .iter()
            .copied()
            .map(FixedQ32::from_raw)
            .collect(),
        Arc::new(reader),
        JournalAnchor {
            sequence: d.neuron.anchor_sequence,
            checkpoint_digest: digest(&d.neuron.anchor_checkpoint_digest, "actual V2 ACK")?,
        },
        artifacts.clone(),
        policy_ids[2].clone(),
        d.signal_bindings
            .iter()
            .map(signal_binding)
            .collect::<Result<Vec<_>, _>>()?,
        d.artifacts.observed_at,
        d.artifacts.expires_at,
    )
    .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    verify_fact_policy_bindings(
        &d.owner_policy,
        &d.artifacts,
        &d.ndu,
        &d.neuron,
        &artifacts,
        &dataset,
    )?;
    let resolver = ConcretePlasticityOwnerEvidenceResolverV1::new(
        dataset,
        artifacts.clone(),
        d.artifacts.observed_at,
        d.artifacts.expires_at,
        vec![
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
                artifact_id: policy_ids[0].clone(),
            },
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::MutationPolicy,
                artifact_id: policy_ids[1].clone(),
            },
        ],
        Box::new(dynamic),
    )
    .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    let verifier = build_verifier(&d.trust, objective)?;
    if verifier.scope_digest() != material.scope.scope_digest
        || verifier.objective_digest() != material.scope.objective_digest
    {
        return invalid("whole learning trust differs from actual training material scope");
    }
    if protected_context_bytes(path, pin, MAX_DESCRIPTOR_BYTES)? != bytes {
        return invalid("protected plasticity context changed");
    }
    Ok(PlasticityInputContextV2 {
        round,
        source: (path.to_path_buf(), pin),
        predecessor: digest(&d.predecessor_registry_head_digest, "context predecessor")?,
        baseline,
        baseline_source: Some((
            d.baseline_material.path,
            digest(&d.baseline_material.digest, "baseline material source")?,
        )),
        baseline_material: Some(material),
        artifacts,
        current_artifacts,
        resolver: Box::new(resolver),
        policy: owner_policy,
        verifier,
    })
}

fn decode_round(hex: &str) -> Result<Vec<u8>, AgentdError> {
    if hex.is_empty()
        || hex.len() > 8192
        || !hex.len().is_multiple_of(2)
        || hex
            .bytes()
            .any(|c| !c.is_ascii_digit() && !(b'a'..=b'f').contains(&c))
    {
        return invalid("context original Round hex");
    }
    hex.as_bytes()
        .chunks_exact(2)
        .map(|c| {
            u8::from_str_radix(
                std::str::from_utf8(c).map_err(|e| AgentdError::Invalid(e.to_string()))?,
                16,
            )
            .map_err(|e| AgentdError::Invalid(e.to_string()))
        })
        .collect()
}

pub(crate) fn protected_context_bytes(
    path: &Path,
    pin: Digest32,
    max: u64,
) -> Result<Vec<u8>, AgentdError> {
    if pin.is_zero() || !path.is_absolute() || path.canonicalize()? != path {
        return invalid("protected context canonical source/pin");
    }
    for parent in path
        .parent()
        .ok_or_else(|| AgentdError::Invalid("context parent".into()))?
        .ancestors()
    {
        let m = std::fs::symlink_metadata(parent)?;
        if !m.is_dir() || m.uid() != 0 || m.mode() & 0o022 != 0 {
            return invalid("Root context directory custody");
        }
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let before = file.metadata()?;
    if !before.is_file()
        || before.uid() != 0
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() == 0
        || before.len() > max
    {
        return invalid("Root context file custody/size");
    }
    let mut bytes = Vec::new();
    (&mut file).take(max + 1).read_to_end(&mut bytes)?;
    let after = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    let same = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if bytes.len() as u64 > max
        || same(&before) != same(&after)
        || same(&after) != same(&named)
        || Digest32::of_bytes(&bytes) != pin
    {
        return invalid("Root context whole source changed");
    }
    Ok(bytes)
}

// Runtime model identity remains stable across sparse generations. The selected
// artifact is independently versioned by the original CURRENT registry.
pub(crate) fn validate_context_baseline_artifact(
    selected: &codex_hepta_agent_components::learning_artifacts::ArtifactManifest,
    generation: codex_hepta_agent_components::types::Generation,
    head: Digest32,
    objective: Digest32,
) -> Result<(), AgentdError> {
    use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
    if !matches!(
        selected.kind,
        ArtifactKind::Parameters | ArtifactKind::Model
    ) || selected.generation != generation
        || selected.content_digest != head
        || selected.objective_digest != objective
    {
        return invalid("context CURRENT model artifact differs from actual full material");
    }
    Ok(())
}

#[path = "plasticity_input_context_projection_v2.rs"]
mod projection;
pub use projection::ParameterInputContextProjectionV2;
pub use projection::project_parameter_input_context_v2;
