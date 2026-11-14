//! Explicit isolated qualification with real V13 processes and live authorities.
//! Public fixture issuers do not certify production adoption or model quality.

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
#[path = "neuron_v13_guarded_acceptance/runner.rs"]
mod runner;

#[cfg(target_os = "linux")]
fn main() -> anyhow::Result<()> {
    codex_arg0::arg0_dispatch_or_else_with_preflight(|| {
        let arguments: Vec<_> = std::env::args_os().skip(1).collect();
        anyhow::ensure!(
            arguments.len() == 6,
            "usage: neuron_v13_guarded_acceptance DESCRIPTOR SHA256 NEW_OUTPUT NEW_ROOT_AUTHORITY SECOND_TASK SHA256"
        );
        let digest = |index: usize| -> anyhow::Result<codex_hepta_types::Digest32> {
            Ok(arguments[index]
                .to_str()
                .ok_or_else(|| anyhow::anyhow!("digest is not UTF-8"))?
                .parse()?)
        };
        let inputs = runner::Inputs {
            descriptor: (&arguments[0]).into(),
            expected: digest(1)?,
            output: (&arguments[2]).into(),
            root_authority: (&arguments[3]).into(),
            second_task: (&arguments[4]).into(),
            task_sha: digest(5)?,
        };
        anyhow::ensure!(
            !inputs.output.starts_with(&inputs.root_authority)
                && !inputs.root_authority.starts_with(&inputs.output),
            "authority and worker directories must be separate"
        );
        let host =
            lifecycle::initialize_host(&inputs.output, "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c76")?;
        Ok(move |arg0_paths| async move { runner::run(inputs, host, &arg0_paths).await })
    })
}

#[cfg(not(target_os = "linux"))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("guarded V13 qualification requires Linux and existing root authority")
}
