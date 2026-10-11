//! Regression for RUSTSEC-2026-0318 using real SDK machines and signed device keys.
//! No server, live session, or external message is used.
use matrix_sdk::ruma::TransactionId;
use matrix_sdk::ruma::api::client::keys::get_keys::v3::Response;
use matrix_sdk::ruma::device_id;
use matrix_sdk::ruma::user_id;
use matrix_sdk_crypto::CollectStrategy;
use matrix_sdk_crypto::OlmMachine;
use pretty_assertions::assert_eq;
use serde_json::json;

#[tokio::test]
async fn identity_strategy_rejects_unsigned_recipient_without_panicking()
-> Result<(), Box<dyn std::error::Error>> {
    let alice = OlmMachine::new(user_id!("@alice:fixture.invalid"), device_id!("ALICE")).await;
    let bob = OlmMachine::new(user_id!("@bob:fixture.invalid"), device_id!("BOB")).await;
    let bootstrap = alice.bootstrap_cross_signing(/*reset*/ false).await?;
    let bob_device = bob
        .get_device(bob.user_id(), bob.device_id(), /*timeout*/ None)
        .await?
        .ok_or("missing Bob device")?;
    let mut response = Response::new();
    response.device_keys.insert(
        bob.user_id().to_owned(),
        std::collections::BTreeMap::from([(
            bob.device_id().to_owned(),
            matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
                bob_device.as_device_keys(),
            )?),
        )]),
    );
    let own_device = alice
        .get_device(alice.user_id(), alice.device_id(), /*timeout*/ None)
        .await?
        .ok_or("missing Alice device")?;
    response.device_keys.insert(
        alice.user_id().to_owned(),
        std::collections::BTreeMap::from([(
            alice.device_id().to_owned(),
            matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
                own_device.as_device_keys(),
            )?),
        )]),
    );
    response.master_keys.insert(
        alice.user_id().to_owned(),
        matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
            &bootstrap
                .upload_signing_keys_req
                .master_key
                .ok_or("missing master key")?,
        )?),
    );
    response.self_signing_keys.insert(
        alice.user_id().to_owned(),
        matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
            &bootstrap
                .upload_signing_keys_req
                .self_signing_key
                .ok_or("missing self signing key")?,
        )?),
    );
    response.user_signing_keys.insert(
        alice.user_id().to_owned(),
        matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
            &bootstrap
                .upload_signing_keys_req
                .user_signing_key
                .ok_or("missing user signing key")?,
        )?),
    );
    alice
        .mark_request_as_sent(&TransactionId::new(), &response)
        .await?;
    let recipient = alice
        .get_device(bob.user_id(), bob.device_id(), /*timeout*/ None)
        .await?
        .ok_or("missing recipient")?;
    let content = json!({"test": "isolated advisory regression"});
    let single = recipient
        .encrypt_event_raw(
            "org.hepta.fixture",
            &content,
            CollectStrategy::IdentityBasedStrategy,
        )
        .await;
    assert!(
        matches!(single, Err(matrix_sdk_crypto::OlmError::Withheld(_))),
        "unexpected encryption result: {single:?}"
    );
    let (requests, blocked) = alice
        .encrypt_content_for_devices(
            vec![(*recipient).clone()],
            "org.hepta.fixture",
            &content,
            CollectStrategy::IdentityBasedStrategy,
        )
        .await?;
    assert!(requests.is_empty());
    assert_eq!(blocked.len(), 1);
    assert_eq!(blocked[0].0.device_id(), bob.device_id());
    Ok(())
}

#[test]
fn shared_blake3_patch_preserves_official_known_answer() {
    let mut hash = blake3::Hasher::new();
    // Official BLAKE3 test vector: input bytes 0, 1, 2.
    hash.update(&[0]);
    hash.update(&[1, 2]);
    assert_eq!(
        hash.finalize().to_hex().as_str(),
        "e1be4d7a8ab5560aa4199eea339849ba8e293d55ca0a81006726d184519e647f"
    );
}
