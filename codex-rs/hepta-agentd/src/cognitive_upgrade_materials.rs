use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_types::Digest32;

use crate::AgentdIdentity;
use crate::CognitiveModelReadback;
use crate::cognitive_bootstrap::load_evaluated_cognitive_bootstrap_v1;
use crate::cognitive_upgrade_plan::CognitiveUpgradeCommitmentV1;
use crate::cognitive_upgrade_plan::CognitiveUpgradeSourceV1;

/// Replay the original descriptor, canonical product evaluator, independent
/// selector and artifact CURRENT reader before proposing a process transition.
pub fn inspect_published_cognitive_upgrade_v1(
    fleet: &FleetRegistry,
    source: CognitiveUpgradeSourceV1,
) -> Result<CognitiveUpgradeCommitmentV1> {
    let installed = inspect_model(fleet, &source)?;
    let commitment = CognitiveUpgradeCommitmentV1 {
        schema_version: 1,
        candidate_observed_at_unix_micros: u64::try_from(
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_micros(),
        )?,
        source,
        installed,
    };
    commitment.output_sha256()?;
    Ok(commitment)
}

pub(super) fn inspect_model(
    fleet: &FleetRegistry,
    source: &CognitiveUpgradeSourceV1,
) -> Result<CognitiveModelReadback> {
    let release = fleet.resolve_release(&source.agent_id, &source.target_release)?;
    let descriptor_path = source.descriptor_path.to_str().context("descriptor path is not UTF-8")?;
    for (flag, expected) in [
        ("--cognitive-bootstrap-descriptor", descriptor_path),
        ("--cognitive-bootstrap-descriptor-digest", source.descriptor_sha256.as_str()),
    ] {
        let positions: Vec<_> = release.args.iter().enumerate()
            .filter_map(|(index, value)| (value == flag).then_some(index)).collect();
        ensure!(
            positions.len() == 1
                && release.args.get(positions[0] + 1).map(String::as_str) == Some(expected),
            "the registered target release must pin the exact cognitive descriptor"
        );
    }
    let snapshot = fleet.load()?;
    let record = snapshot.agent(&source.agent_id).context("agent is not registered")?;
    let identity = AgentdIdentity {
        agent_id: source.agent_id.clone(),
        layout: record.layout.clone(),
        spawn_generation: source.spawn_generation,
        fleet_root: fleet.layout().fleet_root().as_path().to_path_buf(),
        workspace: record.manifest.workspace.as_path().to_path_buf(),
        resources: record.manifest.resources.clone(),
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let digest: Digest32 = source.descriptor_sha256.as_str().parse()?;
    let input = crate::load_cognitive_process_bootstrap_v1(
        &source.descriptor_path,
        digest,
        &identity,
    )?;
    let ranker = load_evaluated_cognitive_bootstrap_v1(
        source.agent_id.clone(),
        source.spawn_generation,
        input,
    ).map_err(anyhow::Error::msg)?;
    ranker.readback().map_err(anyhow::Error::msg)
}

