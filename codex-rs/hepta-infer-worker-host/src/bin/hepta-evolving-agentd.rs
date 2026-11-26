fn main() -> anyhow::Result<()> {
    // The root trust endpoint enrolls this immutable process, not arbitrary
    // same-UID code. Disable ptrace/core access before loading host inputs.
    #[cfg(target_os = "linux")]
    rustix::process::set_dumpable_behavior(rustix::process::DumpableBehavior::NotDumpable)?;
    codex_hepta_agentd::run_with_process_configuration(|config| {
        codex_hepta_infer_worker_host::evolving_agentd::compose_installed_model_owner(config)
            .map_err(|error| anyhow::anyhow!(error.to_string()))
    })
}
