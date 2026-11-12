use std::fs;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::ProviderEffectKey;
use pretty_assertions::assert_eq;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

use crate::automation_effect_host::tests::Fixture;
use crate::automation_effect_host::tests::WIRE;
use crate::automation_effect_host::tests::effect_intent;
use crate::automation_effect_host::tests::prepare_effect;
use crate::automation_effect_host::tests::signed_final_use;

use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_product_caller_retains_claimed_fact_before_contact_and_replays_once() {
    let fixture = Fixture::new().await;
    let now_ms = crate::authbus_ingress::now_ms().expect("wall clock");
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await;
    let retained = fixture
        .identity
        .layout
        .automation_root()
        .join(DIRECTORY)
        .join("slot-00.json");
    let server = MockServer::start().await;
    let key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("provider key");
    let ack = serde_json::json!({
        "effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"operation").as_str(), "status": "completed",
    });
    let provider_fact = retained.clone();
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .respond_with(move |_request: &wiremock::Request| {
            let fact: StoredFact = serde_json::from_slice(
                &fs::read(&provider_fact).expect("fact before provider contact"),
            )
            .expect("native retained fact");
            assert_eq!(fact.fact["claimed_step"]["state"], "claimed");
            assert_eq!(fact.fact["pending_attempt_at_second_read"], false);
            assert_eq!(fact.fact["source_provenance_authenticated"], false);
            assert_eq!(fact.fact["prediction_deployed"], false);
            assert!(fact.fact.get("wire_payload").is_none());
            assert!(fact.fact.get("signed_grant").is_none());
            assert!(fact.fact["claimed_step"].get("fence").is_none());
            assert!(
                !serde_json::to_string(&fact.fact)
                    .expect("fact JSON")
                    .contains("agentd-product-effect-fence")
            );
            ResponseTemplate::new(200).set_body_json(&ack)
        })
        .expect(1)
        .mount(&server)
        .await;
    let (host, signer, _) = fixture.open_effect_host(&server, &scope);
    let grant = signed_final_use(&intent, now_ms, &signer);
    let receipt = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "native-export",
            now_ms + 5,
        )
        .await
        .expect("original dispatch");
    let bytes = fs::read(&retained).expect("retained fact");
    let replay = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "native-export",
            now_ms + 6,
        )
        .await
        .expect("original replay");
    assert_eq!(receipt.receipt_digest, replay.receipt_digest);
    assert_eq!(fs::read(&retained).expect("same original fact"), bytes);
    assert_eq!(
        fs::read_dir(retained.parent().expect("root"))
            .expect("slots")
            .count(),
        1
    );
    server.verify().await;

    // Preserve the producer's exact original bytes only after the ordinary
    // dispatch and replay assertions pass. This remains a native test fixture.
    if let Some(output_root) = std::env::var_os("HEPTA_PRED_NATIVE_FIXTURE_DIR") {
        let output_root = PathBuf::from(output_root);
        assert!(output_root.is_absolute(), "absolute fixture output directory");
        let metadata = fs::symlink_metadata(&output_root).expect("existing fixture directory");
        assert!(
            metadata.is_dir()
                && !metadata.file_type().is_symlink()
                && metadata.permissions().mode() & 0o077 == 0,
            "private fixture output directory"
        );
        let mut fact_file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(output_root.join("native-fact.json"))
            .expect("new native fact output");
        fact_file.write_all(&bytes).expect("write original fact bytes");
        fact_file.sync_all().expect("sync original fact bytes");
        let manifest = serde_json::to_vec(&serde_json::json!({
            "schema": "hepta-pred-native-fixture-v1",
            "source": "native_test_fixture",
            "expected_owner": fixture.identity.agent_id.as_str(),
            "fact_file": "native-fact.json",
            "fact_sha256": Sha256Digest::for_bytes(&bytes).as_str(),
            "producer_test": "automation_predispatch_export::tests::ordinary_product_caller_retains_claimed_fact_before_contact_and_replays_once",
            "fixture_only": true,
            "independent_effect_labels": 0,
        }))
        .expect("fixture manifest JSON");
        let mut manifest_file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(output_root.join("manifest.json"))
            .expect("new native fixture manifest");
        manifest_file
            .write_all(&manifest)
            .expect("write fixture manifest");
        manifest_file.sync_all().expect("sync fixture manifest");
        fs::File::open(&output_root)
            .expect("fixture output directory")
            .sync_all()
            .expect("sync fixture output directory");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_rejection_has_no_fact_and_retention_failure_does_not_bypass_final_use() {
    let fixture = Fixture::new().await;
    let now_ms = crate::authbus_ingress::now_ms().expect("wall clock");
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await;
    let server = MockServer::start().await;
    let (host, signer, _) = fixture.open_effect_host(&server, &scope);
    let mut grant = signed_final_use(&intent, now_ms, &signer);
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            b"wrong-wire",
            &grant,
            "rejected",
            now_ms + 5
        )
        .await
        .is_err()
    );
    let root = fixture.identity.layout.automation_root().join(DIRECTORY);
    assert!(!root.exists());
    fs::create_dir(&root).expect("slot root");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).expect("private root");
    let corrupt = root.join("slot-00.json");
    fs::write(&corrupt, b"corrupt original").expect("corrupt slot");
    fs::set_permissions(&corrupt, fs::Permissions::from_mode(0o600)).expect("private slot");
    grant.signature[0] ^= 1;
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "invalid-grant",
            now_ms + 5
        )
        .await
        .is_err()
    );
    assert_eq!(
        fs::read(corrupt).expect("unchanged corrupt slot"),
        b"corrupt original"
    );
    assert!(
        fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("original attempt lookup")
            .is_none()
    );
    assert!(
        server
            .received_requests()
            .await
            .expect("HTTP observations")
            .is_empty()
    );
    let key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("provider key");
    Mock::given(method("POST")).and(path("/dispatch"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
            "provider_operation_id_sha256": Sha256Digest::for_bytes(b"operation").as_str(), "status": "completed",
        }))).expect(1).mount(&server).await;
    let valid = signed_final_use(&intent, now_ms, &signer);
    host.execute(
        &fixture.store,
        &intent,
        WIRE,
        &valid,
        "valid-after-retention-failure",
        now_ms + 6,
    )
    .await
    .expect("ordinary valid dispatch after retention failure");
    assert_eq!(
        fs::read(root.join("slot-00.json")).expect("unchanged corrupt slot"),
        b"corrupt original"
    );
    server.verify().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_owner_identity_deduplicates_first_fact_without_relabeling_its_time() {
    let fixture = Fixture::new().await;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    let fence = prepare_effect(&fixture, 100, &intent).await;
    assert_eq!(
        capture(&fixture.store, &intent, &fence, 105).await,
        Ok("retained_new")
    );
    let path = fixture
        .identity
        .layout
        .automation_root()
        .join(DIRECTORY)
        .join("slot-00.json");
    let bytes = fs::read(&path).expect("first observation");
    assert_eq!(
        capture(&fixture.store, &intent, &fence, 106).await,
        Ok("retained_existing")
    );
    assert_eq!(fs::read(path).expect("original observation"), bytes);
    let fact: StoredFact = serde_json::from_slice(&bytes).expect("native fact");
    assert_eq!(fact.fact["caller_time_ms"], 105);
    assert_eq!(fact.fact["claimed_step"]["event_seq"], 2);
}

#[test]
fn fixed_slots_preserve_capacity_corruption_and_linked_file_boundaries() {
    let temp = tempfile::tempdir().expect("temporary root");
    for index in 0..SLOT_COUNT {
        assert_eq!(
            retain(
                temp.path(),
                serde_json::json!({"identity": index, "caller_time_ms": 1})
            ),
            Ok("retained_new")
        );
    }
    let root = temp.path().join(DIRECTORY);
    let before = (0..SLOT_COUNT)
        .map(|i| fs::read(root.join(format!("slot-{i:02}.json"))).expect("original slot"))
        .collect::<Vec<_>>();
    assert_eq!(
        retain(temp.path(), serde_json::json!({"identity": SLOT_COUNT})),
        Ok("capacity_full")
    );
    assert_eq!(
        (0..SLOT_COUNT)
            .map(|i| fs::read(root.join(format!("slot-{i:02}.json"))).expect("same slot"))
            .collect::<Vec<_>>(),
        before
    );
    let slot = root.join("slot-00.json");
    fs::remove_file(&slot).expect("remove one fixture slot");
    let external = temp.path().join("external");
    fs::write(&external, b"external immutable bytes").expect("external fixture");
    fs::set_permissions(&external, fs::Permissions::from_mode(0o600)).expect("private external");
    for symlink in [false, true] {
        if symlink {
            std::os::unix::fs::symlink(&external, &slot).expect("fixture symlink");
        } else {
            fs::hard_link(&external, &slot).expect("fixture hard link");
        }
        assert_eq!(
            retain(temp.path(), serde_json::json!({"identity": 999})),
            Err(())
        );
        assert_eq!(
            fs::read(&external).expect("unchanged external"),
            b"external immutable bytes"
        );
        fs::remove_file(&slot).expect("remove fixture link");
    }
}

#[test]
fn pinned_directory_does_not_follow_parent_replacement() {
    let temp = tempfile::tempdir().expect("owner root");
    let external = tempfile::tempdir().expect("unrelated destination");
    let pinned = SlotRoot::open(temp.path()).expect("original pinned directory");
    let original = temp.path().join(DIRECTORY);
    let moved = temp.path().join("original-retention-root");
    fs::rename(&original, &moved).expect("move original fixture directory");
    std::os::unix::fs::symlink(external.path(), &original).expect("replace parent with symlink");
    assert_eq!(
        pinned.retain(serde_json::json!({"identity": "native"})),
        Ok("retained_new")
    );
    assert!(moved.join("slot-00.json").is_file());
    assert_eq!(
        fs::read_dir(external.path())
            .expect("unrelated destination")
            .count(),
        0
    );
    assert_eq!(
        retain(temp.path(), serde_json::json!({"identity": "another"})),
        Err(())
    );
}
