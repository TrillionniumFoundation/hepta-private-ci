use super::auth_manager_for_runtime;
use codex_core::config::Config;
use codex_core::config::ConfigBuilder;
use codex_login::AuthCredentialsStoreMode;
use codex_login::AuthKeyringBackendKind;
use codex_login::login_with_api_key;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::TempDir;

async fn config(home: &Path) -> Config {
    let mut config = ConfigBuilder::default()
        .codex_home(home.to_path_buf())
        .build()
        .await
        .expect("private runtime config");
    config.cli_auth_credentials_store_mode = AuthCredentialsStoreMode::File;
    config
}

fn login(home: &Path, key: &str) {
    login_with_api_key(
        home,
        key,
        AuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::default(),
    )
    .expect("write synthetic test credential");
}

#[tokio::test]
async fn two_private_agent_homes_share_one_explicit_profile_and_canonical_reload() {
    let agent_a = TempDir::new().expect("agent a home");
    let agent_b = TempDir::new().expect("agent b home");
    let profile = TempDir::new().expect("credential profile");
    login(agent_a.path(), "agent-a-test-key");
    login(agent_b.path(), "agent-b-test-key");
    login(profile.path(), "shared-test-key");
    let original_a = std::fs::read(agent_a.path().join("auth.json")).unwrap();
    let original_b = std::fs::read(agent_b.path().join("auth.json")).unwrap();
    let config_a = config(agent_a.path()).await;
    let config_b = config(agent_b.path()).await;
    let profile_home = AbsolutePathBuf::from_absolute_path(profile.path()).unwrap();
    let manager_a = auth_manager_for_runtime(&config_a, Some(&profile_home))
        .await
        .expect("agent a profile manager");
    let manager_b = auth_manager_for_runtime(&config_b, Some(&profile_home))
        .await
        .expect("agent b profile manager");
    for manager in [&manager_a, &manager_b] {
        assert_eq!(
            Some("shared-test-key"),
            manager
                .auth_cached()
                .as_ref()
                .and_then(|auth| auth.api_key())
        );
    }
    login(profile.path(), "rotated-test-key");
    for manager in [&manager_a, &manager_b] {
        manager.reload().await;
        assert_eq!(
            Some("rotated-test-key"),
            manager
                .auth_cached()
                .as_ref()
                .and_then(|auth| auth.api_key())
        );
    }
    assert_eq!(agent_a.path(), config_a.codex_home.as_path());
    assert_eq!(agent_b.path(), config_b.codex_home.as_path());
    assert_eq!(
        original_a,
        std::fs::read(agent_a.path().join("auth.json")).unwrap()
    );
    assert_eq!(
        original_b,
        std::fs::read(agent_b.path().join("auth.json")).unwrap()
    );
}

#[tokio::test]
async fn absent_profile_uses_each_runtime_home_and_missing_explicit_profile_fails() {
    let agent_a = TempDir::new().expect("agent a home");
    let agent_b = TempDir::new().expect("agent b home");
    login(agent_a.path(), "isolated-a-test-key");
    login(agent_b.path(), "isolated-b-test-key");
    for (home, expected) in [
        (agent_a.path(), "isolated-a-test-key"),
        (agent_b.path(), "isolated-b-test-key"),
    ] {
        let config = config(home).await;
        let manager = auth_manager_for_runtime(&config, /*credential_profile_home*/ None)
            .await
            .expect("isolated manager");
        assert_eq!(
            Some(expected),
            manager
                .auth_cached()
                .as_ref()
                .and_then(|auth| auth.api_key())
        );
        let missing = AbsolutePathBuf::from_absolute_path(home.join("missing-profile")).unwrap();
        let error = auth_manager_for_runtime(&config, Some(&missing))
            .await
            .expect_err("explicit missing profile must not fall back");
        assert_eq!(std::io::ErrorKind::InvalidInput, error.kind());
    }
}
