use codex_hepta_agentd::AgentdConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut authbus_seen = false;
        let mut browser_seen = false;
        while let Some(flag) = args.next() {
            if flag == "--authbus-trust-file" {
                anyhow::ensure!(!authbus_seen, "duplicate --authbus-trust-file");
                let path = args
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("--authbus-trust-file requires a path"))?;
                config = config.with_authbus_trust_file(path.into());
                authbus_seen = true;
            } else if flag == "--browser-servo-config" {
                anyhow::ensure!(!browser_seen, "duplicate --browser-servo-config");
                let path = args
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("--browser-servo-config requires a path"))?;
                config = config.with_browser_servo_config_file(path.into());
                browser_seen = true;
            } else {
                anyhow::bail!("unknown Agentd argument");
            }
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
