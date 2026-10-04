//! Root's immutable composition refers to original public materials and owners.
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::RootFleetPeerAdmissionV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::initial_cpu_anchor::InstalledCpuSourceV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AgentScope {
    pub agent_id: AgentId,
    pub current_release: ReleaseId,
    pub canonical: InstalledCpuSourceV1,
    pub materials: InstalledCpuSourceV1,
    pub objective_prompt: InstalledCpuSourceV1,
    pub worker_executable_digest: String,
    pub agent_executable_digest: String,
    pub app_server_executable_digest: String,
    pub model: String,
    pub model_provider: String,
    pub native_timeout_ms: u64,
    #[serde(default)]
    pub round_blueprint: Option<InstalledCpuSourceV1>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Configuration {
    pub schema: String,
    pub model_authority_policy: PathBuf,
    pub fleet_root: PathBuf,
    pub socket: PathBuf,
    pub socket_group: u32,
    pub terminal_receipt_directory: PathBuf,
    pub execution_directory: PathBuf,
    pub generator_uid: u32,
    pub generator_program: InstalledCpuSourceV1,
    pub generator_public_trust: InstalledCpuSourceV1,
    pub generator_private_key_path: PathBuf,
    pub generator_inaccessible_paths: Vec<PathBuf>,
    pub agents: Vec<AgentScope>,
    #[serde(default)]
    pub maximum_parallel_issuance: Option<usize>,
}

fn absolute(path: &Path) -> Result<()> {
    ensure!(
        path.is_absolute()
            && !path.components().any(|component| matches!(
                component,
                std::path::Component::CurDir | std::path::Component::ParentDir
            )),
        "Generator composition requires absolute normalized paths"
    );
    Ok(())
}

pub(super) fn source(source: &InstalledCpuSourceV1, maximum: usize) -> Result<Vec<u8>> {
    absolute(&source.path)?;
    let pin = source.digest.parse::<Digest32>()?;
    let bytes = RootFleetPeerAdmissionV1::read_protected_source(
        &source.path,
        maximum,
        /*private*/ false,
    )?;
    ensure!(
        !pin.is_zero() && Digest32::of_bytes(&bytes) == pin,
        "original source changed"
    );
    Ok(bytes)
}

pub(super) fn canonical_policy(
    input: &InstalledCpuSourceV1,
) -> Result<codex_hepta_agentd::CanonicalIterationEnvelopeV1> {
    // The installed source pin authenticates file bytes. The original decoder
    // derives the policy identity from its canonical representation separately.
    codex_hepta_agentd::CanonicalIterationEnvelopeV1::decode(&source(input, 262_144)?)
        .map_err(anyhow::Error::msg)
}

impl Configuration {
    pub(super) fn read(path: &Path) -> Result<(Self, Vec<u8>)> {
        absolute(path)?;
        let bytes = RootFleetPeerAdmissionV1::read_protected_source(
            path,
            64 * 1024,
            /*private*/ true,
        )?;
        let configuration: Self = serde_json::from_slice(&bytes)?;
        ensure!(
            (1..=4).contains(&configuration.maximum_parallel_issuance.unwrap_or(1)),
            "bounded original Generator material concurrency"
        );
        ensure!(
            configuration.schema == "hepta.root-frozen-generator-composition.v1"
                && configuration.generator_uid != 0
                && configuration.socket_group != 0
                && (1..=16).contains(&configuration.agents.len())
                && (2..=32).contains(&configuration.generator_inaccessible_paths.len()),
            "Generator composition schema or bounded independent custody differs"
        );
        HeptaFleetRoot::parse(&configuration.fleet_root)?;
        for path in [
            &configuration.model_authority_policy,
            &configuration.socket,
            &configuration.terminal_receipt_directory,
            &configuration.execution_directory,
            &configuration.generator_program.path,
            &configuration.generator_public_trust.path,
            &configuration.generator_private_key_path,
        ]
        .into_iter()
        .chain(&configuration.generator_inaccessible_paths)
        {
            absolute(path)?;
        }
        ensure!(
            !configuration
                .generator_inaccessible_paths
                .contains(&configuration.generator_private_key_path),
            "Generator key cannot also be a denied role source"
        );
        for pin in [
            &configuration.generator_program.digest,
            &configuration.generator_public_trust.digest,
        ] {
            ensure!(
                !pin.parse::<Digest32>()?.is_zero(),
                "original Generator public pin absent"
            );
        }
        let mut unique = BTreeSet::new();
        for scope in &configuration.agents {
            ensure!(
                unique.insert(scope.agent_id.clone()),
                "duplicate Generator Agent scope"
            );
            for input in [&scope.canonical, &scope.materials, &scope.objective_prompt] {
                absolute(&input.path)?;
                ensure!(
                    !input.digest.parse::<Digest32>()?.is_zero(),
                    "original material pin absent"
                );
            }
            if let Some(input) = &scope.round_blueprint {
                absolute(&input.path)?;
                ensure!(
                    !input.digest.parse::<Digest32>()?.is_zero(),
                    "original round blueprint pin absent"
                );
            }
            ensure!(
                !scope
                    .worker_executable_digest
                    .parse::<Digest32>()?
                    .is_zero()
                    && !scope.agent_executable_digest.parse::<Digest32>()?.is_zero()
                    && !scope
                        .app_server_executable_digest
                        .parse::<Digest32>()?
                        .is_zero()
                    && (1..=60_000).contains(&scope.native_timeout_ms)
                    && !scope.model.is_empty()
                    && scope.model.len() <= 256
                    && !scope.model_provider.is_empty()
                    && scope.model_provider.len() <= 256,
                "original native model scope or budget invalid"
            );
        }
        Ok((configuration, bytes))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    #[ignore = "requires an actual Root process and isolated protected /run directory"]
    fn actual_root_keeps_source_pin_separate_from_canonical_policy_identity() -> Result<()> {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let directory = tempfile::Builder::new()
            .prefix("hepta-original-canonical-policy-")
            .tempdir_in("/run")?;
        let value = serde_json::json!({
            "envelopeId": "whole-policy-source",
            "baseCommit": "1".repeat(40), "baseTree": "2".repeat(40),
            "objectiveDigest": "3".repeat(64), "grammarDigest": "4".repeat(64),
            "allowedPaths": ["parameters/neuron.sparse.rates.q24.v1"],
            "deniedAuthorities": ["release"], "mandatoryChecks": ["verify"],
            "maximumFiles": 1, "maximumBytes": 4096, "maximumCandidates": 4,
            "wallTimeMicros": 300_000_000,
            "computeBudget": {"profile": "hepta.iteration-compute-budget.v1",
                "maximumParallelSandboxes": 1, "maximumMemoryBytes": 134_217_728,
                "maximumProcesses": 1},
            "expiresUnixMs": 4_000_000_000_000_u64
        });
        let bytes = serde_json::to_vec_pretty(&value)?;
        let path = directory.path().join("policy.json");
        std::fs::write(&path, &bytes)?;
        let source_pin = Digest32::of_bytes(&bytes);
        let source = InstalledCpuSourceV1 {
            path: path.clone(),
            digest: source_pin.to_string(),
        };
        let canonical = canonical_policy(&source)?;
        assert_ne!(canonical.digest(), source_pin);
        assert_eq!(
            canonical.canonical_bytes(),
            codex_hepta_agentd::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&value)?)
                .map_err(anyhow::Error::msg)?
                .canonical_bytes()
        );
        // A semantically identical replacement still violates the independently
        // enrolled file pin and must be rejected before semantic decoding.
        std::fs::write(&path, canonical.canonical_bytes())?;
        assert!(canonical_policy(&source).is_err());
        Ok(())
    }
}
