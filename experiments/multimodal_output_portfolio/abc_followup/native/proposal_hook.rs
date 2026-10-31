//! Pause one live owner, propose at its exact anchor, then let the caller recover.
use std::fs::File;
use std::path::Path;
use std::process::{Command,Stdio};
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::{json,Value};

type Result<T>=std::result::Result<T,Box<dyn std::error::Error>>;

#[derive(Deserialize)]
pub struct Hook {
    pub proposal_binary:String,
    pub proposal_binary_sha256:String,
    pub python_binary:String,
    pub python_binary_sha256:String,
    pub evaluation_entrypoint:String,
    pub evaluation_entrypoint_sha256:String,
    pub evaluation_protocol:String,
    pub evaluation_protocol_sha256:String,
    pub evaluation_data:String,
    pub model:String,
}

fn checked(path:&str,expected:&str)->Result<()> {
    if Digest32::of_bytes(&std::fs::read(path)?).to_string()!=expected {
        return Err("Live proposal dependency changed".into());
    }
    Ok(())
}

fn execute(command:&mut Command,path:&Path)->Result<()> {
    let log=File::create_new(path)?;
    let status=command.stdout(Stdio::from(log.try_clone()?)).stderr(Stdio::from(log.try_clone()?)).status()?;
    log.sync_all()?;
    if !status.success() {return Err(format!("Live proposal child failed: {status}; see {}",path.display()).into());}
    Ok(())
}

pub fn run(hook:&Hook,packet:&str,packet_sha:&str,root:&Path,context:&Value,future:bool)->Result<Value> {
    let began=Instant::now();
    checked(&hook.proposal_binary,&hook.proposal_binary_sha256)?;
    checked(&hook.python_binary,&hook.python_binary_sha256)?;
    checked(&hook.evaluation_entrypoint,&hook.evaluation_entrypoint_sha256)?;
    checked(&hook.evaluation_protocol,&hook.evaluation_protocol_sha256)?;
    let candidates=root.join("live-proposal-candidates");
    execute(Command::new(&hook.proposal_binary).args([packet,packet_sha]).arg(root).arg(&candidates),
        &root.join("live-candidates.log"))?;
    let evaluation=root.join("live-proposal-evaluation.json");
    let module=if future {"experiments.multimodal_output_portfolio.abc_followup.native.future_candidate"}
        else {"experiments.multimodal_output_portfolio.abc_followup.native.old_candidate"};
    execute(Command::new(&hook.python_binary).args(["-B","-m","experiments.multimodal_output_portfolio.abc_followup.process",
        "--receipt"]).arg(root.join("live-evaluation.process.json")).args(["--module",module,"--","--candidates"])
        .arg(candidates.join("candidates.json")).args(["--protocol",&hook.evaluation_protocol,"--model",&hook.model,
            "--data",&hook.evaluation_data,"--output"]).arg(&evaluation),&root.join("live-evaluation-wrapper.log"))?;
    let pending=root.join("live-proposal-pending");
    execute(Command::new(&hook.proposal_binary).args([packet,packet_sha]).arg(root).arg(&pending).arg(&evaluation),
        &root.join("live-pending.log"))?;
    let proposal:Value=serde_json::from_slice(&std::fs::read(pending.join("result.json"))?)?;
    if proposal["same_context_neuron_anchor"]!=context["anchor"] || proposal["core_proposal_persisted"]!=true
        || proposal["proposal_recovered"]!=true || proposal["applied_model_update"]!=false {
        return Err("Same-anchor pending proposal or recovery mismatch".into());
    }
    Ok(json!({"sequence":context["sequence"],"pair":context["pair"],"anchor":context["anchor"],
        "future_head":future,"actual_owner_resolutions":proposal["actual_owner_resolutions"],
        "update_candidates":proposal["update_candidates"],"core_proposal_digest":proposal["core_proposal_digest"],
        "pending_registry_anchor":proposal["proposal_anchor"],"proposal_recovered":true,
        "same_context_runtime_recovered_after_proposal":false,"product_admission":proposal["product_admission"],
        "product_error":proposal["product_error"],"applied_update":false,"independent_candidate_acceptance":false,
        "evaluation_sha256":Digest32::of_bytes(&std::fs::read(evaluation)?).to_string(),
        "wall_micros":began.elapsed().as_micros(),"authority":"deny_all"}))
}
