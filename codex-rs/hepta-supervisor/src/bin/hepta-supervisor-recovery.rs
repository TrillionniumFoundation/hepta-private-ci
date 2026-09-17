use std::collections::BTreeMap;
use std::ffi::OsString;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SignedRecoveryResolution;
use codex_hepta_supervisor::inspect_signed_recovery;
use codex_hepta_supervisor::resolve_signed_recovery;

#[cfg(unix)]
use codex_hepta_supervisor::UnixProcessDriver;
#[cfg(unix)]
use codex_hepta_supervisor::fence_signed_recovery;

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .and_then(|value| value.into_string().ok())
        .ok_or_else(|| anyhow::anyhow!(usage()))?;
    let flags = parse_flags(args)?;
    let fleet_root =
        HeptaFleetRoot::parse(PathBuf::from(required(&flags, "--fleet-root")?.as_os_str()))?;
    let registry = FleetRegistry::open_existing(fleet_root)?;
    let agent_id = AgentId::parse(os_text(required(&flags, "--agent-id")?, "--agent-id")?)
        .map_err(|error| anyhow::anyhow!("invalid --agent-id: {error}"))?;

    match command.as_str() {
        "inspect" => print_json(&inspect_signed_recovery(&registry, &agent_id)?)?,
        "fence" => run_fence(&registry, &agent_id)?,
        "resolve" => {
            let grant = Sha256Digest::parse(os_text(
                required(&flags, "--grant-sha256")?,
                "--grant-sha256",
            )?)
            .map_err(|error| anyhow::anyhow!("invalid --grant-sha256: {error}"))?;
            let control_revision_successor = parse_u64(
                required(&flags, "--control-revision-successor")?,
                "--control-revision-successor",
            )?;
            let lifecycle_generation = parse_u64(
                required(&flags, "--lifecycle-generation")?,
                "--lifecycle-generation",
            )?;
            let release_state_generation = parse_u64(
                required(&flags, "--release-state-generation")?,
                "--release-state-generation",
            )?;
            let authority_epoch =
                parse_u64(required(&flags, "--authority-epoch")?, "--authority-epoch")?;
            let resolution = match os_text(required(&flags, "--outcome")?, "--outcome")?.as_str() {
                "commit" => SignedRecoveryResolution::Commit,
                "abort" => SignedRecoveryResolution::Abort,
                _ => anyhow::bail!("--outcome must be commit or abort"),
            };
            print_json(&resolve_signed_recovery(
                &registry,
                &agent_id,
                &grant,
                control_revision_successor,
                lifecycle_generation,
                release_state_generation,
                authority_epoch,
                resolution,
            )?)?;
        }
        _ => anyhow::bail!(usage()),
    }
    Ok(())
}

#[cfg(unix)]
fn run_fence(registry: &FleetRegistry, agent_id: &AgentId) -> anyhow::Result<()> {
    let mut driver = UnixProcessDriver::new(64)?;
    print_json(&fence_signed_recovery(registry, &mut driver, agent_id)?)?;
    Ok(())
}

#[cfg(not(unix))]
fn run_fence(_registry: &FleetRegistry, _agent_id: &AgentId) -> anyhow::Result<()> {
    anyhow::bail!("fence is supported only on Unix process-driver hosts")
}

fn parse_flags(
    mut args: impl Iterator<Item = OsString>,
) -> anyhow::Result<BTreeMap<String, OsString>> {
    let mut flags = BTreeMap::new();
    while let Some(flag) = args.next() {
        let flag = flag
            .into_string()
            .map_err(|_| anyhow::anyhow!("flag name is not UTF-8"))?;
        if !flag.starts_with("--") || flags.contains_key(&flag) {
            anyhow::bail!(usage());
        }
        let value = args
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing value for {flag}"))?;
        flags.insert(flag, value);
    }
    Ok(flags)
}

fn required<'a>(flags: &'a BTreeMap<String, OsString>, name: &str) -> anyhow::Result<&'a OsString> {
    flags
        .get(name)
        .ok_or_else(|| anyhow::anyhow!("{name} is required\n{}", usage()))
}

fn os_text(value: &OsString, label: &str) -> anyhow::Result<String> {
    value
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| anyhow::anyhow!("{label} is not UTF-8"))
}

fn parse_u64(value: &OsString, label: &str) -> anyhow::Result<u64> {
    os_text(value, label)?
        .parse::<u64>()
        .map_err(|error| anyhow::anyhow!("{label} is invalid: {error}"))
}

fn print_json(value: &impl serde::Serialize) -> anyhow::Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}

fn usage() -> &'static str {
    "usage:\n  hepta-supervisor-recovery inspect --fleet-root ABSOLUTE_PATH --agent-id UUID\n  hepta-supervisor-recovery fence --fleet-root ABSOLUTE_PATH --agent-id UUID\n  hepta-supervisor-recovery resolve --fleet-root ABSOLUTE_PATH --agent-id UUID --outcome commit|abort --grant-sha256 HEX --control-revision-successor N --lifecycle-generation N --release-state-generation N --authority-epoch N"
}
