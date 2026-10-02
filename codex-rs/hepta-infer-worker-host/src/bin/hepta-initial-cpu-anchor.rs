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
        "preview-operational-model-use-v2" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::preview_operational_model_use_v2(
                path, pin,
            )?
        }
        "select-installed-model-use-v2" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_cpu_model_use_v2(path, pin)?
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
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    Err("fixed initial CPU custody requires the installed Linux role boundary".into())
}
