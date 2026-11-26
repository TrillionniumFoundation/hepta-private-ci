//! Owner-local installation and lifecycle control. No signing keys or model
//! credentials cross this CLI's control requests.

#[cfg(unix)]
#[path = "../fleet_cli.rs"]
mod fleet_cli;

#[cfg(unix)]
#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    fleet_cli::run(std::env::args_os().skip(1)).await
}

#[cfg(not(unix))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("hepta-fleetctl requires the Unix Supervisor runtime")
}
