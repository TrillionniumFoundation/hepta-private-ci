//! Fixed artificial tensors used by both the loader and actual CLI tests.
//! All source/adoption labels below explicitly identify synthetic test input.

use std::fs;
use std::path::Path;
use std::sync::Arc;

use super::AgentdIdentity;
use super::neuron_generation_process_identity_digest_v1;
use anyhow::Result;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

#[path = "../../../hepta-neuron/tests/support/joint_synthetic.rs"]
pub(crate) mod synthetic;

pub(crate) struct FixtureAssets(synthetic::Assets);

pub(crate) fn descriptor(root: &Path, identity: &AgentdIdentity) -> Result<(Value, FixtureAssets)> {
    let assets = synthetic::assets()?;
    let executable = codex_utils_cargo_bin::cargo_bin("hepta-joint-propose")?.canonicalize()?;
    let executable_digest = Digest32::of_bytes(&fs::read(&executable)?);
    let weights_digest = Digest32::of_bytes(&assets.weights);
    let public_digest = Digest32::of_bytes(&assets.public);
    let weights = root.join("synthetic-weights.hps");
    let public = root.join("synthetic-public.hps");
    fs::write(&weights, &assets.weights)?;
    fs::write(&public, &assets.public)?;
    let source_digest = Digest32::of_bytes(b"synthetic-normal-entry-source").into_array();
    let device_digest = JointGenerationProcessWorkerV1::observed_device_digest()?;
    let worker = JointGenerationProcessWorkerV1::open(
        JointGenerationProcessConfigV1 {
            executable: executable.clone(),
            executable_digest: executable_digest.into_array(),
            source_digest,
            weights: weights.clone(),
            weights_digest: weights_digest.into_array(),
            public: public.clone(),
            public_digest: public_digest.into_array(),
            device_digest,
        },
        Arc::new(|| 1),
    )?;
    let manifest = CellBackendManifestV2 {
        profile: JointGenerationProcessWorkerV1::PROFILE.into(),
        source_digest,
        bundle_digest: Digest32::of_bytes(b"synthetic-normal-entry-bundle").into_array(),
        encoder: Some(worker.encoder_digest()),
        head: Some(worker.head_digest()),
        memory: Some(worker.memory_digest()),
        world_model: None,
        decoder: Some(worker.decoder_digest()),
        runtime_digest: executable_digest.into_array(),
        device_digest,
        input_schema: JointGenerationProcessWorkerV1::input_schema_digest(),
        state_schema: JointGenerationProcessWorkerV1::state_schema_digest(),
        output_schema: JointGenerationProcessWorkerV1::output_schema_digest(),
        learning: CellLearningBindingV2::Frozen {
            weights: weights_digest.into_array(),
        },
        evolution: CellEvolutionBindingV2 {
            structure: Digest32::of_bytes(b"synthetic structure").into_array(),
            lineage: Digest32::of_bytes(b"synthetic lineage").into_array(),
            source_dependencies: Digest32::of_bytes(b"synthetic dependencies").into_array(),
            adoption_receipt: Digest32::of_bytes(b"synthetic reference, not adoption evidence")
                .into_array(),
        },
        max_input_bytes: 8192,
        max_state_bytes: 65_536,
        max_delta_bytes: 65_536,
        max_prefix_bytes: 65_536,
        max_step_cost_entries: 8,
        max_ack_cost_entries: 1,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: Digest32::of_bytes(b"synthetic principal").into_array(),
            agent_id: identity.agent_id.to_string(),
            cell_id: "synthetic-joint".into(),
            run_id: "synthetic-normal-entry".into(),
        },
        manifest_digest: manifest.digest()?,
        generation: 3,
        writer_epoch: 7,
        revision: 0,
        state: Vec::new(),
        prefix: Vec::new(),
        stopped: false,
    };
    let config = CellGenerationConfigV2 {
        manifest,
        initial,
        task_digest: Digest32::of_bytes(b"synthetic task").into_array(),
        source_frontier: Digest32::of_bytes(b"synthetic source frontier").into_array(),
    };
    Ok((
        json!({
            "schema": "hepta.agentd.neuron-generation-bootstrap.v1",
            "identity_digest": neuron_generation_process_identity_digest_v1(identity)?.to_string(),
            "boot_id": fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim(),
            "mode": "create", "journal_path": root.join("cell.journal"),
            "witness_path": root.join("independent.witness"), "control_path": root.join("control.journal"),
            "max_records": 128, "worker_generation": 7, "control_capacity": 32,
            "queue_capacity": 4, "rpc_timeout_millis": 1000, "config": config,
            "executable": {"path": executable, "digest": executable_digest.to_string()},
            "weights": {"path": weights, "digest": weights_digest.to_string()},
            "public": {"path": public, "digest": public_digest.to_string()},
        }),
        FixtureAssets(assets),
    ))
}

pub(crate) fn write_descriptor(path: &Path, value: &Value) -> Result<Digest32> {
    let bytes = serde_json::to_vec_pretty(value)?;
    let digest = Digest32::of_bytes(&bytes);
    fs::write(path, bytes)?;
    Ok(digest)
}

pub(crate) fn verify_stopped(state: &[u8], prefix: &[u8], assets: &FixtureAssets) -> Result<()> {
    let facts = synthetic::state(state, prefix, &assets.0)?;
    assert!(facts.stopped);
    assert_eq!(facts.cursors, synthetic::TOTAL_UNITS);
    let decoded = synthetic::prefix(prefix)?;
    assert_eq!(
        decoded.bytes,
        [
            vec![128; 768],
            vec![0; 2048],
            vec![128; 3072],
            b"action=0;sound=0\n".to_vec()
        ]
    );
    Ok(())
}
