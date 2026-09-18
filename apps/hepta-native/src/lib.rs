#![forbid(unsafe_code)]

pub mod app;
pub mod backend;
pub mod journal;
pub mod platform;
pub mod runtime;
pub mod security;
pub mod types;
pub mod update;

use sha2::Digest as _;
use sha2::Sha256;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub const APP_ID: &str = "ai.hepta.native";
pub const APP_NAME: &str = "Hepta Native";
pub const PROTOCOL_VERSION: u32 = 1;
pub const MAX_STABLE_ID_BYTES: usize = 128;
pub const MAX_JSON_BYTES: usize = 2 * 1024 * 1024;

pub fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

pub fn now_unix_ms() -> Result<u64, std::time::SystemTimeError> {
    let millis = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    Ok(u64::try_from(millis).unwrap_or(u64::MAX))
}

pub fn validate_digest(value: &str) -> bool {
    value.len() == 64
        && value != "0".repeat(64)
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

pub fn validate_stable_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_STABLE_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

pub fn state_root() -> std::io::Result<std::path::PathBuf> {
    let root = dirs_next::data_local_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("hepta")
        .join("native-v1");
    std::fs::create_dir_all(&root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(root)
}

pub fn self_test() -> Result<serde_json::Value, Box<dyn std::error::Error>> {
    use crate::journal::OperationJournal;
    use crate::types::OperationKey;
    use crate::types::PlatformAction;

    let unique = format!(
        "hepta-native-self-test-{}-{}",
        std::process::id(),
        now_unix_ms()?
    );
    let root = std::env::temp_dir().join(unique);
    std::fs::create_dir_all(&root)?;
    let journal = OperationJournal::open(root.join("operations.jsonl"))?;
    let key = OperationKey {
        session_id: "self-test.session".to_string(),
        session_generation: 1,
        operation_id: "self-test.operation".to_string(),
    };
    let digest = sha256_hex(b"self-test-payload");
    let start = journal.begin_dispatch(&key, PlatformAction::CopyText, &digest)?;
    let ok = matches!(start, crate::journal::DispatchDisposition::Started);
    let _ = std::fs::remove_dir_all(&root);
    Ok(serde_json::json!({
        "schema": "hepta.native.self-test.v1",
        "ok": ok,
        "platform": std::env::consts::OS,
        "architecture": std::env::consts::ARCH,
        "rust_state_machine": true,
        "effect_authority": false,
    }))
}
