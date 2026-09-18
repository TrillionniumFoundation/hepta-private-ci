use super::*;

use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptRoleV2;
use crate::test_support::TestAuthority;
use crate::test_support::admission_request;
use crate::test_support::digest;
use crate::test_support::factor_with_id;
use crate::test_support::id;

fn binding(payload: &[u8]) -> crate::PromptRealizationBindingV2 {
    crate::PromptRealizationBindingV2 {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(payload),
        token_cost: 16,
        expires_unix_ms: None,
        predecessor_realization_id: None,
    }
}

#[test]
fn restart_reopens_factor_admission_payload_and_revocation_without_resurrection() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let authority = TestAuthority::new();
    {
        let mut store =
            DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
        store
            .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
            .expect("register factor");
        let request = admission_request("factor:1", "reviewer:1");
        let token = authority.token(store.registry(), &request, 61);
        store
            .admit_factor_authorized(&authority.authority, token, request)
            .expect("authorized durable admission");
        store
            .register_realization_v2(binding(b"durable payload"), b"durable payload".to_vec())
            .expect("durable realization");
        store
            .revoke_factor_with_reason(
                &id("factor:1"),
                &id("operator:1"),
                digest("revocation-reason"),
                500,
            )
            .expect("durable revocation");
    }

    let reopened = DurablePromptRegistry::open(directory.path()).expect("reopen store");
    let registry = reopened.registry();
    assert_eq!(
        registry.factor(&id("factor:1")).expect("factor").lifecycle,
        Lifecycle::Revoked
    );
    assert!(registry.admission(&id("factor:1")).is_some());
    assert_eq!(
        registry.realization_payload(&id("realization:1")),
        Some(&b"durable payload"[..])
    );
    assert!(
        !registry
            .realization(&id("realization:1"))
            .expect("realization")
            .active
    );
    assert!(registry.revocation_frontier() > 0);
    registry.validate_integrity().expect("reopened integrity");
}

#[test]
fn durable_admission_consumes_scope_bound_authority_before_publication() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let authority = TestAuthority::new();
    let mut store =
        DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
    store
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let request = admission_request("factor:1", "reviewer:1");
    let token = authority.token(store.registry(), &request, 62);
    let mut drifted = request;
    drifted.evidence_digest = digest("drifted-evidence");
    assert!(matches!(
        store.admit_factor_authorized(&authority.authority, token, drifted),
        Err(PromptRegistryStoreError::Authority(_))
    ));
    assert_eq!(
        store
            .registry()
            .factor(&id("factor:1"))
            .expect("factor")
            .lifecycle,
        Lifecycle::Draft
    );
    drop(store);
    let reopened = DurablePromptRegistry::open(directory.path()).expect("reopen store");
    assert_eq!(
        reopened
            .registry()
            .factor(&id("factor:1"))
            .expect("factor")
            .lifecycle,
        Lifecycle::Draft
    );
}

#[test]
fn corrupt_current_fails_closed_without_destroying_predecessor_backup() {
    let directory = tempfile::tempdir().expect("store temp dir");
    {
        let mut store =
            DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
        store
            .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
            .expect("register factor");
    }
    let current = directory.path().join(STATE_FILE);
    let backup = directory.path().join(BACKUP_FILE);
    std::fs::copy(&current, &backup).expect("preserve predecessor");
    std::fs::write(&current, b"{\"corrupt\":true}").expect("corrupt current");

    assert!(DurablePromptRegistry::open(directory.path()).is_err());
    assert!(backup.exists());
}

#[test]
fn tampered_durable_state_fails_closed_on_reopen() {
    let directory = tempfile::tempdir().expect("store temp dir");
    {
        let mut store =
            DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
        store
            .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
            .expect("register factor");
    }
    let path = directory.path().join(STATE_FILE);
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("json");
    value["registryDigest"] = serde_json::Value::String(digest("tampered").to_string());
    std::fs::write(&path, serde_json::to_vec(&value).expect("encode")).expect("tamper state");
    assert!(matches!(
        DurablePromptRegistry::open(directory.path()),
        Err(PromptRegistryStoreError::Protocol(_))
    ));
}

#[test]
fn deterministic_v0_draft_migration_rewrites_current_v1_state() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let factor_digest = digest("legacy-draft");
    let legacy = format!(
        "{{\"schema\":\"hepta.prompt-registry.durable.v0\",\"schemaVersion\":0,\"maximumRecords\":64,\"factors\":[{{\"factorId\":\"factor:legacy\",\"proposerId\":\"proposer:legacy\",\"semanticVersion\":\"v1\",\"contentDigest\":\"{factor_digest}\",\"source\":\"governed_internal\",\"lifecycle\":\"draft\"}}]}}"
    );
    std::fs::write(directory.path().join(STATE_FILE), legacy.as_bytes()).expect("write v0");
    let migrated = DurablePromptRegistry::open(directory.path()).expect("migrate v0");
    assert_eq!(
        migrated
            .registry()
            .factor(&id("factor:legacy"))
            .expect("migrated factor")
            .lifecycle,
        Lifecycle::Draft
    );
    drop(migrated);
    let bytes = std::fs::read(directory.path().join(STATE_FILE)).expect("read migrated state");
    let value: serde_json::Value = serde_json::from_slice(&bytes).expect("json");
    assert_eq!(value["schemaVersion"].as_u64(), Some(1));
    assert_eq!(value["schema"], "hepta.prompt-registry.durable.v1");
}

#[test]
fn v0_migration_rejects_capacity_above_native_bound() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let legacy = format!(
        "{{\"schema\":\"hepta.prompt-registry.durable.v0\",\"schemaVersion\":0,\"maximumRecords\":{},\"factors\":[]}}",
        u64::try_from(MAX_RECORDS).expect("max records fits").saturating_add(1)
    );
    std::fs::write(directory.path().join(STATE_FILE), legacy.as_bytes()).expect("write v0");
    assert!(matches!(
        DurablePromptRegistry::open(directory.path()),
        Err(PromptRegistryStoreError::Protocol(_))
    ));
}

#[test]
fn v0_migration_refuses_to_invent_admission_authority() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let factor_digest = digest("legacy-admitted");
    let legacy = format!(
        "{{\"schema\":\"hepta.prompt-registry.durable.v0\",\"schemaVersion\":0,\"maximumRecords\":64,\"factors\":[{{\"factorId\":\"factor:legacy\",\"proposerId\":\"proposer:legacy\",\"semanticVersion\":\"v1\",\"contentDigest\":\"{factor_digest}\",\"source\":\"governed_internal\",\"lifecycle\":\"admitted\"}}]}}"
    );
    std::fs::write(directory.path().join(STATE_FILE), legacy.as_bytes()).expect("write v0");
    assert!(matches!(
        DurablePromptRegistry::open(directory.path()),
        Err(PromptRegistryStoreError::Protocol(_))
    ));
}

#[test]
fn writer_fence_refuses_to_overwrite_a_diverged_persisted_generation() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let mut store =
        DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
    store
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");

    let mut divergent = store.registry().clone();
    divergent
        .register_factor(factor_with_id("factor:disk", FactorSource::GovernedInternal))
        .expect("advance disk generation");
    let divergent_bytes = encode_registry_state(&divergent).expect("encode divergent state");
    std::fs::write(directory.path().join(STATE_FILE), divergent_bytes).expect("replace state");

    assert_eq!(
        store.register_factor(factor_with_id(
            "factor:stale-writer",
            FactorSource::GovernedInternal,
        )),
        Err(PromptRegistryStoreError::StateDiverged)
    );
    drop(store);

    let reopened = DurablePromptRegistry::open(directory.path()).expect("reopen disk generation");
    assert!(reopened.registry().factor(&id("factor:disk")).is_some());
    assert!(
        reopened
            .registry()
            .factor(&id("factor:stale-writer"))
            .is_none()
    );
}

#[test]
fn interrupted_replacement_restores_last_durable_generation_on_reopen() {
    let directory = tempfile::tempdir().expect("store temp dir");
    {
        let mut store =
            DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create store");
        store
            .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
            .expect("register factor");
    }

    let current = directory.path().join(STATE_FILE);
    let backup = directory.path().join(BACKUP_FILE);
    let temporary = directory.path().join(TEMP_FILE);
    std::fs::rename(&current, &backup).expect("simulate current-to-backup crash window");
    std::fs::write(&temporary, b"incomplete next generation").expect("write interrupted temp");

    let reopened = DurablePromptRegistry::open(directory.path()).expect("recover predecessor");
    assert!(reopened.registry().factor(&id("factor:1")).is_some());
    assert!(current.exists());
    assert!(!backup.exists());
    assert!(!temporary.exists());
    reopened
        .registry()
        .validate_integrity()
        .expect("recovered integrity");
}

#[test]
fn durable_store_rejects_concurrent_authoritative_writer() {
    let directory = tempfile::tempdir().expect("store temp dir");
    let first =
        DurablePromptRegistry::open_or_create(directory.path(), 64).expect("create first writer");
    assert!(matches!(
        DurablePromptRegistry::open(directory.path()),
        Err(PromptRegistryStoreError::WriterBusy)
    ));
    drop(first);
    assert!(DurablePromptRegistry::open(directory.path()).is_ok());
}
