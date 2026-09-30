use super::*;
use codex_app_server_protocol::Account;
use codex_app_server_protocol::GetAccountParams;
use codex_app_server_protocol::GetAccountResponse;
use codex_app_server_protocol::LoginAccountParams;
use codex_login::AuthCredentialsStoreMode;
use codex_login::AuthKeyringBackendKind;
use codex_login::login_with_api_key;
use codex_utils_absolute_path::AbsolutePathBuf;

#[tokio::test]
#[serial]
async fn host_owned_profile_survives_account_rpc_override_and_logout() -> Result<()> {
    let server = MockServer::start().await;
    let agent_home = TempDir::new()?;
    let profile = TempDir::new()?;
    login_with_api_key(
        profile.path(),
        "shared-profile-test-key",
        AuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::default(),
    )?;
    let original_profile = std::fs::read(profile.path().join("auth.json"))?;
    let mut config = build_test_config(agent_home.path(), &server.uri()).await?;
    config.cli_auth_credentials_store_mode = AuthCredentialsStoreMode::File;
    let (processor, mut outgoing) = build_test_processor_with_credential_profile(
        Arc::new(config),
        Some(AbsolutePathBuf::from_absolute_path(profile.path())?),
    )
    .await;
    let session = Arc::new(ConnectionSessionState::new());
    let initialize = ClientRequest::Initialize {
        request_id: RequestId::Integer(1),
        params: InitializeParams {
            client_info: ClientInfo {
                name: "profile-boundary-test".to_string(),
                title: None,
                version: "0.1.0".to_string(),
            },
            capabilities: None,
        },
    };
    processor
        .process_request(
            TEST_CONNECTION_ID,
            request_from_client_request(initialize),
            &AppServerTransport::Stdio,
            Arc::clone(&session),
        )
        .await;
    let _: InitializeResponse = read_response(&mut outgoing, 1).await;
    for request in [
        ClientRequest::LoginAccount {
            request_id: RequestId::Integer(2),
            params: LoginAccountParams::ApiKey {
                api_key: "request-override-test-key".to_string(),
            },
        },
        ClientRequest::LogoutAccount {
            request_id: RequestId::Integer(3),
            params: None,
        },
    ] {
        let id = request.id().clone();
        processor
            .process_request(
                TEST_CONNECTION_ID,
                request_from_client_request(request),
                &AppServerTransport::Stdio,
                Arc::clone(&session),
            )
            .await;
        loop {
            let envelope = tokio::time::timeout(std::time::Duration::from_secs(5), outgoing.recv())
                .await?
                .expect("outgoing response");
            if let crate::outgoing_message::OutgoingEnvelope::ToConnection {
                message: crate::outgoing_message::OutgoingMessage::Error(error),
                ..
            } = envelope
                && error.id == id
            {
                assert_eq!(-32600, error.error.code);
                assert!(error.error.message.contains("owned by the app-server host"));
                break;
            }
        }
    }
    let read = ClientRequest::GetAccount {
        request_id: RequestId::Integer(4),
        params: GetAccountParams {
            refresh_token: false,
        },
    };
    processor
        .process_request(
            TEST_CONNECTION_ID,
            request_from_client_request(read),
            &AppServerTransport::Stdio,
            Arc::clone(&session),
        )
        .await;
    let account: GetAccountResponse = read_response(&mut outgoing, 4).await;
    assert_eq!(Some(Account::ApiKey {}), account.account);
    assert_eq!(
        original_profile,
        std::fs::read(profile.path().join("auth.json"))?
    );
    assert!(!agent_home.path().join("auth.json").exists());
    processor.shutdown_threads().await;
    processor.drain_background_tasks().await;
    Ok(())
}
