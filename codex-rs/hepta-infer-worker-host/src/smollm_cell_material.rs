//! Controlled byte closure only. Selection, installation and use remain with
//! the original owners. Peer bytes never supply executable permissions.

use std::fs::File;
use std::io::Cursor;
use std::io::Read;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::model_worker::ResourceGrant;
use crate::native_app_server::TurnStartAuthorizer;
use crate::smollm_neural_read::SmolLmNeuralReadConfigV1;
use crate::smollm_neural_read::SmolLmNeuralReadPortV1;

#[path = "smollm_cell_wire.rs"]
mod wire;

const SCHEMA: &str = "hepta-smollm-controlled-cell-release-v1";
const PROFILE: &str = "smollm2-135m-f32-r4-dense-single-adapter-no-fallback-v1";
const MAX_SIDECAR: u64 = 65_536;
const FAMILY_SHA256: &str = "0837bbfb31f3f2b9a8731545c9f742aee1ebd32daed392a936a3ec9719537e52";
const BASE_NAMES: [&str; 8] = [
    "README.md",
    "config.json",
    "generation_config.json",
    "material-manifest.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Sidecar {
    schema: String,
    scope: String,
    profile: String,
    operation_id: String,
    generation: u64,
    family_id: String,
    family_file_sha256: String,
    model: String,
    revision: String,
    artifact_sha256: String,
    adapter_digest: String,
    contract_digest: String,
    backbone_digest: String,
    tokenizer_digest: String,
    execution_profile_sha256: String,
    sources: Vec<Source>,
    actions: Vec<super::profile::Action>,
    tcr1_hex: String,
    tcr1_id: String,
    members: Vec<Member>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    name: String,
    sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Member {
    name: String,
    manifest_id: String,
    payload_sha256: String,
    size: u64,
    tcm1_hex: String,
}

/// Consumed original admission inputs; this container issues no grant or key.
pub struct SmolLmCellStartOwnerV1 {
    pub owner_id: AgentId,
    pub body_generation: u64,
    pub worker_id: String,
    pub grant: ResourceGrant,
    pub control: Arc<Mutex<DurableInferenceControl>>,
    pub authorizer: Arc<dyn TurnStartAuthorizer>,
    pub runtime: tokio::runtime::Handle,
}

/// Sealed, owned byte/profile check, never a selected or installed model proof.
pub struct VerifiedCellMaterialV1 {
    config: SmolLmNeuralReadConfigV1,
    pin: NeuralCognitivePinV1,
    parameters: Vec<u8>,
    sidecar_digest: Digest32,
    closure_digest: Digest32,
}

impl VerifiedCellMaterialV1 {
    pub fn sidecar_digest(&self) -> Digest32 {
        self.sidecar_digest
    }
    pub fn closure_digest(&self) -> Digest32 {
        self.closure_digest
    }

    /// Consume the checked snapshot through the original signed/resource path.
    pub fn start(self, owner: SmolLmCellStartOwnerV1) -> Result<SmolLmNeuralReadPortV1, String> {
        SmolLmNeuralReadPortV1::start(
            self.config,
            self.pin,
            self.parameters,
            owner.owner_id,
            owner.body_generation,
            owner.worker_id,
            owner.grant,
            owner.control,
            owner.authorizer,
            owner.runtime,
        )
    }
}

/// Verify the narrow eleven-object profile before original model admission.
/// The caller owns a private staging directory; the actual worker rechecks
/// materials before Ready. This is not a held-namespace or install capability.
pub fn verify_controlled_cell_material_v1(
    file: File,
    expected_sha256: Digest32,
    config: SmolLmNeuralReadConfigV1,
    pin: NeuralCognitivePinV1,
    parameters: Vec<u8>,
    expected_operation_id: &str,
) -> Result<VerifiedCellMaterialV1, String> {
    let metadata = file.metadata().map_err(|e| e.to_string())?;
    need(
        metadata.is_file() && metadata.len() > 0 && metadata.len() <= MAX_SIDECAR,
        "sidecar size/type",
    )?;
    let mut raw = Vec::new();
    file.take(MAX_SIDECAR + 1)
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    need(
        raw.len() as u64 == metadata.len() && Digest32::of_bytes(&raw) == expected_sha256,
        "sidecar bytes",
    )?;
    let sidecar: Sidecar = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    let sources =
        validate_declaration(&sidecar, &config, &pin, &parameters, expected_operation_id)?;
    let family_path = config
        .source_pins
        .keys()
        .find(|p| {
            p.file_name().and_then(|n| n.to_str()) == Some("model-family-smollm2-135m-v1.json")
        })
        .ok_or("family source")?;
    let family_raw = super::session::read_bounded(family_path, 2 * 1024 * 1024)?;
    need(
        Digest32::of_bytes(&family_raw) == pin.family_digest
            && pin.family_digest.to_string() == FAMILY_SHA256,
        "family changed/profile version",
    )?;
    let family: serde_json::Value =
        serde_json::from_slice(&family_raw).map_err(|e| e.to_string())?;
    need(
        family["id"].as_str() == Some(&sidecar.family_id)
            && family["reference"]["model"].as_str() == Some(&sidecar.model)
            && family["reference"]["revision"].as_str() == Some(&sidecar.revision)
            && sidecar.family_id == "smollm2-135m-cpu-dev-v1",
        "model family",
    )?;
    let context = wire::context(
        &sidecar.family_id,
        [
            config.backbone_digest,
            pin.payload_digest,
            config.tokenizer_digest,
            config.contract_digest,
            sources["llm_neural_read_worker.py"]
                .parse()
                .map_err(|e| format!("worker digest: {e}"))?,
        ],
    )?;
    let mut ids = Vec::new();
    for member in &sidecar.members {
        let (size, sha, chunks) = match member.name.as_str() {
            "adapter/artifact.safetensors" => {
                wire::measure(Cursor::new(&parameters), 2 * 1024 * 1024)?
            }
            "adapter/target-contract.json" => {
                wire::measure(Cursor::new(&config.target_contract), 2 * 1024 * 1024)?
            }
            "adapter/wrapped-adapter.json" => {
                wire::measure(Cursor::new(&config.wrapped_adapter), 2 * 1024 * 1024)?
            }
            _ => {
                let name = member.name.strip_prefix("base/").ok_or("base path")?;
                let file = wire::open_regular(&config.materials.join(name), 300 * 1024 * 1024)?;
                let measured = wire::measure(file, 300 * 1024 * 1024)?;
                if name != "material-manifest.json" {
                    let expected = &family["material_pins"]["files"][name];
                    need(
                        expected["size"].as_u64() == Some(measured.0)
                            && expected["sha256"].as_str() == Some(&measured.1.to_string()),
                        "public material pin",
                    )?;
                }
                measured
            }
        };
        need(
            member.size == size && member.payload_sha256 == sha.to_string(),
            "member payload binding",
        )?;
        let expected = wire::manifest(&context, size, sha, &chunks);
        let id = wire::verify(
            wire::ManifestKind::Cell,
            &member.tcm1_hex,
            &expected,
            &member.manifest_id,
        )?;
        ids.push(id);
    }
    let manifest_raw =
        super::session::read_bounded(&config.materials.join("material-manifest.json"), 65_536)?;
    let material_manifest: serde_json::Value =
        serde_json::from_slice(&manifest_raw).map_err(|e| e.to_string())?;
    need(
        material_manifest["files"] == family["material_pins"]["files"]
            && material_manifest["model"].as_str() == Some(&sidecar.model)
            && material_manifest["revision"].as_str() == Some(&sidecar.revision),
        "material manifest semantics",
    )?;
    ids.sort_unstable();
    need(
        ids.windows(2).all(|p| p[0] < p[1]),
        "duplicate release member",
    )?;
    let release = wire::release(&context, &ids);
    wire::verify(
        wire::ManifestKind::Release,
        &sidecar.tcr1_hex,
        &release,
        &sidecar.tcr1_id,
    )?;
    let closure_digest = Digest32::of_parts(&[
        b"hepta.smollm.controlled-cell-release.v1\0",
        &(raw.len() as u64).to_be_bytes(),
        &raw,
    ]);
    Ok(VerifiedCellMaterialV1 {
        config,
        pin,
        parameters,
        sidecar_digest: expected_sha256,
        closure_digest,
    })
}

fn validate_declaration(
    sidecar: &Sidecar,
    config: &SmolLmNeuralReadConfigV1,
    pin: &NeuralCognitivePinV1,
    parameters: &[u8],
    expected_operation_id: &str,
) -> Result<std::collections::BTreeMap<String, String>, String> {
    config.verify_sources()?;
    let sources = config.source_identities()?;
    need(
        sidecar.schema == SCHEMA
            && sidecar.scope == "controlled-native-load-only"
            && sidecar.profile == PROFILE
            && sidecar.generation == pin.generation.get()
            && sidecar.family_id == "smollm2-135m-cpu-dev-v1"
            && sidecar.model == "HuggingFaceTB/SmolLM2-135M-Instruct"
            && sidecar.revision == "12fd25f77366fa6b3b4b768ec3050bf629380bac"
            && sidecar.operation_id == expected_operation_id
            && !sidecar.operation_id.is_empty()
            && sidecar.operation_id.len() <= 128
            && sidecar.operation_id.bytes().all(|b| b.is_ascii_graphic()),
        "closure identity/profile",
    )?;
    for (declared, expected) in [
        (&sidecar.artifact_sha256, pin.payload_digest),
        (&sidecar.family_file_sha256, pin.family_digest),
        (&sidecar.adapter_digest, config.adapter_digest),
        (&sidecar.contract_digest, config.contract_digest),
        (&sidecar.backbone_digest, config.backbone_digest),
        (&sidecar.tokenizer_digest, config.tokenizer_digest),
        (
            &sidecar.execution_profile_sha256,
            config.execution_profile_digest()?,
        ),
    ] {
        need(declared == &expected.to_string(), "closure semantic digest")?;
    }
    need(
        pin.execution_profile_digest == config.execution_profile_digest()?
            && Digest32::of_bytes(&parameters) == pin.payload_digest,
        "owned model inputs",
    )?;
    need(
        sidecar.actions.len() == 2
            && sidecar.sources.len() == sources.len()
            && sidecar
                .sources
                .iter()
                .zip(&sources)
                .all(|(a, (name, sha))| &a.name == name && &a.sha256 == sha)
            && sidecar.actions == config.actions(),
        "local execution profile",
    )?;
    let mut names = vec![
        "adapter/artifact.safetensors".to_owned(),
        "adapter/target-contract.json".to_owned(),
        "adapter/wrapped-adapter.json".to_owned(),
    ];
    names.extend(BASE_NAMES.iter().map(|n| format!("base/{n}")));
    need(
        sidecar.members.len() == names.len()
            && sidecar
                .members
                .iter()
                .zip(&names)
                .all(|(m, n)| &m.name == n),
        "exact mandatory role/path roster",
    )?;
    Ok(sources)
}

fn need(value: bool, message: &str) -> Result<(), String> {
    if value {
        Ok(())
    } else {
        Err(format!("controlled Cell material: {message}"))
    }
}

#[cfg(test)]
#[path = "smollm_cell_material_tests.rs"]
mod tests;
