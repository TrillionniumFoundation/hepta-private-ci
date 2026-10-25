//! Read back real durable stores using the public independently anchored APIs.

use std::fs::OpenOptions;
use std::path::Path;
use codex_hepta_agentd::NativeMemoryModelConfigV1;
use codex_hepta_agentd::NativeMemoryShadowReadV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseJournal;
use codex_hepta_neuron::canonical_model_output_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde_json::Value;
use super::ControlledQualificationContext;
use super::MAX_RECORDS;
use super::descriptor;
use super::profile;
use crate::native_memory_support::owner;

pub fn journal_evidence(
    root: &Path, model: &NativeMemoryModelConfigV1, context: &ControlledQualificationContext,
    result: &NativeMemoryShadowReadV1,
) -> anyhow::Result<Value> {
    let source = &result.source().binding;
    let registered = profile(model)?;
    let profile_digest = descriptor(model)?.semantic_digest()?;
    // Independent diagnostic derivation from the actual admitted source and
    // explicit profile; the witness header is not accepted as its own authority.
    let namespace = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.memory-cell.shadow-namespace.v1", owner()?.as_str(), context.subject.as_str(),
        registered.cell_id.as_str(), &source.memory, source.memory_content_sha256.as_str(),
        source.source_content_sha256.as_str(), source.event_digest.to_string(),
        source.production_receipt_digest.as_str(), &model.scope, model.rank, model.seed,
        &model.pins, profile_digest.to_string(),
    ))?);
    let subject = context.subject.as_str().as_bytes();
    let scope = JournalScope {
        scope_digest: Digest32::of_parts(&[b"hepta.neuron.subject-scope.v1",
            &u32::try_from(subject.len())?.to_be_bytes(), subject]),
        objective_digest: context.objective,
    };
    let open = |name| OpenOptions::new().read(true).write(true).open(root.join(name));
    let witness = FileAnchorWitnessStore::open(open("shadow-witness")?,
        JournalScope { scope_digest: namespace, objective_digest: context.objective },
        Generation::new(model.generation)?, MAX_RECORDS)?;
    let anchor = witness.current()?.ok_or_else(|| anyhow::anyhow!("actual witness anchor absent"))?;
    let expected = JournalAnchor { sequence: 1, checkpoint_digest: result.observation().checkpoint_after };
    anyhow::ensure!(anchor == expected, "actual witness differs from returned shadow checkpoint");
    let journal = SparseJournal::open_anchored(open("shadow-journal")?, registered.sparse,
        scope, MAX_RECORDS, anchor)?;
    anyhow::ensure!(journal.current_anchor()? == Some(anchor), "actual journal/witness anchors differ");
    let journal_bytes = std::fs::read(root.join("shadow-journal"))?;
    let witness_bytes = std::fs::read(root.join("shadow-witness"))?;
    Ok(serde_json::json!({
        "journal_anchor": {"sequence": anchor.sequence, "checkpoint_digest": anchor.checkpoint_digest.to_string()},
        "witness_anchor": {"sequence": anchor.sequence, "checkpoint_digest": anchor.checkpoint_digest.to_string()},
        "journal_sha256": Digest32::of_bytes(&journal_bytes).to_string(), "journal_bytes": journal_bytes.len(),
        "witness_sha256": Digest32::of_bytes(&witness_bytes).to_string(), "witness_bytes": witness_bytes.len(),
        "namespace_digest": namespace.to_string(), "shadow_profile_digest": profile_digest.to_string(),
        "witness_namespace_independently_derived": true,
        "independent_operational_witness_trust_qualified": false,
    }))
}

pub fn read_evidence(root: &Path, model: &NativeMemoryModelConfigV1, context: &ControlledQualificationContext,
    result: &NativeMemoryShadowReadV1) -> anyhow::Result<Value> {
    let execution = result.execution();
    let raw_path = model.receipt_directory.join(&execution.request_sha256).join("request.json");
    let raw = std::fs::read(&raw_path)?;
    anyhow::ensure!(Digest32::of_bytes(&raw).to_string() == execution.request_sha256, "raw request hash differs");
    let request: Value = serde_json::from_slice(&raw)?;
    let observation = result.observation();
    let binding = &result.source().binding;
    let joint = Digest32::of_parts(&[b"hepta.memory-cell.source-query-tick.v1",
        binding.binding_digest.as_array(), binding.query_digest.as_array(), observation.input_digest.as_array()]);
    anyhow::ensure!(request["schema"] == "hepta.memory-cell.native-request.v2"
        && request["tick_binding"]["tick_digest"] == observation.input_digest.to_string()
        && request["tick_binding"]["source_binding_digest"] == binding.binding_digest.to_string()
        && request["tick_binding"]["query_digest"] == binding.query_digest.to_string()
        && request["tick_binding"]["joint_digest"] == joint.to_string()
        && request["neuron_request"]["input_digest"] == observation.input_digest.to_string(),
        "actual callback is not the admitted v2 tick/source/query");
    anyhow::ensure!(request["tick_binding"]["subject_id"] == context.subject.as_str()
        && request["tick_binding"]["objective_digest"] == context.objective.to_string()
        && request["tick_binding"]["ndu_snapshot_digest"] == context.ndu.to_string()
        && request["tick_binding"]["logical_sequence"] == 1
        && request["tick_binding"]["checkpoint_digest"] == Digest32::ZERO.to_string()
        && request["tick_binding"]["body_generation"].is_null()
        && request["tick_binding"]["modulator_digest"].is_null(),
        "actual tick differs from the explicitly controlled qualification context");
    anyhow::ensure!(observation.abstain && !observation.authority.grants_any(), "shadow escaped abstain/deny-all");
    anyhow::ensure!(execution.decoder_queries == 1 && execution.feature_forward_calls == 1,
        "unexpected actual decoder/feature count");
    let resources = &observation.resource_receipt;
    let runtime = &observation.model_runtime;
    let runtime_receipt_digest = runtime.semantic_digest()?;
    let model_output_digest = canonical_model_output_digest_v1(&execution.drive_q24, &execution.prediction_q24, runtime)?;
    let encoder: Digest32 = request["neuron_request"]["encoder_digest"].as_str()
        .ok_or_else(|| anyhow::anyhow!("actual encoder digest absent"))?.parse()?;
    let head: Digest32 = request["neuron_request"]["head_digest"].as_str()
        .ok_or_else(|| anyhow::anyhow!("actual head digest absent"))?.parse()?;
    let model_binding = Digest32::of_parts(&[b"hepta.neuron.model-runtime-binding.v1",
        encoder.as_array(), head.as_array(), model_output_digest.as_array(), runtime_receipt_digest.as_array()]);
    anyhow::ensure!(model_binding == observation.model_runtime_digest, "full model/output/runtime binding differs");
    Ok(serde_json::json!({
        "schema": "hepta.memory-cell.controlled-shadow-read.v1", "execution": execution,
        "source": result.source(), "request_path": raw_path, "request": request,
        "retained_owner": root, "observation": {
            "tick_id": observation.tick_id.as_str(), "input_digest": observation.input_digest.to_string(),
            "checkpoint_before": observation.checkpoint_before.to_string(), "checkpoint_after": observation.checkpoint_after.to_string(),
            "activation_digest": observation.activation_digest.to_string(), "temporal_state_digest": observation.temporal_state_digest.to_string(),
            "model_runtime_digest": observation.model_runtime_digest.to_string(), "signals_q24": observation.signals_q24,
            "runtime_receipt_digest": runtime_receipt_digest.to_string(), "model_output_digest": model_output_digest.to_string(),
            "sparsity_ppm": observation.sparsity_ppm, "abstain": observation.abstain, "authority_grants_any": observation.authority.grants_any(),
            "resource_receipt": {"execution_micros": resources.execution_micros, "transient_allocation_bytes": resources.transient_allocation_bytes,
                "checkpoint_bytes": resources.checkpoint_bytes, "journal_bytes_written": resources.journal_bytes_written,
                "write_amplification_ppm": resources.write_amplification_ppm, "saturation_count": resources.saturation_count,
                "queue_age_micros": resources.queue_age_micros},
            "model_runtime": {"model_id": runtime.model_id.as_str(), "model_manifest_digest": runtime.model_manifest_digest.to_string(),
                "weights_digest": runtime.weights_digest.to_string(), "tokenizer_digest": runtime.tokenizer_digest.to_string(),
                "preprocessor_digest": runtime.preprocessor_digest.to_string(), "quantization_id": runtime.quantization_id.as_str(),
                "quantization_digest": runtime.quantization_digest.to_string(), "backend_id": runtime.backend_id.as_str(),
                "runtime_digest": runtime.runtime_digest.to_string(), "device_identity_digest": runtime.device_identity_digest.to_string(),
                "latency_micros": runtime.latency_micros, "resident_bytes": runtime.resident_bytes},
        },
        "calibration": null, "production_qualified": false,
    }))
}
