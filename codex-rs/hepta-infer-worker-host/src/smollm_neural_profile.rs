//! Immutable executable, vocabulary and parameter profile for the CPU read port.
use super::session::read_bounded;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::PathBuf;

pub(super) const SCHEMA: &str = "hepta-smollm-neural-read-worker-v1";
pub(super) const PROFILE: &str = "hepta-smollm-single-token-action-score-v1";

/// Host-owned fixed model material and executable pins. Action completions are
/// the full registered action vocabulary, never per-query expected answers.
pub struct SmolLmNeuralReadConfigV1 {
    pub python: PathBuf,
    pub script: PathBuf,
    pub materials: PathBuf,
    pub run_directory: PathBuf,
    pub source_pins: BTreeMap<PathBuf, Digest32>,
    pub target_contract: Vec<u8>,
    pub wrapped_adapter: Vec<u8>,
    pub contract_digest: Digest32,
    pub adapter_digest: Digest32,
    pub backbone_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub action_completions: BTreeMap<StableId, String>,
}

impl SmolLmNeuralReadConfigV1 {
    /// Commitment installed into NeuralCognitivePinV1 and the original artifact
    /// compatibility field before qualification. Filesystem locations do not
    /// alter model semantics; exact executable contents and action labels do.
    pub fn execution_profile_digest(&self) -> Result<Digest32, String> {
        let sources = self.source_identities()?;
        let actions = self.actions();
        let bytes = serde_json::to_vec(&(
            PROFILE,
            sources,
            actions,
            self.contract_digest.to_string(),
            self.adapter_digest.to_string(),
            Digest32::of_bytes(&self.target_contract).to_string(),
            Digest32::of_bytes(&self.wrapped_adapter).to_string(),
            self.backbone_digest.to_string(),
            self.tokenizer_digest.to_string(),
            4_u32,
        ))
        .map_err(|error| error.to_string())?;
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(super) fn source_identities(&self) -> Result<BTreeMap<String, String>, String> {
        let mut identities = BTreeMap::new();
        for (path, expected) in &self.source_pins {
            if !path.is_absolute() || expected.is_zero() {
                return Err("neural executable pin must be absolute and nonzero".to_owned());
            }
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .ok_or("neural source filename")?;
            if identities
                .insert(name.to_owned(), expected.to_string())
                .is_some()
            {
                return Err("duplicate neural source filename".to_owned());
            }
        }
        let required = [
            "llm_adapter_contract.py",
            "llm_inherited_runtime.py",
            "llm_neural_read_worker.py",
            "llm_parent_material.py",
            "llm_runtime_pilot.py",
            "model-family-smollm2-135m-v1.json",
        ];
        if identities.keys().map(String::as_str).collect::<Vec<_>>() != required {
            return Err(
                "neural worker requires the complete executable and family pin set".to_owned(),
            );
        }
        Ok(identities)
    }

    pub(super) fn verify_sources(&self) -> Result<(), String> {
        self.source_identities()?;
        for (path, expected) in &self.source_pins {
            if Digest32::of_bytes(&read_bounded(path, 2 * 1024 * 1024)?) != *expected {
                return Err("neural executable changed; independent reload required".to_owned());
            }
        }
        Ok(())
    }

    pub(super) fn actions(&self) -> Vec<Action> {
        self.action_completions
            .iter()
            .map(|(id, completion)| Action {
                action_id: id.to_string(),
                completion: completion.clone(),
            })
            .collect()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Action {
    pub(super) action_id: String,
    pub(super) completion: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NoAuthority {
    installation_authorized: bool,
    selection_authorized: bool,
    independent_accepted: bool,
    prospective_accepted: bool,
    public_reward_eligible: bool,
    hepta_final_use: bool,
}
impl NoAuthority {
    pub(super) fn denied(&self) -> bool {
        !(self.installation_authorized
            || self.selection_authorized
            || self.independent_accepted
            || self.prospective_accepted
            || self.public_reward_eligible
            || self.hepta_final_use)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Ready {
    pub(super) schema: String,
    pub(super) actual_loaded_parent: String,
    pub(super) file_sha256: String,
    pub(super) contract: String,
    pub(super) generation: u64,
    pub(super) backbone: String,
    pub(super) tokenizer: String,
    pub(super) source_pins: BTreeMap<String, String>,
    pub(super) worker_source: String,
    pub(super) actions: Vec<Action>,
    pub(super) observed_rss_bytes: u64,
    pub(super) authority: NoAuthority,
}
