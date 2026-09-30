fn main() -> anyhow::Result<()> {
    codex_hepta_agentd::run_with_process_configuration(|config| {
        codex_hepta_infer_worker_host::evolving_agentd::compose_installed_model_owner(config)
            .map_err(|error| anyhow::anyhow!(error.to_string()))
    })
}
