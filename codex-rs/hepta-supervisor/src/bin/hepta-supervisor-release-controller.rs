use std::path::PathBuf;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::ProductionReleaseCallerStatusV1;
use codex_hepta_supervisor::ProductionReleaseController;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::read_production_release_request;

const USAGE: &str = "usage: hepta-supervisor-release-controller <dispatch|recover|status> --fleet-root ABSOLUTE_PATH --request ABSOLUTE_PATH --journal ABSOLUTE_PATH [--wait-seconds N]";
const DEFAULT_WAIT_SECONDS: u64 = 60;
const MAX_WAIT_SECONDS: u64 = 3_600;

#[derive(Clone, Copy)]
enum Command {
    Dispatch,
    Recover,
    Status,
}

struct Arguments {
    command: Command,
    fleet_root: PathBuf,
    request: PathBuf,
    journal: PathBuf,
    wait: Duration,
}

#[tokio::main]
async fn main() -> Result<()> {
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("context")) {
        return print_context().await;
    }
    let arguments = parse_arguments()?;
    let fleet_root = HeptaFleetRoot::parse(arguments.fleet_root)
        .context("validate production release fleet root")?;
    let request = read_production_release_request(&arguments.request)
        .context("read production release request")?;
    let client = SupervisordClient::new(fleet_root.layout().supervisor_socket().to_path_buf())?;
    let controller = ProductionReleaseController::new(client, arguments.journal)?;
    let journal = match arguments.command {
        Command::Dispatch => controller.dispatch(&request, arguments.wait).await?,
        Command::Recover => controller.recover(&request, arguments.wait).await?,
        Command::Status => controller.read_status(&request)?,
    };
    println!("{}", serde_json::to_string(&journal)?);
    match journal.status {
        ProductionReleaseCallerStatusV1::RecoveryRequired => {
            bail!("signed production mutation requires the explicit recovery ceremony")
        }
        ProductionReleaseCallerStatusV1::Indeterminate => {
            bail!("signed production mutation is indeterminate; blind replay is forbidden")
        }
        ProductionReleaseCallerStatusV1::Prepared
        | ProductionReleaseCallerStatusV1::Accepted
        | ProductionReleaseCallerStatusV1::Committed
        | ProductionReleaseCallerStatusV1::RolledBack
        | ProductionReleaseCallerStatusV1::Aborted => Ok(()),
    }
}

fn parse_arguments() -> Result<Arguments> {
    let mut arguments = std::env::args_os().skip(1);
    let command = match arguments.next().and_then(|value| value.into_string().ok()) {
        Some(value) if value == "dispatch" => Command::Dispatch,
        Some(value) if value == "recover" => Command::Recover,
        Some(value) if value == "status" => Command::Status,
        _ => bail!(USAGE),
    };
    let mut fleet_root = None;
    let mut request = None;
    let mut journal = None;
    let mut wait_seconds = DEFAULT_WAIT_SECONDS;
    let mut seen = std::collections::BTreeSet::new();
    while let Some(flag) = arguments.next() {
        let flag = flag
            .into_string()
            .map_err(|_| anyhow::anyhow!("flag is not UTF-8"))?;
        if !seen.insert(flag.clone()) {
            bail!("duplicate flag {flag}");
        }
        let value = arguments.next().ok_or_else(|| anyhow::anyhow!(USAGE))?;
        match flag.as_str() {
            "--fleet-root" => fleet_root = Some(PathBuf::from(value)),
            "--request" => request = Some(PathBuf::from(value)),
            "--journal" => journal = Some(PathBuf::from(value)),
            "--wait-seconds" => {
                wait_seconds = value
                    .into_string()
                    .map_err(|_| anyhow::anyhow!(USAGE))?
                    .parse::<u64>()
                    .context("parse --wait-seconds")?;
                if wait_seconds > MAX_WAIT_SECONDS {
                    bail!("--wait-seconds exceeds {MAX_WAIT_SECONDS}");
                }
            }
            _ => bail!(USAGE),
        }
    }
    let fleet_root = fleet_root.ok_or_else(|| anyhow::anyhow!(USAGE))?;
    let request = request.ok_or_else(|| anyhow::anyhow!(USAGE))?;
    let journal = journal.ok_or_else(|| anyhow::anyhow!(USAGE))?;
    if !fleet_root.is_absolute() || !request.is_absolute() || !journal.is_absolute() {
        bail!("fleet root, request and journal paths must be absolute");
    }
    Ok(Arguments {
        command,
        fleet_root,
        request,
        journal,
        wait: Duration::from_secs(wait_seconds),
    })
}

async fn print_context() -> Result<()> {
    let mut arguments = std::env::args_os().skip(2);
    let mut fleet = None;
    let mut agent = None;
    while let Some(flag) = arguments.next() {
        let value = arguments
            .next()
            .context("context option requires a value")?;
        match flag.to_str() {
            Some("--fleet-root") if fleet.is_none() => fleet = Some(PathBuf::from(value)),
            Some("--agent") if agent.is_none() => {
                let value = value
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("agent id is not UTF-8"))?;
                agent =
                    Some(codex_hepta_contracts::AgentId::parse(value).map_err(anyhow::Error::msg)?);
            }
            _ => bail!("unknown or duplicate context option"),
        }
    }
    let root = HeptaFleetRoot::parse(fleet.context("context requires --fleet-root")?)?;
    let client = SupervisordClient::new(root.layout().supervisor_socket().to_path_buf())?;
    let context = client
        .production_mutation_context(agent.context("context requires --agent")?)
        .await?;
    println!("{}", serde_json::to_string(&context)?);
    Ok(())
}
