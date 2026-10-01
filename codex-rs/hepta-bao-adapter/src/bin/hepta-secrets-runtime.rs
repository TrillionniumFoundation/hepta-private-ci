//! Actual local role services and the independently approved issuance caller.

#[cfg(target_os = "linux")]
#[tokio::main]
async fn main() -> std::process::ExitCode {
    use codex_hepta_bao_adapter::ConsumerPortError;
    use codex_hepta_bao_adapter::CredentialConsumerServiceConfig;
    use codex_hepta_bao_adapter::SecretsAuthorityClient;
    use codex_hepta_bao_adapter::SecretsAuthorityServiceConfig;
    use codex_hepta_bao_adapter::SecretsOperatorServiceConfig;
    use codex_hepta_bao_adapter::SecretsRoleClientConfig;
    let mut arguments = std::env::args_os().skip(1);
    let command = arguments.next();
    let configuration = arguments.next();
    let operation = arguments.next();
    if arguments.next().is_some() || configuration.is_none() {
        eprintln!(
            "usage: hepta-secrets-runtime serve-consumer|serve-authority|serve-operator /etc/hepta-secrets/role.json\n       hepta-secrets-runtime authorize-original|original-status /etc/hepta-secrets/client.json ORIGINAL_ID"
        );
        return std::process::ExitCode::from(64);
    }
    let Some(configuration) = configuration else {
        return std::process::ExitCode::from(64);
    };
    let result = async {
        let path = std::path::Path::new(&configuration);
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .map_err(|_| ConsumerPortError::Unavailable)?;
        let shutdown = async move {
            tokio::select! {_=terminate.recv()=>{},_=tokio::signal::ctrl_c()=>{}}
        };
        match command.as_deref().and_then(std::ffi::OsStr::to_str) {
            Some("serve-consumer") if operation.is_none() => {
                codex_hepta_bao_adapter::serve_credential_consumer(
                    CredentialConsumerServiceConfig::load_root_owned(path)?,
                    shutdown,
                )
                .await
            }
            Some("serve-authority") if operation.is_none() => {
                codex_hepta_bao_adapter::serve_secrets_authority(
                    SecretsAuthorityServiceConfig::load_root_owned(path)?,
                    shutdown,
                )
                .await
            }
            Some("serve-operator") if operation.is_none() => {
                codex_hepta_bao_adapter::serve_secrets_operator(
                    SecretsOperatorServiceConfig::load_root_owned(path)?,
                    shutdown,
                )
                .await
            }
            Some("authorize-original" | "original-status") => {
                let operation = operation
                    .as_deref()
                    .and_then(std::ffi::OsStr::to_str)
                    .ok_or(ConsumerPortError::Invalid)?;
                let client =
                    SecretsAuthorityClient::new(SecretsRoleClientConfig::load_root_owned(path)?)?;
                let output =
                    if command.as_deref() == Some(std::ffi::OsStr::new("authorize-original")) {
                        serde_json::to_string(&client.authorize_original(operation)?)
                            .map_err(|_| ConsumerPortError::Unavailable)?
                    } else {
                        serde_json::to_string(&client.original_status(operation)?)
                            .map_err(|_| ConsumerPortError::Unavailable)?
                    };
                println!("{output}");
                Ok(())
            }
            _ => Err(ConsumerPortError::Invalid),
        }
    }
    .await;
    match result {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("secrets role stopped: {error}");
            std::process::ExitCode::FAILURE
        }
    }
}
#[cfg(not(target_os = "linux"))]
fn main() -> std::process::ExitCode {
    eprintln!("enrolled local secrets IPC requires Linux kernel peer credentials");
    std::process::ExitCode::from(69)
}
