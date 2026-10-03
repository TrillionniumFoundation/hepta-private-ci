//! Independently protected full factual material for the original Root join.
//! Reading and validating it creates no worker, store, signer or admission.
use crate::CpuNeuronGenerationPlanV1;
use crate::CpuNeuronParameterMaterialCandidateV2;
use crate::CpuNeuronParameterMaterialPlanV2;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agent_components::intelligence::*;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

const MAX_DESCRIPTOR_BYTES: u64 = 64 * 1024;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    canonical_envelope: InstalledCpuSourceV1,
    parameter_request: InstalledCpuSourceV1,
    baseline: InstalledCpuSourceV1,
    baseline_candidate_id: String,
    test_plan_digest: String,
    candidates: Vec<CandidateSources>,
    rollback: InstalledCpuSourceV1,
    worker_program: InstalledCpuSourceV1,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateSources {
    candidate_id: String,
    generation: InstalledCpuSourceV1,
    canary_tick: InstalledCpuSourceV1,
    canary_port: InstalledCpuSourceV1,
}
struct Candidate {
    id: StableId,
    generation: CpuNeuronGenerationPlanV1,
    tick: NeuronTickInputV1,
    port: CanonicalPortInputV1,
}

/// Complete protected materials; original effect owners still validate actual
/// completed receipts, signatures, CURRENT, Fleet and the physical model facts.
pub struct CpuNeuronParameterRootMaterialsV2 {
    sources: Vec<(InstalledCpuSourceV1, u64)>,
    worker: worker::VerifiedWorker,
    canonical: CanonicalIterationEnvelopeV1,
    envelope: IterationEnvelopeV1,
    request: ParameterPlasticityProductRequestV1,
    baseline: CpuNeuronGenerationPlanV1,
    baseline_id: StableId,
    test_plan_digest: Digest32,
    candidates: Vec<Candidate>,
    rollback: CpuNeuronGenerationPlanV1,
}
impl CpuNeuronParameterRootMaterialsV2 {
    pub fn from_protected_source(
        source: &InstalledCpuSourceV1,
        expected_worker_elf: Digest32,
    ) -> Result<Self, AgentdError> {
        let descriptor_bytes = read(source, MAX_DESCRIPTOR_BYTES)?;
        let descriptor: Descriptor = serde_json::from_slice(&descriptor_bytes)?;
        if descriptor.schema != "hepta.cpu-neuron.parameter-root-materials.v2"
            || descriptor.candidates.is_empty()
            || descriptor.candidates.len() > 32
        {
            return Err(invalid("bounded protected CPU material descriptor"));
        }
        let worker = worker::VerifiedWorker::open(&descriptor.worker_program, expected_worker_elf)?;
        let mut sources = vec![(source.clone(), MAX_DESCRIPTOR_BYTES)];
        let canonical = CanonicalIterationEnvelopeV1::decode(&read_retained(
            &descriptor.canonical_envelope,
            262_144,
            &mut sources,
        )?)
        .map_err(invalid)?;
        let request = decode_parameter_plasticity_request_v1(&read_retained(
            &descriptor.parameter_request,
            MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1 as u64,
            &mut sources,
        )?)
        .map_err(|error| invalid(error.to_string()))?;
        let policy = canonical.policy();
        // Compatibility is explicit. Full canonical policy is retained separately
        // and checked by its original policy owner before any effect.
        let envelope = IterationEnvelopeV1 {
            envelope_id: StableId::new(policy.envelope_id)
                .map_err(|error| invalid(error.to_string()))?,
            base_commit: Digest32::of_bytes(policy.base_commit.as_bytes()),
            base_tree: Digest32::of_bytes(policy.base_tree.as_bytes()),
            objective_digest: digest(policy.objective_digest)?,
            grammar_digest: digest(policy.grammar_digest)?,
            maximum_files: u16::try_from(policy.maximum_files)
                .map_err(|error| invalid(error.to_string()))?,
            maximum_diff_bytes: policy.maximum_bytes,
            maximum_candidates: u16::try_from(request.generated.candidates.len())
                .map_err(|error| invalid(error.to_string()))?,
            maximum_parallel_sandboxes: policy.compute_budget.maximum_parallel_sandboxes,
            expiry_unix_seconds: policy.expires_unix_ms / 1000,
        };
        envelope.validate().map_err(invalid)?;
        if u32::from(envelope.maximum_candidates) > policy.maximum_candidates {
            return Err(invalid(
                "actual frontier exceeds protected canonical window",
            ));
        }
        let baseline = plan(&descriptor.baseline, &mut sources)?;
        let rollback = plan(&descriptor.rollback, &mut sources)?;
        let mut candidates = Vec::new();
        for source in descriptor.candidates {
            let id =
                StableId::new(source.candidate_id).map_err(|error| invalid(error.to_string()))?;
            if candidates
                .iter()
                .any(|candidate: &Candidate| candidate.id == id)
            {
                return Err(invalid("duplicate protected candidate material"));
            }
            let generation = plan(&source.generation, &mut sources)?;
            let tick = codex_hepta_neuron::decode_neuron_tick_input_v1(&read_retained(
                &source.canary_tick,
                262_144,
                &mut sources,
            )?)
            .map_err(|error| invalid(error.to_string()))?;
            let port = decode_canonical_port_input_material_v1(&read_retained(
                &source.canary_port,
                MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1 as u64,
                &mut sources,
            )?)
            .map_err(|error| invalid(error.to_string()))?;
            if tick
                .journal_scope()
                .map_err(|error| invalid(error.to_string()))?
                != generation.scope
                || tick.body_generation != Some(generation.runtime.generation.get())
                || tick.feature_vector_q24.len() != generation.runtime.input_feature_dimension
                || port.stage != CanonicalStageV1::NeuralSignalCollected
                || port.objective_digest != envelope.objective_digest
                || port.budget_micros == 0
            {
                return Err(invalid(
                    "protected canary differs from its full original generation",
                ));
            }
            candidates.push(Candidate {
                id,
                generation,
                tick,
                port,
            });
        }
        let materials = Self {
            sources,
            worker,
            canonical,
            envelope,
            request,
            baseline,
            baseline_id: StableId::new(descriptor.baseline_candidate_id)
                .map_err(|error| invalid(error.to_string()))?,
            test_plan_digest: digest(&descriptor.test_plan_digest)?,
            candidates,
            rollback,
        };
        materials.with_plan(crate::validate_cpu_neuron_parameter_materials_v2)?;
        materials.revalidate_sources()?;
        Ok(materials)
    }
    pub fn request(&self) -> &ParameterPlasticityProductRequestV1 {
        &self.request
    }
    pub fn canonical_envelope(&self) -> &CanonicalIterationEnvelopeV1 {
        &self.canonical
    }
    pub fn execution_envelope(&self) -> &IterationEnvelopeV1 {
        &self.envelope
    }
    pub fn baseline(&self) -> &CpuNeuronGenerationPlanV1 {
        &self.baseline
    }
    pub fn rollback(&self) -> &CpuNeuronGenerationPlanV1 {
        &self.rollback
    }
    pub fn candidate_canary(
        &self,
        id: &StableId,
    ) -> Option<(&NeuronTickInputV1, &CanonicalPortInputV1)> {
        self.candidates
            .iter()
            .find(|candidate| &candidate.id == id)
            .map(|candidate| (&candidate.tick, &candidate.port))
    }
    /// Borrow the same pure material facade. Temporary references never escape.
    pub fn with_plan<T>(
        &self,
        inspect: impl FnOnce(&CpuNeuronParameterMaterialPlanV2<'_>) -> T,
    ) -> T {
        let candidates: Vec<_> = self
            .candidates
            .iter()
            .map(|candidate| CpuNeuronParameterMaterialCandidateV2 {
                candidate_id: &candidate.id,
                generation: &candidate.generation,
            })
            .collect();
        inspect(&CpuNeuronParameterMaterialPlanV2 {
            envelope: &self.envelope,
            baseline_runtime: &self.baseline.runtime,
            baseline_native: &self.baseline.native,
            baseline_body: &self.baseline.body,
            baseline_candidate_id: &self.baseline_id,
            request: &self.request,
            test_plan_digest: self.test_plan_digest,
            candidates: &candidates,
            rollback: &self.rollback,
        })
    }
    pub fn revalidate_sources(&self) -> Result<(), AgentdError> {
        self.worker.revalidate()?;
        for (source, bound) in &self.sources {
            read(source, *bound)?;
        }
        Ok(())
    }
}
fn digest(text: &str) -> Result<Digest32, AgentdError> {
    let value: Digest32 = text
        .parse()
        .map_err(|error| invalid(format!("protected material digest: {error}")))?;
    if value.is_zero() || value.to_string() != text {
        return Err(invalid("nonzero canonical protected material digest"));
    }
    Ok(value)
}
fn read(source: &InstalledCpuSourceV1, bound: u64) -> Result<Vec<u8>, AgentdError> {
    let expected = digest(&source.digest)?;
    let bytes =
        read_root_review_input(&source.path, bound).map_err(|error| invalid(error.to_string()))?;
    if Digest32::of_bytes(&bytes) != expected {
        return Err(invalid("protected CPU material Source pin changed"));
    }
    Ok(bytes)
}
fn read_retained(
    source: &InstalledCpuSourceV1,
    bound: u64,
    sources: &mut Vec<(InstalledCpuSourceV1, u64)>,
) -> Result<Vec<u8>, AgentdError> {
    let bytes = read(source, bound)?;
    sources.push((source.clone(), bound));
    Ok(bytes)
}
fn plan(
    source: &InstalledCpuSourceV1,
    sources: &mut Vec<(InstalledCpuSourceV1, u64)>,
) -> Result<CpuNeuronGenerationPlanV1, AgentdError> {
    let bytes = read_retained(
        source,
        codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        sources,
    )?;
    let plan = crate::decode_cpu_neuron_generation_material_v2(&bytes)?;
    let manifest_source = InstalledCpuSourceV1 {
        path: plan.model_manifest.clone(),
        digest: plan.model_manifest_digest.to_string(),
    };
    let manifest: crate::local_cpu_model::CpuNeuronManifestV1 =
        serde_json::from_slice(&read_retained(&manifest_source, 64 * 1024, sources)?)?;
    if manifest.version != 1
        || manifest.model_id != plan.runtime.model_id.as_str()
        || manifest.weights_digest != plan.runtime.weights_digest.to_string()
        || manifest.encoder_digest != plan.runtime.encoder_digest.to_string()
        || manifest.head_digest != plan.runtime.head_digest.to_string()
        || manifest.tokenizer_digest != plan.runtime.tokenizer_digest.to_string()
        || manifest.preprocessor_digest != plan.runtime.preprocessor_digest.to_string()
        || manifest.quantization_digest != plan.runtime.quantization_digest.to_string()
        || manifest.runtime_digest != plan.runtime.runtime_digest.to_string()
        || manifest.device_digest != plan.runtime.device_digest.to_string()
    {
        return Err(invalid(
            "protected full material model manifest tuple changed",
        ));
    }
    let mut components = std::path::Path::new(&manifest.weights_filename).components();
    if !matches!(components.next(), Some(std::path::Component::Normal(_)))
        || components.next().is_some()
        || manifest.weights_filename.len() > 255
    {
        return Err(invalid("protected original weights filename"));
    }
    let weights = InstalledCpuSourceV1 {
        path: plan
            .model_manifest
            .parent()
            .ok_or_else(|| invalid("model parent"))?
            .join(manifest.weights_filename),
        digest: manifest.weights_digest,
    };
    read_retained(&weights, 16 * 1024 * 1024, sources)?;
    Ok(plan)
}
fn invalid(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}
#[path = "local_cpu_parameter_root_worker_v2.rs"]
mod worker;

#[cfg(test)]
#[path = "local_cpu_parameter_root_materials_v2_tests.rs"]
mod tests;
