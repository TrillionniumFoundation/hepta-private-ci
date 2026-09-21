use std::path::PathBuf;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::load_plasticity_process_bootstrap_v1;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut authbus_trust_file: Option<PathBuf> = None;
        let mut plasticity_bootstrap_descriptor: Option<PathBuf> = None;
        while let Some(flag) = args.next() {
            if flag == "--authbus-trust-file" {
                anyhow::ensure!(
                    authbus_trust_file.is_none(),
                    "--authbus-trust-file may be supplied at most once"
                );
                authbus_trust_file = Some(
                    args.next()
                        .ok_or_else(|| anyhow::anyhow!("--authbus-trust-file requires a path"))?
                        .into(),
                );
            } else if flag == "--plasticity-bootstrap-descriptor" {
                anyhow::ensure!(
                    plasticity_bootstrap_descriptor.is_none(),
                    "--plasticity-bootstrap-descriptor may be supplied at most once"
                );
                plasticity_bootstrap_descriptor = Some(
                    args.next()
                        .ok_or_else(|| {
                            anyhow::anyhow!("--plasticity-bootstrap-descriptor requires a path")
                        })?
                        .into(),
                );
            } else {
                anyhow::bail!("unknown Agentd argument");
            }
        }

        if let Some(path) = authbus_trust_file {
            config = config.with_authbus_trust_file(path);
        }
        if let Some(path) = plasticity_bootstrap_descriptor {
            let bootstrap = load_plasticity_process_bootstrap_v1(&path, config.identity())?;
            config = config.with_plasticity_runtime_bootstrap(bootstrap)?;
        }

        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
