use std::error::Error;
use std::fs;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_sdk::MatrixSdkClient;
use codex_hepta_matrix_sdk::MatrixSdkPaths;
use codex_hepta_matrix_sdk::MatrixSession;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use matrix_sdk::store::StateStoreDataKey;
use matrix_sdk::store::StateStoreDataValue;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

#[derive(Deserialize)]
struct LegacyFixture {
    session: MatrixSession,
    ed25519_key: String,
    curve25519_key: String,
    passphrase: String,
    filter_name: String,
    filter_id: String,
    databases: Vec<LegacyDatabase>,
}

#[derive(Deserialize)]
struct LegacyDatabase {
    path: String,
    sql: String,
}

struct LegacySetup {
    _directory: TempDir,
    layout: HeptaAgentLayout,
    config: MatrixSidecarConfig,
    paths: MatrixSdkPaths,
    fixture: LegacyFixture,
}

async fn legacy_setup() -> TestResult<LegacySetup> {
    let directory = tempfile::tempdir()?;
    let fleet = directory.path().join("fleet");
    fs::create_dir_all(&fleet)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(fleet.canonicalize()?)?
        .layout()
        .agent(&agent_id);
    let fixture: LegacyFixture = serde_json::from_str(include_str!("fixtures/matrix_0_18.json"))?;
    let config = MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id,
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
            expected_mxid: MatrixUserId::parse(fixture.session.meta.user_id.as_str())?,
            expected_device_id: MatrixDeviceId::parse(fixture.session.meta.device_id.as_str())?,
            allowed_rooms: vec![MatrixRoomId::parse("!allowed:example.test")?],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test")?],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: Duration::from_secs(1),
    };
    let paths = MatrixSdkPaths::prepare(&layout, &config)?;
    let sqlite = SqliteConfig::new_for_testing(paths.root().try_into()?);
    for database in &fixture.databases {
        let path = paths.root().join(&database.path);
        let pool = sqlite.open_read_write_pool(&path).await?;
        let mut connection = pool.acquire().await?;
        // This SQL is the checked-in historical fixture included above. It is
        // never assembled from configuration, requests, or other runtime input.
        sqlx::raw_sql(sqlx::AssertSqlSafe(database.sql.as_str()))
            .execute(&mut *connection)
            .await?;
        drop(connection);
        pool.close().await;
    }
    Ok(LegacySetup {
        _directory: directory,
        layout,
        config,
        paths,
        fixture,
    })
}

#[tokio::test]
async fn legacy_encrypted_storage_migrates_and_reopens_with_the_same_identity() -> TestResult {
    let setup = legacy_setup().await?;
    let restored = MatrixSdkClient::restore(
        &setup.layout,
        setup.config.clone(),
        setup.fixture.session.clone(),
        Some(&setup.fixture.passphrase),
    )
    .await?;
    assert_eq!(restored.paths(), &setup.paths);
    let filter = restored
        .client()
        .state_store()
        .get_kv_data(StateStoreDataKey::Filter(&setup.fixture.filter_name))
        .await?
        .and_then(StateStoreDataValue::into_filter);
    assert_eq!(filter, Some(setup.fixture.filter_id.clone()));
    assert!(
        restored
            .client()
            .state_store()
            .get_kv_data(StateStoreDataKey::SyncToken)
            .await?
            .is_none()
    );
    let expected_identity = (
        Some(setup.fixture.session.clone()),
        Some(setup.fixture.ed25519_key.clone()),
        Some(setup.fixture.curve25519_key.clone()),
    );
    assert_eq!(persistent_identity(&restored).await, expected_identity);
    drop(restored);

    let (reopened, session) = MatrixSdkClient::login_or_restore(
        &setup.layout,
        setup.config,
        "no-network-login-is-needed",
        Some(&setup.fixture.passphrase),
        /*device_display_name*/ None,
    )
    .await?;
    assert_eq!(session, setup.fixture.session);
    assert_eq!(persistent_identity(&reopened).await, expected_identity);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        assert_eq!(
            fs::metadata(setup.paths.session())?.permissions().mode() & 0o777,
            0o600
        );
    }
    Ok(())
}

#[tokio::test]
async fn wrong_passphrase_preserves_the_existing_encrypted_store() -> TestResult {
    let setup = legacy_setup().await?;
    let wrong_passphrase = MatrixSdkClient::restore(
        &setup.layout,
        setup.config.clone(),
        setup.fixture.session.clone(),
        Some("different-fixture-passphrase"),
    )
    .await;
    assert!(wrong_passphrase.is_err());
    assert!(!setup.paths.session().exists());

    let restored = MatrixSdkClient::restore(
        &setup.layout,
        setup.config,
        setup.fixture.session.clone(),
        Some(&setup.fixture.passphrase),
    )
    .await?;
    assert_eq!(
        persistent_identity(&restored).await,
        (
            Some(setup.fixture.session),
            Some(setup.fixture.ed25519_key),
            Some(setup.fixture.curve25519_key),
        )
    );
    Ok(())
}

async fn persistent_identity(
    sidecar: &MatrixSdkClient,
) -> (Option<MatrixSession>, Option<String>, Option<String>) {
    (
        sidecar.client().matrix_auth().session(),
        sidecar.client().encryption().ed25519_key().await,
        sidecar
            .client()
            .encryption()
            .curve25519_key()
            .await
            .map(|key| key.to_base64()),
    )
}
