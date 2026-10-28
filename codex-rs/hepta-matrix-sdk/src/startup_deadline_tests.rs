use std::cell::Cell;
use std::error::Error;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use pretty_assertions::assert_eq;

use super::MATRIX_STARTUP_TIMEOUT;
use super::MatrixSdkClient;
use super::MatrixSdkError;
use super::MatrixSession;
use super::MatrixSidecarConfig;
use super::load_session;
use super::persist_session;

fn fixture() -> Result<(tempfile::TempDir, HeptaAgentLayout, MatrixSidecarConfig), Box<dyn Error>> {
    let root = tempfile::tempdir()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.path().canonicalize()?)?
        .layout()
        .agent(&agent_id);
    let config = MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id,
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
            expected_mxid: MatrixUserId::parse("@deadline:example.test")?,
            expected_device_id: MatrixDeviceId::parse("DEADLINE")?,
            allowed_rooms: vec![MatrixRoomId::parse("!deadline:example.test")?],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test")?],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: Duration::from_secs(1),
    };
    config.validate(&layout)?;
    Ok((root, layout, config))
}

#[tokio::test]
async fn fresh_login_cannot_renew_expired_startup_budget() -> Result<(), Box<dyn Error>> {
    let (_root, layout, config) = fixture()?;
    let result = MatrixSdkClient::login_password_until(
        &layout,
        config,
        "must not be sent after the original startup deadline",
        Some("full-strength human passphrase"),
        /*device_display_name*/ None,
        tokio::time::Instant::now(),
    )
    .await;
    assert_eq!(result.map(|_| ()), Err(MatrixSdkError::Initialization));
    assert!(!layout.matrix_root().exists());
    Ok(())
}

#[tokio::test]
async fn expired_authentication_does_not_poll_the_request() {
    let polled = Cell::new(false);
    let result = MatrixSdkClient::authenticate_until(tokio::time::Instant::now(), async {
        polled.set(true);
        Ok::<_, ()>("a request must not start after its startup budget")
    })
    .await;
    assert_eq!(result, Err(MatrixSdkError::Authentication));
    assert!(!polled.get());
}

#[tokio::test]
async fn authentication_returning_late_ready_cannot_activate_a_session() {
    let polled = Cell::new(false);
    let startup_deadline = tokio::time::Instant::now() + Duration::from_secs(1);
    let result = MatrixSdkClient::authenticate_until(startup_deadline, async {
        polled.set(true);
        // Model a synchronous SDK operation that returns Ready in its first
        // poll, after the shared deadline. Tokio's timer cannot preempt it.
        std::thread::sleep(Duration::from_millis(1_100));
        Ok::<_, ()>("late session")
    })
    .await;
    assert!(polled.get());
    assert_eq!(result, Err(MatrixSdkError::Authentication));
}

#[tokio::test]
async fn expired_finalization_rejects_success_without_erasing_a_written_session()
-> Result<(), Box<dyn Error>> {
    let (_root, layout, config) = fixture()?;
    let sidecar = MatrixSdkClient::build_until(
        &layout,
        config,
        Some("full-strength human passphrase"),
        tokio::time::Instant::now() + MATRIX_STARTUP_TIMEOUT,
    )
    .await?;
    let session = MatrixSession {
        meta: SessionMeta {
            user_id: "@deadline:example.test".try_into()?,
            device_id: "DEADLINE".into(),
        },
        tokens: SessionTokens {
            access_token: "local-deadline-test-access-token".to_string(),
            refresh_token: Some("local-deadline-test-refresh-token".to_string()),
        },
    };
    let startup_deadline = tokio::time::Instant::now();
    persist_session(sidecar.paths.session(), &session)?;
    assert_eq!(
        sidecar.finish_startup(startup_deadline),
        Err(MatrixSdkError::Initialization)
    );
    assert_eq!(load_session(sidecar.paths.session())?, Some(session));
    assert!(sidecar.client.user_id().is_none());
    Ok(())
}
