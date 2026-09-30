//! Explicitly enabled Linux root service for ordinary runtime.codex grants.
//! Its key cannot issue independent evaluation or self-evolution acceptance.

fn main() -> anyhow::Result<()> {
    #[cfg(target_os = "linux")]
    {
        let args: Vec<_> = std::env::args_os().skip(1).collect();
        if args.len() != 2 || args[0] != "--config" {
            anyhow::bail!("usage: hepta-model-authority --config ROOT_PROTECTED_JSON");
        }
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()?
            .block_on(codex_hepta_supervisor::run_local_model_authority(
                std::path::Path::new(&args[1]),
            ))
    }
    #[cfg(not(target_os = "linux"))]
    anyhow::bail!("local model authority requires Linux")
}
