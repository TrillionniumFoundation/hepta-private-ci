#![cfg(unix)]

use codex_hepta_agentd::AgentdError;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Connection;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::TypeInfo;
use sqlx::ValueRef;
use sqlx::sqlite::SqliteConnectOptions;
use std::collections::BTreeMap;
use std::path::Path;

use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
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
    let (_temp, config, owner) = recovery_fixture()?;

    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let expected = store.recovery_anchor().await?;
    let original_path = store.path().to_path_buf();
    let before_writer = logical_snapshot(&original_path).await?;
    store.close().await;

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
    let authority_live = Arc::new(AtomicBool::new(true));
    let authority_live_for_verifier = Arc::clone(&authority_live);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected_owner: &AgentId| -> Result<(), String> {
            if !authority_live_for_verifier.load(Ordering::SeqCst) {
                return Err("production authority revoked".to_string());
            }
            if lease.agent_id != *expected_owner {
                return Err("authority owner mismatch".to_string());
            }
            if lease.grant_digest != Sha256Digest::for_bytes(b"agentd-product-recovery-test-grant")
            {
                return Err("unexpected recovery grant digest".to_string());
            }
            Ok(())
        },
    );

    let mut tampered = expected.clone();
    tampered.state_digest = Sha256Digest::for_bytes(b"tampered exact-cut witness");
    let rejected = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&tampered),
        authority.clone(),
        Arc::clone(&verifier),
        "agentd-product-recovery-test",
        1,
    )
    .await;
    let Err(AgentdError::Protocol(message)) = rejected else {
        return Err("tampered cut did not fail at recovery admission".into());
    };
    assert_eq!(
        message,
        "recover production cognitive store: cognitive recovery access denied: recovery candidate differs from independently retained current cut"
    );
    assert_eq!(logical_snapshot(&original_path).await?, before_writer);
    let writer_fence = authority.fencing_token_digest()?;
    let writer_expiry = i64::try_from(authority.lease_expires_at_unix_seconds)?;
    let acquisition_started = i64::try_from(now_unix_seconds()?)?;

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
    // Exact recovery precedes writer acquisition. The new append-only lease
    // is an intentional owner mutation and must be bound by the new cut.
    assert_eq!(recovered_anchor.profile, expected.profile);
    assert_eq!(recovered_anchor.owner_agent_id, expected.owner_agent_id);
    assert_eq!(recovered_anchor.schema_digest, expected.schema_digest);
    assert_ne!(recovered_anchor.state_digest, expected.state_digest);
    let mut after_writer = logical_snapshot(host.writer().database_path()).await?;
    let mut preserved = before_writer.clone();
    let empty_lease = preserved
        .remove("cognitive_local_leases")
        .ok_or("missing lease table")?;
    let acquired = after_writer
        .remove("cognitive_local_leases")
        .ok_or("missing acquired lease")?;
    assert!(empty_lease.rows.is_empty());
    assert_eq!(acquired.columns, empty_lease.columns);
    assert_eq!(
        after_writer, preserved,
        "writer acquisition changed non-lease logical state"
    );
    assert_eq!(acquired.rows.len(), 1);
    let mut lease: BTreeMap<_, _> = acquired
        .columns
        .into_iter()
        .zip(acquired.rows[0].clone())
        .collect();
    let recorded = lease
        .remove("recorded_at_unix_seconds")
        .ok_or("missing lease timestamp")?;
    let LogicalValue::Integer(recorded) = recorded else {
        return Err("invalid lease timestamp type".into());
    };
    assert!((acquisition_started..=i64::try_from(now_unix_seconds()?)?).contains(&recorded));
    let chain_digest = lease.remove("lease_sha256").ok_or("missing lease digest")?;
    let LogicalValue::Text(chain_digest) = chain_digest else {
        return Err("invalid lease digest type".into());
    };
    let genesis = Sha256Digest::for_bytes(b"hepta-memory:local-lease:genesis:v1");
    let mut lease_hasher = Sha256::new();
    for part in [
        b"hepta-memory:local-lease:v2".as_slice(),
        b"agentd-product-recovery-test".as_slice(),
        &1_u64.to_be_bytes(),
        owner.as_str().as_bytes(),
        &1_u64.to_be_bytes(),
        writer_fence.as_str().as_bytes(),
        b"active".as_slice(),
        &13_u64.to_be_bytes(),
        &17_u64.to_be_bytes(),
        &u64::try_from(writer_expiry)?.to_be_bytes(),
        genesis.as_str().as_bytes(),
    ] {
        lease_hasher.update(u64::try_from(part.len())?.to_be_bytes());
        lease_hasher.update(part);
    }
    assert_eq!(
        chain_digest,
        Sha256Digest::from_sha256_output(lease_hasher.finalize()).as_str()
    );
    assert_eq!(
        lease,
        BTreeMap::from([
            (
                "lease_id".to_string(),
                LogicalValue::Text("agentd-product-recovery-test".to_string())
            ),
            ("lease_sequence".to_string(), LogicalValue::Integer(1)),
            (
                "owner_agent_id".to_string(),
                LogicalValue::Text(owner.as_str().to_string())
            ),
            ("generation".to_string(), LogicalValue::Integer(1)),
            (
                "fencing_token".to_string(),
                LogicalValue::Text(writer_fence.as_str().to_string())
            ),
            (
                "state".to_string(),
                LogicalValue::Text("active".to_string())
            ),
            ("authority_epoch".to_string(), LogicalValue::Integer(13)),
            ("owner_epoch".to_string(), LogicalValue::Integer(17)),
            (
                "lease_expires_at_unix_seconds".to_string(),
                LogicalValue::Integer(writer_expiry)
            ),
            (
                "previous_sha256".to_string(),
                LogicalValue::Text(
                    Sha256Digest::for_bytes(b"hepta-memory:local-lease:genesis:v1")
                        .as_str()
                        .to_string()
                )
            ),
        ])
    );
    // The predecessor remains untouched; only the activated generation owns
    // the new lease. No physical-page comparison is used as a logical witness.
    assert_eq!(logical_snapshot(&original_path).await?, before_writer);

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
    authority_live.store(false, Ordering::SeqCst);
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
    authority_live.store(true, Ordering::SeqCst);
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

// Compare typed logical values, not database pages, WAL layout or FTS shadows.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum LogicalValue {
    Null,
    Integer(i64),
    Real(u64),
    Text(String),
    Blob(Vec<u8>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LogicalTable {
    columns: Vec<String>,
    rows: Vec<Vec<LogicalValue>>,
}

async fn logical_snapshot(path: &Path) -> Result<BTreeMap<String, LogicalTable>, Box<dyn Error>> {
    let options = SqliteConnectOptions::new().filename(path).read_only(true);
    let mut connection = SqliteConnection::connect_with(&options).await?;
    sqlx::query("BEGIN").execute(&mut connection).await?;
    let mut tables: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list WHERE schema = 'main' AND type IN ('table', 'virtual') AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetch_all(&mut connection).await?;
    // The logical FTS rows remain included; only their derived shadow pages
    // are excluded by pragma_table_list's type filter.
    for logical_fts in ["memory_fts", "kg_entity_fts", "kg_revision_entity_fts"] {
        assert!(tables.iter().any(|table| table == logical_fts));
    }
    tables.push("sqlite_schema".to_string());
    let mut snapshot = BTreeMap::new();
    for table in tables {
        let columns: Vec<String> = if table == "sqlite_schema" {
            ["type", "name", "tbl_name", "sql"]
                .map(str::to_string)
                .to_vec()
        } else {
            sqlx::query_scalar("SELECT name FROM pragma_table_info(?) ORDER BY cid")
                .bind(&table)
                .fetch_all(&mut connection)
                .await?
        };
        let selection = columns
            .iter()
            .map(|column| format!("\"{}\"", column.replace('"', "\"\"")))
            .collect::<Vec<_>>()
            .join(", ");
        // Identifiers come only from this test-owned SQLite schema and are
        // double-quoted/escaped; no value is interpolated into the query.
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT ");
        query
            .push(selection)
            .push(" FROM \"")
            .push(table.replace('"', "\"\""))
            .push("\"");
        let mut rows = Vec::new();
        for row in query.build().fetch_all(&mut connection).await? {
            let mut values = Vec::new();
            for index in 0..columns.len() {
                let raw = row.try_get_raw(index)?;
                values.push(if raw.is_null() {
                    LogicalValue::Null
                } else {
                    match raw.type_info().name() {
                        "INTEGER" => LogicalValue::Integer(row.try_get(index)?),
                        "REAL" => LogicalValue::Real(row.try_get::<f64, _>(index)?.to_bits()),
                        "TEXT" => LogicalValue::Text(row.try_get(index)?),
                        "BLOB" => LogicalValue::Blob(row.try_get(index)?),
                        other => {
                            return Err(format!("unsupported logical cell type: {other}").into());
                        }
                    }
                });
            }
            rows.push(values);
        }
        rows.sort();
        snapshot.insert(table, LogicalTable { columns, rows });
    }
    sqlx::query("ROLLBACK").execute(&mut connection).await?;
    connection.close().await?;
    Ok(snapshot)
}

fn recovery_fixture() -> Result<(TempDir, AgentdConfig, AgentId), Box<dyn Error>> {
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

    Ok((temp, config, owner))
}

#[tokio::test]
async fn agentd_product_host_recovers_existing_active_lease_without_advancing_cut()
-> Result<(), Box<dyn Error>> {
    let (_temp, config, owner) = recovery_fixture()?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"active-lease-recovery-grant"),
        13,
        17,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(b"active-lease-recovery-fence".to_vec())?,
    )?;
    let verified_authority = authority.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected_owner: &AgentId| -> Result<(), String> {
            if lease != &verified_authority || expected_owner != &owner {
                return Err("unexpected recovery authority".to_string());
            }
            Ok(())
        },
    );
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::clone(&verifier),
        "existing-active-recovery",
        1,
    )
    .await?;
    let expected = writer.recovery_anchor().await?;
    let before = logical_snapshot(writer.database_path()).await?;
    drop(writer);
    store.close().await;
    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
        authority,
        verifier,
        "existing-active-recovery",
        1,
    )
    .await?;
    assert_eq!(host.writer().recovery_anchor().await?, expected);
    assert_eq!(
        logical_snapshot(host.writer().database_path()).await?,
        before
    );
    host.writer().release().await?;
    Ok(())
}
