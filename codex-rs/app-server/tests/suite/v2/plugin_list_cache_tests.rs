use super::cached_remote_catalog_plugin_ids;
use super::rewrite_cached_remote_catalog_fetched_at;
use anyhow::Result;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::NamedTempFile;
use tempfile::TempDir;

#[test]
fn cached_remote_catalog_helpers_ignore_unpublished_atomic_files() -> Result<()> {
    let codex_home = TempDir::new()?;
    let cache_dir = codex_home.path().join("cache/remote_plugin_catalog");
    std::fs::create_dir_all(&cache_dir)?;
    let published_path = cache_dir.join("0000000000000001.json");
    let mut expected = json!({
        "schema_version": 1,
        "fetched_at": null,
        "plugins": [{ "id": "committed-plugin" }]
    });
    std::fs::write(&published_path, serde_json::to_vec(&expected)?)?;
    // Hold the empty sibling open, as write_atomically does before writing.
    let in_flight = NamedTempFile::new_in(&cache_dir)?;

    assert_eq!(
        cached_remote_catalog_plugin_ids(codex_home.path())?,
        vec!["committed-plugin".to_string()]
    );
    let refreshed_at = chrono::Utc::now();
    rewrite_cached_remote_catalog_fetched_at(codex_home.path(), refreshed_at)?;
    expected["fetched_at"] = serde_json::to_value(refreshed_at)?;
    let observed: serde_json::Value = serde_json::from_slice(&std::fs::read(&published_path)?)?;
    assert_eq!(observed, expected);
    assert_eq!(std::fs::read(in_flight.path())?, Vec::<u8>::new());
    Ok(())
}

#[test]
fn cached_remote_catalog_helpers_reject_malformed_published_json() -> Result<()> {
    let codex_home = TempDir::new()?;
    let cache_dir = codex_home.path().join("cache/remote_plugin_catalog");
    std::fs::create_dir_all(&cache_dir)?;
    let published_path = cache_dir.join("0000000000000001.json");
    std::fs::write(&published_path, b"{")?;

    assert!(cached_remote_catalog_plugin_ids(codex_home.path()).is_err());
    assert!(
        rewrite_cached_remote_catalog_fetched_at(codex_home.path(), chrono::Utc::now()).is_err()
    );
    assert_eq!(std::fs::read(published_path)?, b"{");
    Ok(())
}
