//! Closed normal offline replay-witness initialization for the original Agent.
use super::*;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    program: Source,
    fleet_root: PathBuf,
    agent_id: String,
    checkpoint: PathBuf,
}

pub(super) async fn initialize(path: &Path, pin: Digest32) -> HostResult<Value> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(8192)?;
    let cfg: Configuration = serde_json::from_slice(&bytes)?;
    if cfg.schema != "hepta.agentd.offline-authbus-checkpoint-config.v1"
        || std::env::current_exe()?.canonicalize()? != cfg.program.path
    {
        return Err("closed normal offline checkpoint configuration".into());
    }
    let program = model_use_program::Program::open(cfg.program)?;
    let agent = cfg.agent_id.parse()?;
    let checkpoint = codex_hepta_agentd::initialize_offline_authbus_checkpoint_v1(
        &cfg.fleet_root,
        &agent,
        &cfg.checkpoint,
    )
    .await?;
    program.revalidate()?;
    if source.read(8192)? != bytes {
        return Err("offline checkpoint configuration changed".into());
    }
    Ok(serde_json::json!({
        "schema": "hepta.agentd.offline-authbus-checkpoint-result.v1",
        "configuration": source, "agent_id": cfg.agent_id,
        "generation": checkpoint.generation, "digest": checkpoint.digest.to_string(),
        "current_goal_authority_issued": false,
    }))
}
