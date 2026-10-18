//! Explicit operator entry for an ordinary, already-published cognitive upgrade.
//! The exact input digest is independently pinned on the command line. Original
//! signed CURRENT, selector, FinalUse and Supervisord gates remain mandatory.

use std::io::Read;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_agentd::CognitiveUpgradeSourceV1;
use codex_hepta_agentd::CognitiveArtifactPublicationInputV1;
use codex_hepta_agentd::CognitiveArtifactRevocationInputV1;
use codex_hepta_agentd::PublishedCognitiveUpgradePlanV1;
use codex_hepta_agentd::advance_published_cognitive_upgrade_v1;
use codex_hepta_agentd::inspect_published_cognitive_upgrade_v1;
use codex_hepta_agentd::publish_cognitive_artifact_v1;
use codex_hepta_agentd::revoke_cognitive_artifact_v1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;

const MAX_INPUT_BYTES: u64 = 4 * 1024 * 1024;

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() -> Result<()> {
    let started = Instant::now();
    let started_at = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
    let mut args = std::env::args_os().skip(1);
    let usage = "usage: hepta-cognitive-upgrade inspect|publish|revoke|advance FLEET_ROOT INPUT_SHA256 < input.json";
    let command = args.next().context(usage)?.into_string().map_err(|_| anyhow::anyhow!(usage))?;
    let fleet_path = PathBuf::from(args.next().context(usage)?);
    let expected = args.next().context(usage)?.into_string().map_err(|_| anyhow::anyhow!(usage))?;
    ensure!(args.next().is_none(), "{usage}");
    ensure!(matches!(command.as_str(), "inspect" | "publish" | "revoke" | "advance"), "{usage}");
    let expected = Sha256Digest::parse(expected).map_err(anyhow::Error::msg)?;
    let mut bytes = Vec::new();
    std::io::stdin().lock().take(MAX_INPUT_BYTES + 1).read_to_end(&mut bytes)?;
    ensure!(!bytes.is_empty() && bytes.len() as u64 <= MAX_INPUT_BYTES, "upgrade input is empty or too large");
    ensure!(Sha256Digest::for_bytes(&bytes) == expected, "upgrade input digest mismatch");
    let fleet = FleetRegistry::open_existing(HeptaFleetRoot::parse(fleet_path)?)?;
    let mut candidate_observed_at = None;
    let mut identity = json!(null);
    let result: Result<serde_json::Value> = async {
    let output = match command.as_str() {
        "inspect" => {
            let source: CognitiveUpgradeSourceV1 = serde_json::from_slice(&bytes)?;
            let commitment = inspect_published_cognitive_upgrade_v1(&fleet, source)?;
            identity = json!({"agent_id":commitment.source.agent_id, "source_release":commitment.source.source_release,
                "target_release":commitment.source.target_release, "spawn_generation":commitment.source.spawn_generation,
                "artifact":commitment.installed.model});
            candidate_observed_at = Some(commitment.candidate_observed_at_unix_micros);
            json!({"output_sha256":commitment.output_sha256()?, "commitment":commitment})
        }
        "advance" => {
            let plan: PublishedCognitiveUpgradePlanV1 = serde_json::from_slice(&bytes)?;
            candidate_observed_at = Some(plan.commitment.candidate_observed_at_unix_micros);
            identity = json!({"agent_id":plan.commitment.source.agent_id, "source_release":plan.commitment.source.source_release,
                "target_release":plan.commitment.source.target_release, "spawn_generation":plan.commitment.source.spawn_generation,
                "artifact":plan.commitment.installed.model, "task_id":plan.task.task_id,
                "run_id":plan.effect.intent.run_id, "step_id":plan.effect.intent.step_id,
                "attempt":plan.effect.intent.attempt, "command_id":plan.effect.command_id,
                "grant_sha256":plan.production_grant.grant_sha256});
            serde_json::to_value(advance_published_cognitive_upgrade_v1(&fleet, &plan).await?)?
        }
        "publish" => publish_cognitive_artifact_v1(&fleet, serde_json::from_slice::<CognitiveArtifactPublicationInputV1>(&bytes)?)?,
        "revoke" => revoke_cognitive_artifact_v1(&fleet, serde_json::from_slice::<CognitiveArtifactRevocationInputV1>(&bytes)?)?,
        _ => bail!("{usage}"),
    };
    Ok(output)
    }.await;
    let finished_at = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
    let output = match &result {
        Ok(output) => output.clone(),
        Err(error) => json!({"state":"failed", "reason":format!("{error:#}")}),
    };
    let candidate_to_install = (output.get("state").and_then(serde_json::Value::as_str) == Some("installed"))
        .then(|| candidate_observed_at.and_then(|candidate| finished_at.checked_sub(candidate))).flatten();
    println!("{}", serde_json::to_string(&json!({
        "schema":"hepta.cognitive-upgrade-observation.v1", "command":command,
        "input_sha256":expected, "identity":identity,
        "started_at_unix_micros":started_at, "finished_at_unix_micros":finished_at,
        "monotonic_elapsed_micros":u64::try_from(started.elapsed().as_micros())?,
        "candidate_observed_at_unix_micros":candidate_observed_at,
        "candidate_to_install_wall_clock_micros":candidate_to_install,
        "observed_qualified_update_count":null, "independent_operator_evidence":null,
        "result":output,
    }))?);
    result.map(|_| ())
}
