//! Real native process transport fixture; production authorization is tested by
//! the separate signed AutomationStore integration, not minted by this program.

use codex_hepta_automation::HcsnJobIdentityV1;
use codex_hepta_automation::HcsnProcessSupervisor;
use codex_hepta_automation::HcsnProcessSupervisorConfig;
use codex_hepta_automation::HcsnSupervisor;
use codex_hepta_automation::HcsnSupervisorCommandV1;
use codex_hepta_contracts::Sha256Digest;
use serde_json::Value;
use std::error::Error;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 || !matches!(args[1].as_str(), "start" | "status") {
        return Err("expected start|status and fixture directory".into());
    }
    let root = PathBuf::from(&args[2]);
    let config: Value = serde_json::from_slice(&fs::read(root.join("supervisor-config.json"))?)?;
    let mut supervisor = HcsnProcessSupervisor::new(HcsnProcessSupervisorConfig {
        python_executable: config["python_executable"]
            .as_str()
            .ok_or("python path")?
            .into(),
        python_sha256: Sha256Digest::parse(
            config["python_sha256"].as_str().ok_or("python digest")?,
        )?,
        repository_root: config["repository_root"]
            .as_str()
            .ok_or("repository root")?
            .into(),
        supervisor_sha256: Sha256Digest::parse(
            config["supervisor_sha256"]
                .as_str()
                .ok_or("supervisor digest")?,
        )?,
        durable_root: config["durable_root"]
            .as_str()
            .ok_or("durable root")?
            .into(),
        deadline: Duration::from_secs(10),
    })?;
    let payload = fs::read(root.join("request.json"))?;
    let identity = HcsnJobIdentityV1::for_taskflow(
        "hcsn-fixture-host",
        "fixture-run",
        "train",
        Sha256Digest::for_bytes(&payload),
    )?;
    let command = HcsnSupervisorCommandV1::start(identity, String::from_utf8(payload)?)?;
    let command = if args[1] == "status" {
        command.status()
    } else {
        command
    };
    let observation = supervisor.exchange(&command)?;
    println!("{}", serde_json::to_string(&observation)?);
    Ok(())
}
