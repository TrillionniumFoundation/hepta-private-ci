//! Explicit qualified-neural composition around the original Agentd runtime.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use codex_hepta_agentd::AgentdConfig;
    use codex_hepta_infer_worker_host::smollm_cognitive_host::prepare_smollm_neural_agentd_v1;
    use codex_hepta_infer_worker_host::smollm_cognitive_process::load_smollm_cognitive_host_inputs_v1;
    use codex_hepta_types::Digest32;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use std::io;
    use std::path::PathBuf;

    // Helper re-execs must reach the original dispatch before daemon flags.
    codex_arg0::arg0_dispatch_or_else(|arg0_paths| async move {
        let mut path = None;
        let mut digest = None;
        let mut args = std::env::args_os().skip(1);
        while let Some(flag) = args.next() {
            if flag == "--help" {
                println!("hepta-neural-agentd --host-config ABSOLUTE_JSON --host-config-sha256 HEX\nUses the normal HEPTA_AGENT_* identity and original Agentd runtime. The pinned hepta-smollm-cognitive-host-v1 file must reference a real product-qualified neural bootstrap v3 and an independently operated Unix FinalUse issuer. No model fallback or qualification is manufactured.");
                return Ok(());
            }
            let value = args.next().ok_or_else(|| io::Error::other("missing neural host argument value"))?;
            if flag == "--host-config" && path.is_none() {
                path = Some(PathBuf::from(value));
            } else if flag == "--host-config-sha256" && digest.is_none() {
                digest = Some(value.into_string().map_err(|_| io::Error::other("host digest must be UTF-8"))?
                    .parse::<Digest32>().map_err(io::Error::other)?);
            } else {
                return Err(io::Error::other(format!("unknown or duplicate neural host flag {flag:?}")).into());
            }
        }
        let path = path.ok_or_else(|| io::Error::other("--host-config is required"))?;
        let digest = digest.ok_or_else(|| io::Error::other("--host-config-sha256 is required"))?;
        let config = AgentdConfig::from_process_environment()?;
        let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
        codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
        let inputs = load_smollm_cognitive_host_inputs_v1(&path, digest).map_err(io::Error::other)?;
        let prepared = prepare_smollm_neural_agentd_v1(config, inputs).await.map_err(io::Error::other)?;
        // The normal control socket and CognitiveContext route own evidence of
        // later use. Merely loading a model emits no synthetic success receipt.
        let result = codex_hepta_agentd::run(prepared.config, arg0_paths).await;
        let unloaded = prepared.session.shutdown().await;
        match (result, unloaded) {
            (Ok(()), Ok(())) => Ok(()),
            (Err(error), Ok(())) => Err(error.into()),
            (Ok(()), Err(error)) => Err(io::Error::other(error).into()),
            (Err(run), Err(unload)) => Err(io::Error::other(format!("Agentd failed: {run}; terminal unload failed: {unload}")).into()),
        }
    }).map_err(Into::into)
}

#[cfg(not(target_os = "linux"))]
fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    Err("the qualified SmolLM cognitive host requires the Linux observed-process profile".into())
}
