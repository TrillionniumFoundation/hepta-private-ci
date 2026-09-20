use codex_hepta_agentd::AgentdConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        if let Some(flag) = args.next() {
            anyhow::ensure!(flag == "--authbus-trust-file", "unknown Agentd argument");
            let path = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("--authbus-trust-file requires a path"))?;
            anyhow::ensure!(args.next().is_none(), "unexpected Agentd arguments");
            config = config.with_authbus_trust_file(path.into());
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
