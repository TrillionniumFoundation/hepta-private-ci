#![allow(clippy::expect_used)]

use super::*;
use std::sync::atomic::Ordering;

#[path = "inspection_test_support.rs"]
mod support;
use support::*;

#[tokio::test]
async fn inspection_original_owner_accepts_fresh_cache_without_catalog_fetch_or_cache_write() {
    let temp = tempfile::tempdir().expect("owned cache");
    let (manager, endpoint) = cached_manager(temp.path(), cache_entry());
    let before_file = std::fs::read(temp.path().join("models_cache.json")).expect("cache before");
    let observed = observe_catalog(
        &manager,
        MODEL,
        &ModelsManagerConfig::default(),
        http_factory(),
    )
    .await;
    assert!(!observed.model.used_fallback_model_metadata);
    assert!(observed.model.use_responses_lite);
    assert_eq!(
        observed.model.default_reasoning_level,
        Some(codex_protocol::openai_models::ReasoningEffort::Max)
    );
    assert_ne!(observed.before, observed.active);
    assert_eq!(endpoint.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        std::fs::read(temp.path().join("models_cache.json")).expect("cache after"),
        before_file
    );
    let report =
        snapshot::build(&settings(false), &observed, None, None).expect("whitelisted snapshot");
    assert_eq!(report["catalog"]["source"], "provider_owner_offline");
    assert!(
        report["catalog"]["cache_hit"].is_null(),
        "the public owner does not expose hit status"
    );
    assert_eq!(report["model_metadata"]["use_responses_lite"], true);
    assert!(
        report["model_metadata"]["configured_tier_accepted_by_original_model_method"].is_null()
    );
    let encoded = report.to_string();
    for hidden in [
        PRIVATE,
        "SECRET_CREDENTIAL",
        "SECRET_PROMPT",
        "instructions_template",
        "etag",
        "display_name",
    ] {
        assert!(!encoded.contains(hidden));
    }
}

#[tokio::test]
async fn inspection_original_owner_rejects_stale_or_wrong_version_cache_without_fetch() {
    for stale in [false, true] {
        let temp = tempfile::tempdir().expect("owned cache");
        let mut entry = cache_entry();
        if stale {
            entry.fetched_at -= chrono::Duration::days(1);
        } else {
            entry.client_version = Some("ineligible-fixture-version".into());
        }
        let (manager, endpoint) = cached_manager(temp.path(), entry);
        let observed = observe_catalog(
            &manager,
            MODEL,
            &ModelsManagerConfig::default(),
            http_factory(),
        )
        .await;
        assert!(observed.model.used_fallback_model_metadata);
        assert_eq!(observed.before, observed.active);
        assert_eq!(endpoint.calls.load(Ordering::SeqCst), 0);
        let report =
            snapshot::build(&settings(false), &observed, None, None).expect("fallback snapshot");
        assert_eq!(
            report["model_metadata"]["used_fallback_model_metadata"],
            true
        );
        assert_eq!(
            report["catalog"]["cache_eligibility"],
            "enforced_by_original_owner_result_not_exposed"
        );
        assert!(
            report["catalog"]["cache_rejection_reason"].is_null(),
            "do not infer a reason from unchanged catalogs"
        );
    }
}

#[tokio::test]
async fn inspection_static_owner_and_equivalent_cache_do_not_claim_cache_miss() {
    let manager = static_manager(metadata());
    let config = ModelsManagerConfig {
        model_context_window: Some(128),
        ..Default::default()
    };
    let observed = observe_catalog(&manager, MODEL, &config, http_factory()).await;
    assert_eq!(
        observed.model.context_window,
        Some(128),
        "original model override method is used"
    );
    let report = snapshot::build(&settings(true), &observed, None, None).expect("static snapshot");
    assert_eq!(report["catalog"]["source"], "configured_static");
    assert_eq!(report["catalog"]["cache_may_apply"], false);
    assert_eq!(report["catalog"]["values_changed_from_initial"], false);

    let temp = tempfile::tempdir().expect("owned equivalent cache");
    let mut entry = cache_entry();
    entry.models = codex_models_manager::bundled_models_response()
        .expect("bundled catalog")
        .models;
    let selected = entry.models[0].slug.clone();
    let (manager, endpoint) = cached_manager(temp.path(), entry);
    let equivalent = observe_catalog(
        &manager,
        &selected,
        &ModelsManagerConfig::default(),
        http_factory(),
    )
    .await;
    assert_eq!(equivalent.before, equivalent.active);
    assert!(!equivalent.model.used_fallback_model_metadata);
    let mut selected_settings = settings(false);
    selected_settings.model = selected;
    let report =
        snapshot::build(&selected_settings, &equivalent, None, None).expect("equivalent snapshot");
    assert!(report["catalog"]["cache_hit"].is_null());
    assert_eq!(endpoint.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn inspection_snapshot_refuses_resolved_model_identity_drift() {
    let manager = static_manager(metadata());
    let mut observed = observe_catalog(
        &manager,
        MODEL,
        &ModelsManagerConfig::default(),
        http_factory(),
    )
    .await;
    observed.model.slug = "different-model".into();
    assert_eq!(
        snapshot::build(&settings(true), &observed, None, None),
        Err(InspectionFailure::ModelMismatch)
    );
}

#[tokio::test]
async fn inspection_setup_timeout_and_private_owner_error_use_static_codes() {
    let timed = bounded(
        Duration::from_millis(10),
        InspectionFailure::AuthTimeout,
        InspectionFailure::AuthUnavailable,
        std::future::pending::<std::result::Result<(), &str>>(),
    )
    .await;
    assert_eq!(timed, Err(InspectionFailure::AuthTimeout));
    let failed = bounded(
        Duration::from_secs(1),
        InspectionFailure::AuthTimeout,
        InspectionFailure::AuthUnavailable,
        async { Err::<(), _>(PRIVATE) },
    )
    .await;
    assert_eq!(failed, Err(InspectionFailure::AuthUnavailable));
    assert_eq!(
        failed.expect_err("owner failure").code(),
        "inspection_auth_owner_unavailable"
    );
}

#[tokio::test]
async fn inspection_existing_evidence_directory_refuses_before_owner_bootstrap() {
    let temp = tempfile::tempdir().expect("already existing evidence directory");
    let args = InspectionArgs {
        evidence_dir: temp.path().to_path_buf(),
        expected_model: MODEL.into(),
        setup_seconds: 1,
    };
    let error = run(&args)
        .await
        .expect_err("existing path must block before configuration/auth");
    assert_eq!(
        error.to_string(),
        "qualification evidence directory must be new"
    );
    assert_eq!(
        std::fs::read_dir(temp.path())
            .expect("owned directory read")
            .count(),
        0
    );
}
