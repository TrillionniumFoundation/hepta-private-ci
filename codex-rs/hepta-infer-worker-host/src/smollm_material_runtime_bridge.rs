//! Exact historical-material/current-runtime pairing, separate from permission.
use super::Action;
use super::NoAuthority;
use super::Ready;
use super::SmolLmNeuralReadConfigV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;

pub(super) const PROFILE: &str = "smollm2-public-v2-material-runtime-bridge-v1";
pub(super) const READY_SCHEMA: &str = "hepta-smollm-neural-read-ready-material-bridge-v1";
const MATERIAL_PLAN: &str = "01ec1a644f37b9fc7a4c6616f589768df97f8eed7a289b5de86afadaa7ce6165";
const MATERIAL_TARGET: &str = "ebc8ac84999a91acb823d1bf8959a7dbc61fe20d7ba137f11affe426605d9852";
const MATERIAL_CONTRACT: &str = "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f";
const MATERIAL_RUNTIME: &str = "65ccc6454befd96fa5ce1f5bdde2c56cb6cbb741cf495b8d24a758039f99f755";
const EXECUTION_RUNTIME: &str = "d2854289ae810115bccd3b7714c3d40b03cc6ec216747d6fca653aeac9299bd7";
const EXECUTION_PLAN: &str = "e9506293ba9e70ef16889efcbeb23007c177806677b4fdf68104726c885054e4";
const EXECUTION_TARGET: &str = "ab62a0df784f43274d01cb5ebff11c8ef798ec21ff389ce6b46662377e6f555d";

/// Explicit fixed-pair selection. This carries no load, grant or FinalUse authority.
#[derive(Clone, Debug, Serialize)]
pub struct SmolLmMaterialRuntimeBridgeV1 {
    profile: String,
    material_plan: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BridgeInput {
    profile: String,
    material_plan: String,
}

impl<'de> Deserialize<'de> for SmolLmMaterialRuntimeBridgeV1 {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let input = BridgeInput::deserialize(deserializer)?;
        Self::new(&input.profile, input.material_plan.into_bytes())
            .map_err(serde::de::Error::custom)
    }
}

impl SmolLmMaterialRuntimeBridgeV1 {
    pub fn new(profile: &str, material_plan: Vec<u8>) -> Result<Self, String> {
        if profile != PROFILE
            || material_plan.is_empty()
            || material_plan.len() > 64 * 1024
            || Digest32::of_bytes(&material_plan).to_string() != MATERIAL_PLAN
        {
            return Err(
                "unsupported material/runtime bridge profile or historical plan".to_owned(),
            );
        }
        Ok(Self {
            profile: profile.to_owned(),
            material_plan: String::from_utf8(material_plan).map_err(|e| e.to_string())?,
        })
    }

    pub(crate) fn deserialize_present<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<Self>, D::Error> {
        // Missing is the old mode; an explicit null is not a version selector.
        Self::deserialize(deserializer).map(Some)
    }

    pub(super) fn plan(&self) -> &[u8] {
        self.material_plan.as_bytes()
    }

    pub(super) fn verify_config(&self, config: &SmolLmNeuralReadConfigV1) -> Result<(), String> {
        if self.profile != PROFILE
            || Digest32::of_bytes(self.plan()).to_string() != MATERIAL_PLAN
            || Digest32::of_bytes(&config.target_contract).to_string() != MATERIAL_TARGET
            || config.contract_digest.to_string() != MATERIAL_CONTRACT
            || config
                .source_identities()?
                .get("llm_runtime_pilot.py")
                .map(String::as_str)
                != Some(EXECUTION_RUNTIME)
        {
            return Err("material/runtime bridge differs from the exact admitted pair".to_owned());
        }
        Ok(())
    }

    pub(super) fn execution_digest(
        &self,
        config: &SmolLmNeuralReadConfigV1,
        original: Digest32,
    ) -> Result<Digest32, String> {
        self.verify_config(config)?;
        let raw = serde_json::to_vec(&(
            "hepta-smollm-material-runtime-bound-execution-v1",
            original.to_string(),
            self,
            READY_SCHEMA,
            BridgeObservation::expected(),
        ))
        .map_err(|e| e.to_string())?;
        Ok(Digest32::of_bytes(&raw))
    }

    pub(super) fn decode_ready(
        &self,
        config: &SmolLmNeuralReadConfigV1,
        raw: &[u8],
    ) -> Result<Ready, String> {
        self.verify_config(config)?;
        let ready: BridgedReady = serde_json::from_slice(raw).map_err(|e| e.to_string())?;
        let source_set =
            serde_json::to_vec(&config.source_identities()?).map_err(|e| e.to_string())?;
        if ready.schema != READY_SCHEMA
            || ready.material_runtime_bridge != BridgeObservation::expected()
            || ready.runtime_source_set_sha256 != Digest32::of_bytes(&source_set).to_string()
        {
            return Err(
                "material/runtime bridge Ready differs from the exact current and historical pair"
                    .to_owned(),
            );
        }
        Ok(Ready {
            schema: ready.schema,
            actual_loaded_parent: ready.actual_loaded_parent,
            file_sha256: ready.file_sha256,
            contract: ready.contract,
            generation: ready.generation,
            backbone: ready.backbone,
            tokenizer: ready.tokenizer,
            source_pins: ready.source_pins,
            worker_source: ready.worker_source,
            runtime_snapshot_sha256: ready.runtime_snapshot_sha256,
            actions: ready.actions,
            observed_rss_bytes: ready.observed_rss_bytes,
            authority: ready.authority,
        })
    }
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct BridgeObservation {
    schema: String,
    profile: String,
    historical_plan_sha256: String,
    historical_contract_sha256: String,
    historical_contract: String,
    historical_runtime_source: String,
    execution_runtime_source: String,
    execution_plan_sha256: String,
    execution_contract_sha256: String,
}

impl BridgeObservation {
    fn expected() -> Self {
        Self {
            schema: "hepta-smollm-material-runtime-bridge-v1".to_owned(),
            profile: PROFILE.to_owned(),
            historical_plan_sha256: MATERIAL_PLAN.to_owned(),
            historical_contract_sha256: MATERIAL_TARGET.to_owned(),
            historical_contract: MATERIAL_CONTRACT.to_owned(),
            historical_runtime_source: MATERIAL_RUNTIME.to_owned(),
            execution_runtime_source: EXECUTION_RUNTIME.to_owned(),
            execution_plan_sha256: EXECUTION_PLAN.to_owned(),
            execution_contract_sha256: EXECUTION_TARGET.to_owned(),
        }
    }
}

// Deliberately separate strict objects: even null bridge fields remain unknown
// to the unchanged old Ready parser. No schema guessing or untagged fallback.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BridgedReady {
    schema: String,
    actual_loaded_parent: String,
    file_sha256: String,
    contract: String,
    generation: u64,
    backbone: String,
    tokenizer: String,
    source_pins: BTreeMap<String, String>,
    worker_source: String,
    runtime_snapshot_sha256: String,
    actions: Vec<Action>,
    observed_rss_bytes: u64,
    authority: NoAuthority,
    material_runtime_bridge: BridgeObservation,
    runtime_source_set_sha256: String,
}

#[cfg(test)]
#[path = "smollm_material_runtime_bridge_tests.rs"]
mod tests;
