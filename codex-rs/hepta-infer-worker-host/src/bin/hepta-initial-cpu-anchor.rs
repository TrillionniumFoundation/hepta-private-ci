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
        "publish-initial-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::publish_initial_cpu_anchor(
                path, pin,
            )?
        }
        "select-initial-operational" => {
            codex_hepta_infer_worker_host::initial_cpu_anchor::select_initial_cpu_anchor(path, pin)?
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
