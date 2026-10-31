//! Explicit qualified-neural composition around the original Agentd runtime.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use codex_hepta_agentd::AgentdConfig;
    use codex_hepta_infer_worker_host::smollm_cognitive_host::SmolLmCognitiveCellHostInputsV2;
    use codex_hepta_infer_worker_host::smollm_cognitive_host::SmolLmCognitiveHostInputsV1;
    use codex_hepta_infer_worker_host::smollm_cognitive_host::prepare_smollm_cell_neural_agentd_v2;
    use codex_hepta_infer_worker_host::smollm_cognitive_host::prepare_smollm_neural_agentd_v1;
    use codex_hepta_infer_worker_host::smollm_cognitive_process::load_smollm_cognitive_cell_host_inputs_v2;
    use codex_hepta_infer_worker_host::smollm_cognitive_process::load_smollm_cognitive_host_inputs_v1;
    use codex_hepta_types::Digest32;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use std::io;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    use std::path::PathBuf;

    enum HostInputs {
        Original(SmolLmCognitiveHostInputsV1),
        Cell(SmolLmCognitiveCellHostInputsV2),
    }

    // Helper re-execs must reach the original dispatch before daemon flags.
    codex_arg0::arg0_dispatch_or_else_with_preflight(|| {
        let arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
        let cell_v2 = arguments.windows(2)
            .any(|pair| pair[0] == "--host-format" && pair[1] == "cell-v2");
        if cell_v2 {
            // An anonymous sealed ELF cannot supply the original path-based
            // helper re-execs inside a fresh sandbox PID namespace. Reject this
            // unsupported image before aliases, qualifications or model owners.
            let message = "Cell-v2 requires a reopenable native image for original helper/sandbox routes; anonymous sealed-image execution is unavailable";
            let image = std::fs::File::open("/proc/self/exe")?.metadata()?;
            let path = std::env::current_exe()?;
            let reopened = std::fs::OpenOptions::new().read(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                .open(path).map_err(|_| io::Error::other(message))?.metadata()?;
            if !reopened.is_file() || (image.dev(), image.ino()) != (reopened.dev(), reopened.ino()) {
                return Err(io::Error::other(message).into());
            }
        }
        Ok(())
    }, |arg0_paths| async move {
        let mut path = None;
        let mut digest = None;
        let mut host_format = None;
        let mut args = std::env::args_os().skip(1);
        while let Some(flag) = args.next() {
            if flag == "--help" {
                println!("hepta-neural-agentd --host-config ABSOLUTE_JSON --host-config-sha256 HEX [--host-format owner-v1|cell-v2]\nUses the normal HEPTA_AGENT_* identity and original Agentd runtime. owner-v1 (default) requires the original hepta-smollm-cognitive-host-v1 file. cell-v2 requires hepta-smollm-cognitive-cell-host-v2 with independently pinned complete TCD1 and sidecar bytes. Both retain real product-qualified neural bootstrap v3 and independently operated Unix FinalUse admission. No model fallback or qualification is manufactured.");
                return Ok(());
            }
            let value = args.next().ok_or_else(|| io::Error::other("missing neural host argument value"))?;
            if flag == "--host-config" && path.is_none() {
                path = Some(PathBuf::from(value));
            } else if flag == "--host-config-sha256" && digest.is_none() {
                digest = Some(value.into_string().map_err(|_| io::Error::other("host digest must be UTF-8"))?
                    .parse::<Digest32>().map_err(io::Error::other)?);
            } else if flag == "--host-format" && host_format.is_none() {
                host_format = Some(value.into_string().map_err(|_| io::Error::other("host format must be UTF-8"))?);
            } else {
                return Err(io::Error::other(format!("unknown or duplicate neural host flag {flag:?}")).into());
            }
        }
        let path = path.ok_or_else(|| io::Error::other("--host-config is required"))?;
        let digest = digest.ok_or_else(|| io::Error::other("--host-config-sha256 is required"))?;
        let host_format = host_format.as_deref().unwrap_or("owner-v1");
        // Only protected byte snapshots are decoded here. Qualification and
        // selected parameter FDs still come from the original runtime owners.
        let inputs = match host_format {
            "owner-v1" => HostInputs::Original(load_smollm_cognitive_host_inputs_v1(&path, digest).map_err(io::Error::other)?),
            "cell-v2" => HostInputs::Cell(load_smollm_cognitive_cell_host_inputs_v2(&path, digest).map_err(io::Error::other)?),
            _ => return Err(io::Error::other("unsupported neural host format").into()),
        };
        let config = AgentdConfig::from_process_environment()?;
        let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
        codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
        let prepared = match inputs {
            HostInputs::Cell(inputs) => {
                prepare_smollm_cell_neural_agentd_v2(config, inputs).await.map_err(io::Error::other)?
            }
            HostInputs::Original(inputs) => {
                prepare_smollm_neural_agentd_v1(config, inputs).await.map_err(io::Error::other)?
            }
        };
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
