#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    rustix::process::set_dumpable_behavior(rustix::process::DumpableBehavior::NotDumpable)?;
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.len() != 3 {
        return Err("expected fixed purpose, Root deployment path and checksum".into());
    }
    let path = std::path::Path::new(&arguments[1]);
    let pin = arguments[2].parse()?;
    let report = match arguments[0].as_str() {
        "select-registered-self-iteration-stage" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_registered_cpu_self_iteration_stage_v1(path, pin)?
        }
        "publish-parameter-pre-registration" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_parameter_pre_registered_artifacts_v1(path, pin)?
        }
        "select-parameter-pre-registration" => codex_hepta_infer_worker_host::initial_cpu_anchor::select_parameter_pre_registered_artifacts_v1(path, pin)?,
        "observe-self-iteration-canary" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::observe_cpu_self_iteration_canary(path, pin)?
        }
        "select-self-iteration-stage" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_cpu_self_iteration_stage(path, pin)?
        }
        "initialize-offline-authbus-checkpoint" => {
            tokio::runtime::Runtime::new()?.block_on(
                codex_hepta_infer_worker_host::initial_cpu_anchor::initialize_initial_cpu_authbus_checkpoint(path, pin),
            )?
        }
        "sign-cpu-objective" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::sign_initial_cpu_objective(path, pin)?
        }
        "deliver-cpu-objective" => {
            tokio::runtime::Runtime::new()?.block_on(
                codex_hepta_infer_worker_host::initial_cpu_anchor::deliver_initial_cpu_objective(path, pin),
            )?
        }
        "inspect-cpu-objective" => {
            tokio::runtime::Runtime::new()?.block_on(
                codex_hepta_infer_worker_host::initial_cpu_anchor::inspect_initial_cpu_objective(path, pin),
            )?
        }
        "prepare-initial-objective-source" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::prepare_initial_cpu_objective_source(
                path, pin,
            )?
        }
        "preview-operational-model-use-v2" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::preview_operational_model_use_v2(
                path, pin,
            )?
        }
        "select-registered-model-use-v3" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_cpu_registered_model_use_v3(path, pin)?
        }
        "select-installed-model-use-v2" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_cpu_model_use_v2(path, pin)?
        }
        "inspect-learning-withdrawal" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::inspect_initial_cpu_withdrawal(
                path, pin,
            )?
        }
        "withdraw-learning-dataset" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::withdraw_initial_cpu_dataset(
                path, pin,
            )?
        }
        "publish-installed-model-use-continuation-v2" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_installed_model_use_continuation_v2(path, pin)?
        }
        "preview-initial-objective" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::preview_initial_cpu_objective(
                path, pin,
            )?
        }
        "publish-initial-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_initial_cpu_anchor(
                path, pin,
            )?
        }
        "select-initial-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_initial_cpu_anchor(path, pin)?
        }
        "publish-renewed-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_renewed_cpu_operational(
                path, pin,
            )?
        }
        "select-renewed-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_renewed_cpu_operational(
                path, pin,
            )?
        }
        "describe-current-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::describe_current_cpu_operational(
                path, pin,
            )?
        }
        "publish-first-installed-profile" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_first_installed_cpu_profile(
                path, pin,
            )?
        }
        "select-first-installed-profile" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_first_installed_cpu_profile(
                path, pin,
            )?
        }
        _ => return Err("unsupported initial operational purpose".into()),
    };
    println!("{}", serde_json::to_string(&report)?);
    if arguments[0] == "withdraw-learning-dataset" && report["phase"] != "artifact_acknowledged" {
        return Err("withdrawal is incomplete; retain the original request and resolve its existing checkpoint".into());
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    Err("fixed initial CPU custody requires the installed Linux role boundary".into())
}
