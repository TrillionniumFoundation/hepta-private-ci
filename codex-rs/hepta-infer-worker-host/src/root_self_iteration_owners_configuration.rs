//! Immutable per-round routes to the already enrolled finite role programs.
//! Key paths stay inside original native-role templates; this owner reads no
//! seed or private evaluation cut and grants no role authority itself.
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;

use crate::initial_cpu_anchor::InstalledCpuSourceV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootSelfIterationRoleRouteV1 {
    pub program: InstalledCpuSourceV1,
    pub configuration_template: InstalledCpuSourceV1,
    pub uid: u32,
    pub gid: u32,
    pub inaccessible_paths: Vec<PathBuf>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootSelfIterationOwnersRoundConfigurationV1 {
    pub schema: String,
    pub round_digest: String,
    pub client_configuration: InstalledCpuSourceV1,
    pub materials: InstalledCpuSourceV1,
    pub paired_custody_execution: InstalledCpuSourceV1,
    /// Root-owned public immutable configuration area, separate from private effect slots.
    pub public_source_directory: PathBuf,
    pub consumer_directory: PathBuf,
    pub evaluation_directory: PathBuf,
    pub generator_uid: u32,
    pub generator_gid: u32,
    pub evaluator: RootSelfIterationRoleRouteV1,
    pub custody_finish: RootSelfIterationRoleRouteV1,
    pub selector: RootSelfIterationRoleRouteV1,
    pub observer: RootSelfIterationRoleRouteV1,
}

/// Same original recipe directory, with no caller-selected service path.
pub fn root_self_iteration_owners_configuration_path_v1(
    execution_directory: &Path,
    round: &AgentdSelfIterationRoundV1,
) -> PathBuf {
    execution_directory
        .join(format!("round-materials-{}", round.identity_digest()))
        .join("independent-owner-service.json")
}

impl RootSelfIterationOwnersRoundConfigurationV1 {
    pub(super) fn read(path: &Path, round: &AgentdSelfIterationRoundV1) -> Result<(Self, Vec<u8>)> {
        let bytes = codex_hepta_supervisor::RootFleetPeerAdmissionV1::read_protected_source(
            path,
            64 * 1024,
            false,
        )?;
        let configuration: Self = serde_json::from_slice(&bytes)?;
        ensure!(
            configuration.schema == "hepta.root-self-iteration-independent-owners-round.v1"
                && configuration.round_digest.parse::<Digest32>()? == round.identity_digest()
                && configuration.generator_uid > 0
                && configuration.generator_gid > 0,
            "original full round and enrolled Generator publisher identity"
        );
        for route in [
            &configuration.evaluator,
            &configuration.custody_finish,
            &configuration.selector,
            &configuration.observer,
        ] {
            ensure!(
                !route.program.digest.parse::<Digest32>()?.is_zero()
                    && !route
                        .configuration_template
                        .digest
                        .parse::<Digest32>()?
                        .is_zero(),
                "whole enrolled program/template pins"
            );
        }
        ensure!(
            configuration.evaluator.uid > 0
                && configuration.evaluator.gid > 0
                && configuration.evaluator.uid != configuration.generator_uid
                && [
                    &configuration.custody_finish,
                    &configuration.selector,
                    &configuration.observer
                ]
                .iter()
                .all(|route| route.uid == 0 && route.gid == 0)
                && configuration.selector.program.path != configuration.observer.program.path
                && configuration.selector.program.digest != configuration.observer.program.digest,
            "actual finite E/S/O process boundaries"
        );
        Ok((configuration, bytes))
    }
}
