//! Concrete independently owned credential-consumer production entry point.

#[cfg(target_os = "linux")]
#[tokio::main]
async fn main() -> std::process::ExitCode {
    use codex_hepta_bao_adapter::CredentialConsumerServiceConfig;
    use codex_hepta_bao_adapter::serve_credential_consumer;
    let mut arguments = std::env::args_os().skip(1);
    let command = arguments.next();
    let configuration = arguments.next();
    if command.as_deref() != Some(std::ffi::OsStr::new("serve-consumer"))
        || arguments.next().is_some()
    {
        eprintln!("usage: hepta-secrets-runtime serve-consumer /etc/hepta-secrets/consumer.json");
        return std::process::ExitCode::from(64);
    }
    let Some(configuration) = configuration else {
        eprintln!("missing root-owned credential-consumer configuration");
        return std::process::ExitCode::from(64);
    };
    let result = async {
        let config =
            CredentialConsumerServiceConfig::load_root_owned(std::path::Path::new(&configuration))?;
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .map_err(|_| codex_hepta_bao_adapter::ConsumerPortError::Unavailable)?;
        serve_credential_consumer(config, async move {
            tokio::select! {
                _ = terminate.recv() => {},
                _ = tokio::signal::ctrl_c() => {},
            }
        })
        .await
    }
    .await;
    match result {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("credential consumer stopped: {error}");
            std::process::ExitCode::FAILURE
        }
    }
}

#[cfg(not(target_os = "linux"))]
fn main() -> std::process::ExitCode {
    eprintln!("the enrolled local credential-consumer IPC requires Linux kernel peer credentials");
    std::process::ExitCode::from(69)
}
