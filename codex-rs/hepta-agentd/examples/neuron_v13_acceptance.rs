//! Explicit real-asset acceptance through the ordinary embedded Agentd runtime.
//! This executable is never a default test or a product model selector.

#[cfg(target_os = "linux")]
#[path = "neuron_v13_acceptance/descriptor.rs"]
mod descriptor;
#[cfg(target_os = "linux")]
#[path = "neuron_v13_acceptance/lifecycle.rs"]
mod lifecycle;
#[cfg(target_os = "linux")]
#[path = "neuron_v13_acceptance/observations.rs"]
mod observations;
#[cfg(target_os = "linux")]
#[path = "neuron_v13_acceptance/runner.rs"]
mod runner;

#[cfg(target_os = "linux")]
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    anyhow::ensure!(
        arguments.len() == 3,
        "usage: neuron_v13_acceptance ABSOLUTE_DESCRIPTOR EXPECTED_SHA256 NEW_OUTPUT_DIRECTORY"
    );
    let expected = arguments[1]
        .to_str()
        .ok_or_else(|| anyhow::anyhow!("descriptor digest is not UTF-8"))?
        .parse::<codex_hepta_types::Digest32>()?;
    let input = descriptor::load(std::path::Path::new(&arguments[0]), expected)?;
    runner::run(input, std::path::Path::new(&arguments[2])).await
}

#[cfg(not(target_os = "linux"))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("V13 ordinary-runtime acceptance requires Linux")
}
