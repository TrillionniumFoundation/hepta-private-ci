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
    let reservation = arguments.next();
    if arguments.next().is_some()
        || configuration.is_none()
        || (reservation.is_some()
            && !matches!(
                command.as_deref().and_then(std::ffi::OsStr::to_str),
                Some(
                    "settlement-original"
                        | "consume-original"
                        | "runtime-status"
                        | "recover-original"
                )
            ))
    {
        eprintln!(
            "usage: hepta-secrets-runtime serve-runtime|serve-consumer|serve-authority|serve-operator /etc/hepta-secrets/role.json\n       hepta-secrets-runtime authorize-original|original-status /etc/hepta-secrets/client.json ORIGINAL_ID\n       hepta-secrets-runtime settlement-original /etc/hepta-secrets/evidence.json ORIGINAL_ID RESERVATION_ID\n       hepta-secrets-runtime consume-original|runtime-status|recover-original /etc/hepta-secrets/agent.json ORIGINAL_ID AGENT_UUID"
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
            Some("serve-runtime") if operation.is_none() => {
                codex_hepta_bao_adapter::serve_secrets_runtime(codex_hepta_bao_adapter::SecretsRuntimeServiceConfig::load_root_owned(path)?, shutdown).await
            }
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
            Some("consume-original" | "runtime-status" | "recover-original") => {
                let operation = operation.as_deref().and_then(std::ffi::OsStr::to_str).ok_or(ConsumerPortError::Invalid)?;
                let agent = reservation.as_deref().and_then(std::ffi::OsStr::to_str).ok_or(ConsumerPortError::Invalid)?;
                let client = codex_hepta_bao_adapter::SecretsRuntimeClient::new(
                    codex_hepta_bao_adapter::SecretsRuntimeClientConfig::load_root_owned(path)?, agent)?;
                let response = match command.as_deref().and_then(std::ffi::OsStr::to_str) {
                    Some("consume-original") => client.consume_original(operation, std::time::Duration::from_secs(30))?,
                    Some("runtime-status") => client.original_status(operation)?,
                    Some("recover-original") => client.recover_original(operation)?,
                    _ => return Err(ConsumerPortError::Invalid),
                };
                println!("{}", serde_json::to_string(&response).map_err(|_| ConsumerPortError::Unavailable)?);
                Ok(())
            }
            Some("settlement-original") => {
                let operation = operation.as_deref().and_then(std::ffi::OsStr::to_str).ok_or(ConsumerPortError::Invalid)?;
                let reservation = reservation.as_deref().and_then(std::ffi::OsStr::to_str).ok_or(ConsumerPortError::Invalid)?;
                let client = codex_hepta_bao_adapter::ConsumerEvidenceClient::new(
                    codex_hepta_bao_adapter::ConsumerEvidenceConfig::load_root_owned(path)?)?;
                let signed = client.completed_original(operation, reservation)?;
                // This output is public signed metadata, never the credential.
                let claims = signed.claims;
                let output = serde_json::json!({"issuer_id":claims.issuer_id.as_str(), "key_epoch":claims.key_epoch.get(),
                    "reservation_id":claims.reservation_id.as_str(), "operation_id":claims.operation_id.as_str(),
                    "observed_cost":claims.observed_cost, "terminal_evidence_digest":claims.terminal_evidence_digest.as_array(),
                    "observed_at_ms":claims.observed_at_ms, "expires_at_ms":claims.expires_at_ms, "signature":signed.signature.to_vec()});
                println!("{output}");
                Ok(())
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
