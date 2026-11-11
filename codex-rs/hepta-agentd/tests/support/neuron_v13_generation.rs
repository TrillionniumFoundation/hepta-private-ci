//! Deliberately invalid closure bytes, with the actual pinned proposal worker.
//! This qualifies entry/rejection/recovery wiring, never successful inference.

use std::fs;
use std::fs::File;
use std::path::Path;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::neuron_generation_process_identity_digest_v1;
use codex_hepta_agentd::prepare_agentd_v13_generation_worker_v1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

pub(crate) fn descriptor(root: &Path, identity: &AgentdIdentity) -> Result<Value> {
    let script =
        include_bytes!("../../../../qualification/neuron-v13-generation/proposal_worker.py");
    let worker_path = root.join("proposal_worker.py");
    fs::write(&worker_path, script)?;
    let mut catalog = Vec::new();
    let mut assets = Vec::new();
    for (index, name) in [
        "vendor/bounded_npz.py",
        "vendor/closure_common.py",
        "vendor/closure_inputs.py",
        "vendor/closure_io.py",
        "vendor/verify_closure.py",
        "vendor/PROVENANCE.json",
        "vendor/reference/adapter.py.source",
        "vendor/reference/backend.py.source",
        "vendor/reference/download_model.py.source",
        "vendor/reference/lifecycle.py.source",
        "vendor/reference/tasks.py.source",
        "model.npz",
        "sources.json",
        "training.npz",
        "encoder.json",
        "release.json",
        "encoder/onnx/model.onnx",
        "encoder/tokenizer.json",
        "encoder/config.json",
        "encoder/sentence_bert_config.json",
        "encoder/modules.json",
        "encoder/1_Pooling/config.json",
        "encoder/tokenizer_config.json",
        "encoder/special_tokens_map.json",
    ]
    .into_iter()
    .enumerate()
    {
        let path = root.join(format!("invalid-asset-{index}"));
        fs::write(&path, b"deliberately-invalid-closure")?;
        let digest = Digest32::of_bytes(b"deliberately-invalid-closure");
        catalog.push(json!({"name": name, "path": path, "digest": digest.to_string()}));
        assets.push(V13GenerationAssetFileV1 {
            name: name.into(),
            digest: digest.into_array(),
            file: File::open(path)?,
        });
    }
    let closure = V13LearningClosureV1 {
        checkpoint_digest: Digest32::of_bytes(b"deliberately-invalid-closure").into_array(),
        state_digest: [21; 32],
        encoder_digest: [22; 32],
        source_version: [23; 32],
        data_identity: [24; 32],
        learning: CellLearningBindingV2::Resumable {
            weights: [25; 32],
            optimizer: [26; 32],
            rng: [27; 32],
            sampler: [28; 32],
            training_cursor: [29; 32],
        },
    };
    let interpreter = fs::canonicalize("/usr/bin/python3")?;
    let interpreter_digest = Digest32::of_bytes(&fs::read(&interpreter)?);
    let worker_digest = Digest32::of_bytes(script);
    let device_digest = V13GenerationProcessWorkerV1::observed_device_digest()?;
    let source_digest = Digest32::of_bytes(b"invalid-closure-ordinary-entry-test-v1").into_array();
    let prepared = prepare_agentd_v13_generation_worker_v1(
        V13GenerationProcessConfigV1 {
            interpreter_argv0: interpreter.clone(),
            interpreter_digest: interpreter_digest.into_array(),
            worker_digest: worker_digest.into_array(),
            source_digest,
            device_digest,
            closure: closure.clone(),
            phase_cpu_seconds: 3,
            address_space_bytes: 512 * 1024 * 1024,
            wall_limit: Duration::from_secs(10),
        },
        V13GenerationProcessFilesV1 {
            interpreter: File::open(&interpreter)?,
            worker: File::open(&worker_path)?,
            assets,
        },
    )?;
    let manifest = CellBackendManifestV2 {
        profile: V13GenerationProcessWorkerV1::PROFILE.into(),
        source_digest,
        bundle_digest: prepared.worker().bundle_digest(),
        encoder: Some(closure.encoder_digest),
        head: Some([25; 32]),
        memory: None,
        world_model: None,
        decoder: None,
        runtime_digest: prepared.worker().runtime_digest(),
        device_digest,
        input_schema: V13GenerationProcessWorkerV1::input_schema_digest(),
        state_schema: V13GenerationProcessWorkerV1::state_schema_digest(),
        output_schema: V13GenerationProcessWorkerV1::output_schema_digest(),
        learning: closure.learning.clone(),
        evolution: CellEvolutionBindingV2 {
            structure: [11; 32],
            lineage: [12; 32],
            source_dependencies: [13; 32],
            adoption_receipt: Digest32::of_bytes(b"invalid fixture, no live adoption").into_array(),
        },
        max_input_bytes: 8192,
        max_state_bytes: 1,
        max_delta_bytes: 8192,
        max_prefix_bytes: 65536,
        max_step_cost_entries: 8,
        max_ack_cost_entries: 1,
    };
    let config = CellGenerationConfigV2 {
        initial: CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: [15; 32],
                agent_id: identity.agent_id.to_string(),
                cell_id: "v13-invalid-closure".into(),
                run_id: "ordinary-entry".into(),
            },
            manifest_digest: manifest.digest()?,
            generation: 41,
            writer_epoch: 7,
            revision: 0,
            state: Vec::new(),
            prefix: Vec::new(),
            stopped: false,
        },
        manifest,
        source_frontier: closure.source_version,
        task_digest: [17; 32],
    };
    Ok(json!({
        "schema": "hepta.agentd.neuron-v13-generation-bootstrap.v1",
        "identity_digest": neuron_generation_process_identity_digest_v1(identity)?.to_string(),
        "boot_id": fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim(),
        "mode": "create", "journal_path": root.join("cell.journal"),
        "witness_path": root.join("independent.witness"), "control_path": root.join("control.journal"),
        "max_records": 128, "control_capacity": 32, "queue_capacity": 4,
        "rpc_timeout_millis": 1000, "config": config, "interpreter_argv0": interpreter,
        "interpreter": {"path": interpreter, "digest": interpreter_digest.to_string()},
        "worker": {"path": worker_path, "digest": worker_digest.to_string()},
        "assets": catalog, "closure": closure, "phase_cpu_seconds": 3,
        "address_space_bytes": 512 * 1024 * 1024, "wall_limit_millis": 10000,
    }))
}
