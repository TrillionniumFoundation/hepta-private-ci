use codex_hepta_agentd::AgentdConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut trust_file = None;
        let mut checkpoint_file = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("Agentd flag requires a value"))?;
            match flag.to_str() {
                Some("--authbus-trust-file") if trust_file.is_none() => {
                    trust_file = Some(value.into());
                }
                Some("--authbus-checkpoint-file") if checkpoint_file.is_none() => {
                    checkpoint_file = Some(value.into());
                }
                _ => anyhow::bail!("unknown or duplicate Agentd argument"),
            }
        }
        anyhow::ensure!(
            trust_file.is_some() == checkpoint_file.is_some(),
            "--authbus-trust-file and --authbus-checkpoint-file must be configured together"
        );
        if let (Some(trust), Some(checkpoint)) = (trust_file, checkpoint_file) {
            config = config
                .with_authbus_trust_file(trust)
                .with_authbus_checkpoint_file(checkpoint);
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
