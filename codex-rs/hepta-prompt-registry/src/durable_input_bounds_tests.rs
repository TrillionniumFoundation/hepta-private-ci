//! Input shape rejection precedes migration work and final-use nonce claims.

use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn write_private(path: &Path, bytes: &[u8]) {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .must("private file");
    file.write_all(bytes).must("fixture bytes");
    file.sync_all().must("fixture durability");
}

fn legacy_factor(index: usize) -> StoredFactor {
    StoredFactor {
        factor_id: format!("factor:legacy:{index}"),
        proposer_id: "proposer:legacy".into(),
        semantic_version: "v1".into(),
        semantic_purpose: String::new(),
        authority_class: String::new(),
        eligible_objective_dimensions: Vec::new(),
        content_digest: digest("legacy factor").into_array(),
        source: 0,
        lifecycle: 0,
    }
}

fn legacy_state() -> StoredV1 {
    StoredV1 {
        schema: 1,
        revision: 2,
        lifecycle_frontier: 2,
        revocation_frontier: 0,
        maximum_records: 1,
        factors: vec![legacy_factor(0)],
        realizations: Vec::new(),
        bindings: Vec::new(),
    }
}

#[test]
fn legacy_record_capacity_precedes_decode_and_preserves_selected_bytes() {
    for excess_kind in ["factor", "realization"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&path)
            .must("owner directory");
        let mut stored = legacy_state();
        if excess_kind == "factor" {
            stored.factors.push(legacy_factor(1));
        } else {
            stored.realizations.push(StoredRealization {
                realization_id: "realization:legacy".into(),
                factor_id: "factor:legacy:0".into(),
                model_digest: digest("model").into_array(),
                tokenizer_digest: digest("tokenizer").into_array(),
                content_digest: digest("payload").into_array(),
                active: false,
            });
        }
        // If entry decoding runs before aggregate admission, this invalid first
        // identity would produce Corrupt instead of CapacityExceeded.
        stored.factors[0].factor_id = "invalid identity".into();
        let selected = serde_json::to_vec(&stored).must("legacy selected image");
        write_private(&path.join("registry.json"), &selected);
        let payload_tail = b"unselected legacy payload file";
        write_private(&path.join(payloads::FILE_NAME), payload_tail);
        assert!(
            matches!(
                DurablePromptRegistry::open_state_dir(&path, 1),
                Err(DurableRegistryError::CapacityExceeded)
            ),
            "{excess_kind}"
        );
        assert_eq!(
            std::fs::read(path.join("registry.json")).must("selected image"),
            selected
        );
        assert_eq!(
            std::fs::read(path.join(payloads::FILE_NAME)).must("unselected file"),
            payload_tail
        );
    }
}

#[test]
fn legacy_orphan_bindings_are_rejected_and_exact_capacity_remains_migratable() {
    let mut stored = legacy_state();
    stored.bindings.push(StoredBindingV1 {
        realization_id: "realization:orphan".into(),
        factor_id: "factor:legacy:0".into(),
        model_digest: digest("model").into_array(),
        tokenizer_digest: digest("tokenizer").into_array(),
        template_digest: digest("template").into_array(),
        tool_schema_digest: digest("tools").into_array(),
        locale_id: "locale:en-US".into(),
        role: 1,
        payload_digest: digest("payload").into_array(),
        token_cost: 1,
        expires_unix_ms: None,
    });
    assert!(matches!(
        migrate_v1(stored, 1),
        Err(DurableRegistryError::Corrupt)
    ));
    let migrated = migrate_v1(legacy_state(), 1).must("record count at exact capacity");
    assert_eq!(migrated.factors.len(), 1);
}

#[test]
fn payload_shape_rejection_preserves_registry_and_signed_grant_claimability() {
    for payload_size in [
        0,
        crate::MAX_REALIZATION_PAYLOAD_BYTES + 1,
        crate::MAX_REALIZATION_PAYLOAD_BYTES,
    ] {
        let temp = tempfile::tempdir().must("temp");
        let registry_path = temp.path().join("registry");
        let mut owner = DurablePromptRegistry::open_state_dir(&registry_path, 8).must("owner");
        let factor = PromptFactor {
            factor_id: id("factor:bounded"),
            proposer_id: id("proposer:bounded"),
            semantic_version: id("v1"),
            semantic_purpose: "payload admission bound".into(),
            authority_class: "registered_prompt_factor".into(),
            eligible_objective_dimensions: Vec::new(),
            content_digest: digest("factor"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        owner.register_factor(factor.clone()).must("factor");
        owner
            .commit(|registry| {
                registry.admit_factor(&factor.factor_id, &id("reviewer:bounded"), digest("review"))
            })
            .must("fixture admission");
        let admitted = owner
            .registry()
            .must("registry")
            .factor(&factor.factor_id)
            .must("factor")
            .clone();
        let actor = id("actor:bounded");
        let scope = digest("scope");
        let payload = vec![b'a'; payload_size];
        let binding = PromptRealizationBindingV2 {
            realization_id: id("realization:bounded"),
            factor_id: factor.factor_id,
            model_id: id("model:bounded"),
            model_version: "v1".into(),
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            context_profile_digest: digest("context"),
            locale_id: id("locale:en-US"),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: Digest32::of_bytes(&payload),
            token_cost: 1,
            expires_unix_ms: None,
        };
        let expected = final_use_realization_binding(&admitted, &actor, scope, &binding, None)
            .must("request binding");
        let key = SigningKey::from_bytes(&[81; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &temp.path().join("authority"),
            "security-owner:bounded".into(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .must("authority");
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .must("clock")
                .as_millis(),
        )
        .must("timestamp");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner:bounded".into(),
            authority_epoch: 7,
            grant_id: "grant:bounded".into(),
            nonce: [81; 32],
            binding: expected.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: key
                .sign(&grant.signing_bytes().must("signing bytes"))
                .to_bytes()
                .to_vec(),
            grant,
        };
        let prior_registry = owner.registry().must("registry").clone();
        let prior_manifest = std::fs::read(registry_path.join("registry.json")).must("manifest");
        let prior_payloads =
            std::fs::read(registry_path.join(payloads::FILE_NAME)).must("payload file");
        let prior_capacity = authority.capacity().must("capacity");
        let result = owner.register_realization_payload_final_use_v2(
            &authority, &signed, &actor, scope, binding, payload, None,
        );
        if payload_size == crate::MAX_REALIZATION_PAYLOAD_BYTES {
            let receipt = result.must("exact-capacity payload publication");
            assert_eq!(receipt.disposition, crate::MutationDisposition::Inserted);
            assert_eq!(
                authority.capacity().must("capacity").used_nonces,
                prior_capacity.used_nonces + 1
            );
        } else {
            assert!(
                matches!(
                    result,
                    Err(DurableRegistryError::Core(Error::PayloadTooLarge))
                ),
                "size={payload_size}"
            );
            assert_eq!(owner.registry().must("registry"), &prior_registry);
            assert_eq!(
                std::fs::read(registry_path.join("registry.json")).must("manifest"),
                prior_manifest
            );
            assert_eq!(
                std::fs::read(registry_path.join(payloads::FILE_NAME)).must("payload file"),
                prior_payloads
            );
            assert_eq!(authority.capacity().must("capacity"), prior_capacity);
            drop(
                authority
                    .claim(&signed, &expected)
                    .must("unchanged signed grant remains claimable"),
            );
        }
    }
}

#[test]
fn v3_metadata_bounds_precede_payload_access_and_preserve_recovery_inputs() {
    for fault in [
        "configuration",
        "capacity",
        "bindings",
        "events",
        "supersessions",
        "references",
        "reference-id",
    ] {
        for payload_available in [false, true] {
            let temp = tempfile::tempdir().must("temp");
            let path = temp.path().join("owner");
            let mut owner = DurablePromptRegistry::open_state_dir(&path, 8).must("owner");
            owner
                .commit(|registry| super::payload_tests::add_payload(registry, 0))
                .must("payload fixture");
            let anchor = owner.recovery_anchor().must("original cut");
            drop(owner);
            let manifest_path = path.join("registry.json");
            let mut manifest: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&manifest_path).must("original manifest"))
                    .must("manifest JSON");
            let state = manifest.get_mut("state").must("metadata");
            match fault {
                "configuration" => state["maximum_records"] = serde_json::json!(7),
                "capacity" => {
                    let factor = state["factors"][0].clone();
                    state["factors"] = serde_json::Value::Array(vec![factor; 8]);
                    state["factors"][0]["factor_id"] = serde_json::json!("invalid identity");
                }
                "bindings" => {
                    let binding = state["bindings"][0].clone();
                    state["bindings"]
                        .as_array_mut()
                        .must("bindings")
                        .push(binding);
                }
                "events" => {
                    let event = state["lifecycle_events"][0].clone();
                    state["lifecycle_events"] = serde_json::Value::Array(vec![event; 5]);
                }
                "supersessions" => {
                    state["supersessions"] = serde_json::json!([
                        {"successor_id":"realization:0", "predecessor_id":"realization:older"},
                        {"successor_id":"realization:other", "predecessor_id":"realization:oldest"}
                    ])
                }
                "references" => {
                    state["realizations"] = serde_json::json!([]);
                    state["bindings"] = serde_json::json!([]);
                }
                "reference-id" => {}
                _ => unreachable!(),
            }
            if fault == "reference-id" {
                manifest["payload_references"][0]["realization_id"] =
                    serde_json::json!("r".repeat(257));
            }
            let selected = serde_json::to_vec(&manifest).must("rejected selected image");
            std::fs::write(&manifest_path, &selected).must("replace fixture manifest");
            let payload_path = path.join(payloads::FILE_NAME);
            let saved_payloads = if payload_available {
                let mut file = std::fs::OpenOptions::new()
                    .append(true)
                    .open(&payload_path)
                    .must("payload file");
                file.write_all(b"unselected tail must survive rejection")
                    .must("orphan tail");
                file.sync_all().must("orphan durability");
                Some(std::fs::read(&payload_path).must("preserved payload bytes"))
            } else {
                std::fs::remove_file(&payload_path).must("missing payload fixture");
                None
            };
            let ordinary = DurablePromptRegistry::open_state_dir(&path, 8);
            let anchored =
                DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 8, &anchor);
            for result in [ordinary, anchored] {
                let expected = match fault {
                    "configuration" => {
                        matches!(result, Err(DurableRegistryError::ConfigurationMismatch))
                    }
                    "capacity" => matches!(result, Err(DurableRegistryError::CapacityExceeded)),
                    "bindings" | "events" | "supersessions" | "references" | "reference-id" => {
                        matches!(result, Err(DurableRegistryError::Corrupt))
                    }
                    _ => unreachable!(),
                };
                assert!(expected, "{fault}, payload_available={payload_available}");
            }
            assert_eq!(
                std::fs::read(&manifest_path).must("selected image"),
                selected
            );
            if let Some(saved) = saved_payloads {
                assert_eq!(std::fs::read(&payload_path).must("payload bytes"), saved);
            } else {
                assert!(!payload_path.exists());
            }
        }
    }
}
