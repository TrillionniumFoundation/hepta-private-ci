//! Offline fixture for the old-to-new Matrix store migration qualification.
//! Every identity, passphrase, and token below is synthetic. No login or sync
//! is performed; an explicit server-version list prevents discovery traffic.

use matrix_sdk::Client;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use matrix_sdk::authentication::matrix::MatrixSession;
use matrix_sdk::ruma::api::MatrixVersion;
use matrix_sdk::ruma::owned_device_id;
use matrix_sdk::ruma::owned_user_id;
use serde_json::json;
use std::path::PathBuf;

const FIXTURE_KEY: &[u8] = b"hepta-store-compat-fixture-v1";
const FIXTURE_VALUE: &[u8] = b"preserve-this-encrypted-state-across-sdk-upgrades";
const FIXTURE_PASSPHRASE: &str = "synthetic-ci-only-passphrase-not-a-real-credential";

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 || !matches!(args[1].as_str(), "create" | "verify" | "wrong-passphrase") {
        return Err(
            "usage: store_compat_probe create|verify|wrong-passphrase STORE EXPECTED_JSON".into(),
        );
    }
    let mode = args[1].as_str();
    let store = PathBuf::from(&args[2]);
    let receipt = PathBuf::from(&args[3]);
    if mode == "create" {
        if store.exists() || receipt.exists() {
            return Err("fixture creation requires absent output paths".into());
        }
        std::fs::create_dir_all(&store)?;
    } else if !store.is_dir() || !receipt.is_file() {
        return Err("verification requires an existing old-version fixture".into());
    }
    let session = MatrixSession {
        meta: SessionMeta {
            user_id: owned_user_id!("@compat-fixture:example.invalid"),
            device_id: owned_device_id!("HEPTA_SYNTHETIC_COMPAT"),
        },
        tokens: SessionTokens {
            access_token: "synthetic-unused-token-no-network-request".to_string(),
            refresh_token: None,
        },
    };
    let passphrase = if mode == "wrong-passphrase" {
        "deliberately-wrong-synthetic-passphrase"
    } else {
        FIXTURE_PASSPHRASE
    };
    let restored = async {
        let client = Client::builder()
            .homeserver_url("http://127.0.0.1:9")
            .server_versions([MatrixVersion::V1_0])
            .sqlite_store(&store, Some(passphrase))
            .build()
            .await?;
        client.restore_session(session).await?;
        Ok::<_, Box<dyn std::error::Error>>(client)
    }
    .await;
    if mode == "wrong-passphrase" {
        if restored.is_ok() {
            return Err("encrypted store accepted the wrong passphrase".into());
        }
        println!("wrong_passphrase_rejected=true");
        return Ok(());
    }
    let client = restored?;
    if mode == "create" {
        client
            .state_store()
            .set_custom_value(FIXTURE_KEY, FIXTURE_VALUE.to_vec())
            .await?;
    }
    let marker = client.state_store().get_custom_value(FIXTURE_KEY).await?;
    if marker.as_deref() != Some(FIXTURE_VALUE) {
        return Err("the old custom state was not preserved".into());
    }
    let device = client
        .encryption()
        .get_own_device()
        .await?
        .ok_or("missing persisted crypto device")?;
    let observed = json!({
        "user_id": device.user_id().as_str(),
        "device_id": device.device_id().as_str(),
        "curve25519": device.curve25519_key().ok_or("missing curve key")?.to_base64(),
        "ed25519": device.ed25519_key().ok_or("missing signing key")?.to_base64(),
        "marker": String::from_utf8(FIXTURE_VALUE.to_vec())?,
    });
    if mode == "create" {
        std::fs::write(receipt, serde_json::to_vec_pretty(&observed)?)?;
    } else {
        let expected: serde_json::Value = serde_json::from_slice(&std::fs::read(receipt)?)?;
        if observed != expected {
            return Err("migration changed the persisted device identity or custom state".into());
        }
    }
    println!("{mode}_fixture_verified=true");
    Ok(())
}
