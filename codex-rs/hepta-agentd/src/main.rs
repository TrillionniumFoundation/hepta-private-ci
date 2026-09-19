use codex_hepta_agentd::AgentdConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut authbus_trust = None;
        let mut evidence_trust = None;
        while let Some(flag) = args.next() {
            let path = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag:?} requires a path"))?;
            if flag == "--authbus-trust-file" {
                anyhow::ensure!(authbus_trust.is_none(), "duplicate --authbus-trust-file");
                authbus_trust = Some(path);
            } else if flag == "--evidence-trust-file" {
                anyhow::ensure!(evidence_trust.is_none(), "duplicate --evidence-trust-file");
                evidence_trust = Some(path);
            } else {
                anyhow::bail!("unknown Agentd argument {flag:?}");
            }
        }
        if let Some(path) = authbus_trust {
            config = config.with_authbus_trust_file(path.into());
        }
        if let Some(path) = evidence_trust {
            config = config.with_evidence_trust_file(path.into());
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
