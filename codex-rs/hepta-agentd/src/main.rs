use codex_hepta_agentd::AgentdConfig;
use codex_hepta_types::Digest32;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut trust_file = None;
        let mut restore_checkpoint = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("Agentd flag requires a value"))?;
            match flag.to_str() {
                Some("--authbus-trust-file") if trust_file.is_none() => {
                    trust_file = Some(value.into());
                }
                Some("--authbus-restore-checkpoint") if restore_checkpoint.is_none() => {
                    let text = value
                        .to_str()
                        .ok_or_else(|| anyhow::anyhow!("AuthBus checkpoint must be UTF-8"))?;
                    let (generation, digest) = text.split_once(':').ok_or_else(|| {
                        anyhow::anyhow!("AuthBus checkpoint must be generation:digest")
                    })?;
                    let generation = generation.parse::<u64>()?;
                    let digest = digest
                        .parse::<Digest32>()
                        .map_err(|_| anyhow::anyhow!("invalid AuthBus checkpoint digest"))?;
                    anyhow::ensure!(
                        generation != 0 && !digest.is_zero(),
                        "AuthBus checkpoint must be nonzero"
                    );
                    restore_checkpoint = Some((generation, digest));
                }
                _ => anyhow::bail!("unknown or duplicate Agentd argument"),
            }
        }

        anyhow::ensure!(
            trust_file.is_some() == restore_checkpoint.is_some(),
            "--authbus-trust-file and --authbus-restore-checkpoint must be configured together"
        );
        if let (Some(path), Some((generation, digest))) = (trust_file, restore_checkpoint) {
            config = config
                .with_authbus_trust_file(path)
                .with_authbus_restore_checkpoint(generation, digest)?;
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}
