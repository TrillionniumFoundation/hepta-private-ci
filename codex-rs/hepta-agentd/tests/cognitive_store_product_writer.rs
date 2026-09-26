#![allow(clippy::expect_used)]
#![cfg(unix)]

use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::CognitiveScope;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::LedgerSourceKind;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryLifecycleState;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::MemoryVerification;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityUseGuard;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_cognitive_store::bind_canonical_event_to_durable_receipt;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

#[derive(Default)]
struct ProductAuthorityState {
    revoked: bool,
    active_uses: usize,
}

#[derive(Clone)]
struct ProductAuthorityVerifier {
    state: Arc<(Mutex<ProductAuthorityState>, Condvar)>,
    grant_digest: Sha256Digest,
}

struct ProductAuthorityUse {
    state: Arc<(Mutex<ProductAuthorityState>, Condvar)>,
}

impl Drop for ProductAuthorityUse {
    fn drop(&mut self) {
        let (lock, changed) = &*self.state;
        let mut state = lock.lock().expect("product authority state");
        state.active_uses = state
            .active_uses
            .checked_sub(1)
            .expect("product authority use count is positive");
        changed.notify_all();
    }
}

impl ProductAuthorityVerifier {
    fn new(grant_digest: Sha256Digest) -> Self {
        Self {
            state: Arc::new((Mutex::new(ProductAuthorityState::default()), Condvar::new())),
            grant_digest,
        }
    }

    fn revoke_and_wait(&self) {
        let (lock, changed) = &*self.state;
        let mut state = lock.lock().expect("product authority state");
        state.revoked = true;
        while state.active_uses != 0 {
            state = changed
                .wait(state)
                .expect("product authority state after wait");
        }
    }

    fn reactivate_for_terminal_release(&self) {
        let mut state = self.state.0.lock().expect("product authority state");
        assert_eq!(state.active_uses, 0);
        state.revoked = false;
    }

    fn check(
        &self,
        lease: &ProductionAuthorityLease,
        expected_owner: &AgentId,
    ) -> Result<(), String> {
        let state = self
            .state
            .0
            .lock()
            .map_err(|_| "product authority state poisoned".to_string())?;
        if state.revoked {
            return Err("production authority revoked".to_string());
        }
        if lease.agent_id != *expected_owner {
            return Err("authority owner mismatch".to_string());
        }
        if lease.grant_digest != self.grant_digest {
            return Err("unexpected recovery grant digest".to_string());
        }
        Ok(())
    }
}

impl ProductionAuthorityVerifier for ProductAuthorityVerifier {
    fn verify(
        &self,
        lease: &ProductionAuthorityLease,
        expected_owner: &AgentId,
    ) -> Result<(), String> {
        self.check(lease, expected_owner)
    }

    fn enter_use(
        &self,
        lease: &ProductionAuthorityLease,
        expected_owner: &AgentId,
    ) -> Result<ProductionAuthorityUseGuard, String> {
        let mut state = self
            .state
            .0
            .lock()
            .map_err(|_| "product authority state poisoned".to_string())?;
        if state.revoked {
            return Err("production authority revoked".to_string());
        }
        if lease.agent_id != *expected_owner {
            return Err("authority owner mismatch".to_string());
        }
        if lease.grant_digest != self.grant_digest {
            return Err("unexpected recovery grant digest".to_string());
        }
        state.active_uses = state.active_uses.saturating_add(1);
        drop(state);
        Ok(ProductionAuthorityUseGuard::from_verified_use(
            ProductAuthorityUse {
                state: Arc::clone(&self.state),
            },
        ))
    }
}

#[tokio::test]
#[cfg(feature = "qualification-cognitive-write")]
async fn agentd_product_host_commits_through_canonical_cognitive_store()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let fleet = HeptaFleetRoot::parse(fleet_root)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c058")?;
    let layout = fleet.layout().agent(&owner);
    let store = DurableCognitiveStore::open(&layout).await?;
    let before = store.recovery_anchor().await?;

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"agentd-product-writer-test-grant"),
        7,
        11,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(
            b"agentd-product-writer-test-fence".to_vec(),
        )?,
    )?;
    let verifier = |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
        if lease.agent_id != *expected {
            return Err("authority owner mismatch".to_string());
        }
        if lease.grant_digest != Sha256Digest::for_bytes(b"agentd-product-writer-test-grant") {
            return Err("unexpected grant digest".to_string());
        }
        Ok(())
    };

    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "agentd-product-writer-test",
        1,
    )
    .await?;
    let queued = host
        .writer()
        .admit(
            "occurrence:product-writer:1",
            "cognitive.product.test",
            r#"{"kind":"memory-write"}"#,
        )
        .await?;
    assert_eq!(queued.owner_agent_id, owner);
    assert!(!queued.replayed);
    assert!(!queued.external_effect);

    let after = host.writer().recovery_anchor().await?;
    assert_ne!(after, before);
    host.writer().release().await?;
    drop(host);

    let reopened = DurableCognitiveStore::open(&layout).await?;
    let reopened_anchor = reopened.recovery_anchor().await?;
    assert_ne!(reopened_anchor, before);
    Ok(())
}

#[tokio::test]
async fn agentd_product_host_recovers_exact_cut_into_fenced_writer_generation()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c059")?;
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root)?;
    let manifest = AgentManifest::new(owner.clone(), binding, ResourceBudget::local_default())?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;

    let config = AgentdConfig::load(
        fleet_path,
        owner.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;

    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let expected = store.recovery_anchor().await?;
    drop(store);

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"agentd-product-recovery-test-grant"),
        13,
        17,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(
            b"agentd-product-recovery-test-fence".to_vec(),
        )?,
    )?;
    let verifier_impl = Arc::new(ProductAuthorityVerifier::new(Sha256Digest::for_bytes(
        b"agentd-product-recovery-test-grant",
    )));
    let verifier: Arc<dyn ProductionAuthorityVerifier> = verifier_impl.clone();

    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
        authority,
        Arc::clone(&verifier),
        "agentd-product-recovery-test",
        1,
    )
    .await?;
    let recovered_anchor = host.writer().recovery_anchor().await?;
    assert_eq!(recovered_anchor, expected);

    let now = i64::try_from(now_unix_seconds()?)?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let content = "Production semantic memory survives recovery.";
    let source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:1".to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let draft = MemoryDraft {
        stable_key: "product-recovery-semantic-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope: scope.clone(),
            content: content.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    let written = host
        .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
        .await?;
    written.validate()?;
    assert_eq!(written.write.memory.id.revision, 1);
    assert_eq!(written.write.source.revision, 1);
    assert!(!written.provenance_event_id.is_empty());
    assert!(!written.provenance_outbox_id.is_empty());
    assert!(!written.provenance_commit_event_id.is_empty());

    let canonical_event = MemoryEventV1 {
        event_id: ContractIdV1::new("event:production-semantic-write:1")?,
        episode_id: ContractIdV1::new("episode:production-semantic-write")?,
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: ContractIdV1::new(owner.as_str())?,
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: u64::try_from(now)?.saturating_mul(1000),
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: ContractIdV1::new("span:production-semantic-write:1")?,
            modality: ModalityKindV1::Text,
            asset_sha256: ContractDigestV1::parse(
                Sha256Digest::for_bytes(content.as_bytes()).as_str(),
            )?,
            range: SpanRangeV1::ByteRange {
                start: 0,
                end: u64::try_from(content.len())?,
            },
            preprocessor_manifest_sha256: ContractDigestV1::parse(
                Sha256Digest::for_bytes(b"production-semantic-preprocessor").as_str(),
            )?,
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["production-memory".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: ContractIdV1::new(written.write.source.source_id.as_str())?,
            source_revision: written.write.source.revision,
            source_sha256: ContractDigestV1::parse(written.source_content_sha256.as_str())?,
            observed_at_unix_ms: u64::try_from(written.source_observed_at_unix_seconds)?
                .saturating_mul(1000),
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: ContractDigestV1::parse(
            Sha256Digest::for_bytes(b"production-objective").as_str(),
        )?,
        ndu_state_digest: ContractDigestV1::parse(
            Sha256Digest::for_bytes(b"production-ndu").as_str(),
        )?,
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    };
    let canonical_binding = bind_canonical_event_to_durable_receipt(&canonical_event, &written)?;
    canonical_binding.validate()?;
    assert_eq!(
        canonical_binding.source_revision, written.write.source.revision,
        "canonical/durable bridge must carry the authoritative source revision"
    );

    let written_occurrence = format!("cognitive-mutation:{}", written.operation_digest.as_str());
    assert_eq!(
        host.writer().status(&written_occurrence).await?,
        LocalOutcomeState::Committed
    );

    let cut_before_invalid = host.writer().recovery_anchor().await?;
    let invalid_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:invalid".to_string(),
        content: b"invalid semantic mutation".to_vec(),
        observed_at_unix_seconds: now,
    };
    let invalid_draft = MemoryDraft {
        stable_key: "product-recovery-invalid-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope: scope.clone(),
            content: "invalid semantic mutation".to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Tombstoned {
                reason: "invalid semantic mutation".to_string(),
            },
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    assert!(
        host.remember_with_kg(
            &access,
            &invalid_source,
            &invalid_draft,
            &KgFactSetDraft::default(),
        )
        .await
        .is_err()
    );
    assert_eq!(
        host.writer().recovery_anchor().await?,
        cut_before_invalid,
        "failed semantic mutation must roll back its provenance admission/outbox"
    );

    let corrected_content = "Production semantic memory remains current after correction.";
    let correction_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:2".to_string(),
        content: corrected_content.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let correction = MemoryRevisionDraft {
        scope: scope.clone(),
        content: corrected_content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: now,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    };
    let corrected = host
        .correct_with_kg(
            &access,
            &written.write.memory.id.memory_id,
            1,
            &correction_source,
            &correction,
            &KgFactSetDraft::default(),
        )
        .await?;
    corrected.validate()?;
    assert_eq!(corrected.write.memory.id.revision, 2);

    let forget_reason = "Production semantic memory is explicitly forgotten.";
    let forget_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:3".to_string(),
        content: forget_reason.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let forget = ForgetMemoryDraft {
        scope: scope.clone(),
        reason: forget_reason.to_string(),
        valid_from_unix_seconds: now,
        citations: Vec::new(),
    };
    let forgotten = host
        .forget_with_kg(
            &access,
            &written.write.memory.id.memory_id,
            2,
            &forget_source,
            &forget,
        )
        .await?;
    forgotten.validate()?;
    assert_eq!(forgotten.write.memory.id.revision, 3);
    assert!(matches!(
        forgotten.write.memory.lifecycle,
        MemoryLifecycleState::Tombstoned { .. }
    ));

    let cut_before_revoked_write = host.writer().recovery_anchor().await?;
    verifier_impl.revoke_and_wait();
    let revoked_content = "This write must be rejected after live revocation.";
    let revoked_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:revoked".to_string(),
        content: revoked_content.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let revoked_draft = MemoryDraft {
        stable_key: "product-recovery-revoked-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope,
            content: revoked_content.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    assert!(
        host.remember_with_kg(
            &access,
            &revoked_source,
            &revoked_draft,
            &KgFactSetDraft::default(),
        )
        .await
        .is_err()
    );
    assert_eq!(
        host.writer().recovery_anchor().await?,
        cut_before_revoked_write,
        "revoked authority must not advance the cognitive owner cut"
    );
    verifier_impl.reactivate_for_terminal_release();
    host.writer().release().await?;
    drop(host);

    let reopened = DurableCognitiveStore::open(&config.identity().layout).await?;
    let post_recovery_anchor = reopened.recovery_anchor().await?;
    assert_ne!(post_recovery_anchor, expected);
    Ok(())
}

fn now_unix_seconds() -> Result<u64, std::time::SystemTimeError> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
