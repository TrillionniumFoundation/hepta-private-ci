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
        let mut objective_profile = None;
        let mut evidence_trust = None;
        let mut automation_effect_host = None;
        let mut evidence_recovery_frontier = None;
        let mut evidence_recovery_frontier_trust = None;
        while let Some(flag) = args.next() {
            let path = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag:?} requires a path"))?;
            if flag == "--authbus-trust-file" {
                anyhow::ensure!(authbus_trust.is_none(), "duplicate --authbus-trust-file");
                authbus_trust = Some(path);
            } else if flag == "--objective-profile-file" {
                anyhow::ensure!(
                    objective_profile.is_none(),
                    "duplicate --objective-profile-file"
                );
                objective_profile = Some(path);
            } else if flag == "--automation-effect-host-file" {
                anyhow::ensure!(
                    automation_effect_host.is_none(),
                    "duplicate --automation-effect-host-file"
                );
                automation_effect_host = Some(path);
            } else if flag == "--evidence-trust-file" {
                anyhow::ensure!(evidence_trust.is_none(), "duplicate --evidence-trust-file");
                evidence_trust = Some(path);
            } else if flag == "--evidence-recovery-frontier-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier.is_none(),
                    "duplicate --evidence-recovery-frontier-file"
                );
                evidence_recovery_frontier = Some(path);
            } else if flag == "--evidence-recovery-frontier-trust-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier_trust.is_none(),
                    "duplicate --evidence-recovery-frontier-trust-file"
                );
                evidence_recovery_frontier_trust = Some(path);
            } else {
                anyhow::bail!("unknown Agentd argument {flag:?}");
            }
        }
        if let Some(path) = authbus_trust {
            config = config.with_authbus_trust_file(path.into());
        }
        if let Some(path) = automation_effect_host {
            config = config.with_automation_effect_host_file(path.into());
        }
        if let Some(path) = objective_profile {
            config = config.with_objective_profile_file(path.into());
        }
        if let Some(path) = evidence_trust {
            config = config.with_evidence_trust_file(path.into());
        }
        match (evidence_recovery_frontier, evidence_recovery_frontier_trust) {
            (Some(frontier), Some(trust)) => {
                config =
                    config.with_evidence_recovery_frontier_files(frontier.into(), trust.into());
            }
            (None, None) => {}
            _ => anyhow::bail!(
                "--evidence-recovery-frontier-file and --evidence-recovery-frontier-trust-file must be supplied together"
            ),
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
