//! Native admission reserves unresolved migration placeholders without altering recovery.

use std::collections::BTreeSet;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::*;

fn id(value: &str) -> StableId {
    StableId::new(value).must("identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor() -> PromptFactor {
    PromptFactor {
        factor_id: id("factor:reserved"),
        proposer_id: id("proposer:reserved"),
        semantic_version: id("v1"),
        semantic_purpose: "native authoritative protocol export".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: Vec::new(),
        content_digest: digest("factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

#[test]
fn native_factor_placeholder_rejection_preserves_selected_files_and_protocol_export() {
    let temporary = tempfile::tempdir().must("temporary");
    let path = temporary.path().join("registry");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4).must("owner");
    let prior = owner.registry().must("registry").clone();
    let manifest = std::fs::read(path.join("registry.json")).must("manifest");
    let payloads = std::fs::read(path.join("registry.payloads")).must("payloads");
    let mut invalid = factor();
    invalid.semantic_purpose = protocol::LEGACY_UNRESOLVED_FACTOR_PURPOSE.into();
    assert!(matches!(
        owner.register_factor(invalid),
        Err(DurableRegistryError::Core(Error::InvalidFactorMetadata))
    ));
    assert_eq!(owner.registry().must("unchanged registry"), &prior);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        manifest
    );
    assert_eq!(
        std::fs::read(path.join("registry.payloads")).must("payloads"),
        payloads
    );
    drop(owner);
    let mut owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4)
        .must("reopen rejection");
    assert_eq!(owner.registry().must("registry"), &prior);
    owner.register_factor(factor()).must("valid same identity");
    let projected = owner
        .registry()
        .must("registry")
        .factor_protocol_v1(&factor().factor_id)
        .must("projection")
        .must("factor");
    assert_eq!(
        PromptFactorV1::decode_canonical_json(&projected.encode_canonical_json().must("encode"))
            .must("decode"),
        projected
    );
    drop(owner);
    let owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4)
        .must("reopen valid factor");
    assert_eq!(
        owner
            .registry()
            .must("registry")
            .factor_protocol_v1(&factor().factor_id),
        Ok(Some(projected))
    );
}

#[test]
fn native_model_placeholder_rejection_preserves_signed_grant_and_valid_protocol_export() {
    let temporary = tempfile::tempdir().must("temporary");
    let path = temporary.path().join("registry");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4).must("owner");
    owner.register_factor(factor()).must("factor");
    let key = SigningKey::from_bytes(&[93; 32]);
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .must("clock")
            .as_millis(),
    )
    .must("timestamp");
    let scope = digest("scope");
    let review = AdmissionGrantV1 {
        schema_version: 1,
        signer_id: "review-owner".into(),
        grant_id: "review:reserved".into(),
        binding: AdmissionBindingV1 {
            factor_id: factor().factor_id.to_string(),
            factor_content_sha256: factor().content_digest.into_array(),
            reviewer_id: "reviewer:reserved".into(),
            reviewed_scope_sha256: scope.into_array(),
            evidence_sha256: digest("review").into_array(),
        },
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed_review = SignedAdmissionGrantV1 {
        signature: key
            .sign(&review.signing_bytes().must("review bytes"))
            .to_bytes()
            .to_vec(),
        grant: review,
    };
    let review_authority =
        AdmissionAuthority::new(id("review-owner"), key.verifying_key().to_bytes())
            .must("review authority");
    let verified = review_authority
        .verify(&signed_review, &factor(), scope, now)
        .must("review");
    owner
        .admit_factor_verified(verified, now)
        .must("fixture admission");
    let admitted = owner
        .registry()
        .must("registry")
        .factor(&factor().factor_id)
        .must("factor")
        .clone();
    let actor = id("actor:reserved");
    let payload = b"native realization bytes".to_vec();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:reserved"),
        factor_id: factor().factor_id,
        model_id: id("model:ordinary"),
        model_version: "v1".into(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 4,
        expires_unix_ms: None,
    };
    let expected = final_use_realization_binding(
        &admitted, &actor, scope, &binding, /*supersedes_realization_id*/ None,
    )
    .must("binding");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        &temporary.path().join("authority"),
        "mutation-owner".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .must("authority");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "mutation-owner".into(),
        authority_epoch: 7,
        grant_id: "grant:reserved".into(),
        nonce: [93; 32],
        binding: expected,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = codex_hepta_contracts::SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().must("grant bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let mut invalid = binding.clone();
    invalid.model_id = id(protocol::LEGACY_UNRESOLVED_MODEL_ID);
    invalid.model_version = protocol::LEGACY_UNRESOLVED_MODEL_VERSION.into();
    assert_eq!(
        final_use_realization_binding(
            &admitted, &actor, scope, &invalid, /*supersedes_realization_id*/ None
        ),
        Err(AdmissionError::InvalidGrant)
    );
    let prior = owner.registry().must("registry").clone();
    let capacity = authority.capacity().must("capacity");
    let manifest = std::fs::read(path.join("registry.json")).must("manifest");
    let payloads = std::fs::read(path.join("registry.payloads")).must("payloads");
    let mut core = prior.clone();
    assert_eq!(
        core.register_realization_v2(invalid.clone()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        core.register_realization_payload_v2(
            invalid.clone(),
            payload.clone(),
            /*supersedes_realization_id*/ None
        ),
        Err(Error::InvalidTransition)
    );
    assert_eq!(core, prior);
    for (index, (model_id, model_version)) in [
        (protocol::LEGACY_UNRESOLVED_MODEL_ID, "native-v1"),
        ("model:native", protocol::LEGACY_UNRESOLVED_MODEL_VERSION),
    ]
    .into_iter()
    .enumerate()
    {
        let mut partial_marker = binding.clone();
        partial_marker.realization_id = id(&format!("realization:partial-marker:{index}"));
        partial_marker.model_id = id(model_id);
        partial_marker.model_version = model_version.into();
        final_use_realization_binding(
            &admitted,
            &actor,
            scope,
            &partial_marker,
            /*supersedes_realization_id*/ None,
        )
        .must("a single marker component is not the reserved tuple");
        core.register_realization_payload_v2(
            partial_marker.clone(),
            payload.clone(),
            /*supersedes_realization_id*/ None,
        )
        .must("native publication with one marker component");
        let projected = core
            .realization_protocol_v1(&partial_marker.realization_id)
            .must("partial-marker projection")
            .must("realization");
        assert_eq!(
            PromptRealizationV1::decode_canonical_json(
                &projected.encode_canonical_json().must("encode")
            )
            .must("decode"),
            projected
        );
    }
    assert!(matches!(
        owner.register_realization_payload_final_use_v2(
            &authority,
            &signed,
            &actor,
            scope,
            invalid,
            payload.clone(),
            /*supersedes_realization_id*/ None,
        ),
        Err(DurableRegistryError::Admission(
            AdmissionError::InvalidGrant
        ))
    ));
    assert_eq!(owner.registry().must("registry"), &prior);
    assert_eq!(authority.capacity().must("capacity"), capacity);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        manifest
    );
    assert_eq!(
        std::fs::read(path.join("registry.payloads")).must("payloads"),
        payloads
    );
    owner
        .register_realization_payload_final_use_v2(
            &authority,
            &signed,
            &actor,
            scope,
            binding.clone(),
            payload,
            /*supersedes_realization_id*/ None,
        )
        .must("same signed grant remains usable for its valid request");
    let projected = owner
        .registry()
        .must("registry")
        .realization_protocol_v1(&binding.realization_id)
        .must("projection")
        .must("realization");
    assert_eq!(
        PromptRealizationV1::decode_canonical_json(
            &projected.encode_canonical_json().must("encode")
        )
        .must("decode"),
        projected
    );
    drop(owner);
    let owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4)
        .must("reopen realization");
    assert_eq!(
        owner
            .registry()
            .must("registry")
            .realization_protocol_v1(&binding.realization_id),
        Ok(Some(projected))
    );
}

#[test]
fn native_placeholder_reservation_preserves_v1_and_v2_legacy_restore() {
    for schema in [1, 2] {
        let temporary = tempfile::tempdir().must("temporary");
        let path = temporary.path().join("registry");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&path)
            .must("directory");
        let mut core = PromptRegistry::new(/*maximum_records*/ 4).must("core");
        core.register_factor(factor()).must("native event fixture");
        core.factors
            .get_mut(&factor().factor_id)
            .must("factor")
            .semantic_purpose = protocol::LEGACY_UNRESOLVED_FACTOR_PURPOSE.into();
        let event = &core.lifecycle_events[0];
        let mut stored = serde_json::json!({
            "schema": schema, "revision": 2, "lifecycle_frontier": 2, "revocation_frontier": 0,
            "maximum_records": 4, "factors": [{
                "factor_id": factor().factor_id.as_str(), "proposer_id": factor().proposer_id.as_str(),
                "semantic_version": "v1", "content_digest": factor().content_digest.into_array(),
                "source": 0, "lifecycle": 0
            }], "realizations": [], "bindings": []
        });
        if schema == 2 {
            stored["registry_digest"] = serde_json::json!(core.snapshot_digest().into_array());
            stored["payloads"] = serde_json::json!([]);
            stored["supersessions"] = serde_json::json!([]);
            stored["lifecycle_events"] = serde_json::json!([{
                "revision": 2, "factor_id": event.factor_id.as_str(), "kind": 0,
                "from": null, "to": 0, "actor_id": event.actor_id.as_str(), "admission_grant_id": null,
                "evidence_digest": event.evidence_digest.into_array(), "scope_digest": null,
                "reason_digest": null, "cutoff_unix_ms": null, "event_digest": event.event_digest.into_array()
            }]);
        }
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path.join("registry.json"))
            .must("private legacy selected state");
        file.write_all(&serde_json::to_vec(&stored).must("legacy bytes"))
            .must("write");
        file.sync_all().must("sync");
        drop(file);
        let owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4)
            .must("legacy migration");
        assert_eq!(
            owner
                .registry()
                .must("registry")
                .factor_protocol_v1(&factor().factor_id),
            Err(ProtocolCodecError::MissingAuthoritativeLineage)
        );
        let migrated = owner.registry().must("registry").clone();
        drop(owner);
        let owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 4)
            .must("reopen migrated selected state");
        assert_eq!(owner.registry().must("registry"), &migrated);
    }
}
