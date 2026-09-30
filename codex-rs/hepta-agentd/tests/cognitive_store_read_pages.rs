#![cfg(unix)]

use std::error::Error;
use std::sync::Arc;

use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveScope;
use codex_hepta_cognitive_store::DurableCognitiveReadStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::LedgerSourceKind;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryLifecycleState;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::MemoryVerification;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_cognitive_store::StableMemoryId;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

struct Fixture {
    reader: DurableCognitiveReadStore,
    store: Arc<CognitiveStore>,
    access: CognitiveAccess,
    scope: CognitiveScope,
    ids: Vec<StableMemoryId>,
    _temp: TempDir,
}

async fn fixture() -> Result<Fixture, Box<dyn Error>> {
    let temp = TempDir::new()?;
    let fleet = temp.path().canonicalize()?.join("fleet");
    std::fs::create_dir(&fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cf71")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let store = Arc::new(CognitiveStore::open(&layout).await?);
    let scope = CognitiveScope::AgentPrivate;
    let access = CognitiveAccess::agent_private(owner);
    let mut ids = Vec::new();
    for index in 0..2 {
        let content = format!("product read page fixture {index}");
        let source = source(&scope, &format!("page-source-{index}"), &content);
        let draft = MemoryDraft {
            stable_key: format!("page-memory-{index}"),
            revision: MemoryRevisionDraft {
                scope: scope.clone(),
                content,
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 1,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        };
        let receipt = store
            .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
            .await?;
        ids.push(receipt.memory.id.memory_id);
    }
    let runtime = CognitiveRuntime::Available(Arc::clone(&store));
    let reader = DurableCognitiveReadStore::from_runtime(&runtime)
        .ok_or("composed owner must provide a bounded read capability")?;
    Ok(Fixture {
        reader,
        store,
        access,
        scope,
        ids,
        _temp: temp,
    })
}

fn source(scope: &CognitiveScope, key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 1,
    }
}

#[tokio::test]
async fn product_read_page_matches_owner_and_revalidates() -> Result<(), Box<dyn Error>> {
    let f = fixture().await?;
    let first = f
        .reader
        .lane_c_snapshot_page(&f.access, &f.scope, 10, 1, None)
        .await?;
    let oracle = f
        .store
        .lane_c_snapshot_page(&f.access, &f.scope, 10, 1, None)
        .await?;
    assert_eq!(first, oracle);
    assert!(!first.authority().grants_any());
    assert!(!first.is_complete());
    assert!(first.next().is_some());
    assert_eq!(
        f.reader
            .revalidate_lane_c_snapshot_page(&f.access, &f.scope, 10, 1, &first)
            .await?,
        first
    );
    let second = f
        .reader
        .lane_c_snapshot_page(&f.access, &f.scope, 10, 1, first.next().cloned())
        .await?;
    assert_eq!(first.cut_digest(), second.cut_digest());
    assert!(second.is_complete());
    assert!(second.next().is_none());
    assert!(
        f.reader
            .revalidate_lane_c_snapshot_page(&f.access, &f.scope, 11, 1, &first)
            .await
            .is_err()
    );
    assert!(
        f.reader
            .revalidate_lane_c_snapshot_page(&f.access, &f.scope, 10, 2, &first)
            .await
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn product_read_page_rejects_invalid_bounds_and_foreign_scope() -> Result<(), Box<dyn Error>>
{
    let f = fixture().await?;
    for limit in [0, 513] {
        assert!(matches!(
            f.reader
                .lane_c_snapshot_page(&f.access, &f.scope, 10, limit, None)
                .await,
            Err(DurableCognitiveStoreError::Invalid(_))
        ));
    }
    let other =
        CognitiveAccess::agent_private(AgentId::parse("00000000-0000-4000-8000-00000000cf72")?);
    assert!(matches!(
        f.reader
            .lane_c_snapshot_page(&other, &f.scope, 10, 1, None)
            .await,
        Err(DurableCognitiveStoreError::AccessDenied(_))
    ));
    Ok(())
}

#[tokio::test]
async fn product_read_page_rejects_stale_cut_after_tombstone() -> Result<(), Box<dyn Error>> {
    let f = fixture().await?;
    let first = f
        .reader
        .lane_c_snapshot_page(&f.access, &f.scope, 10, 1, None)
        .await?;
    let reason = "product pagination tombstone regression";
    let forgotten = ForgetMemoryDraft {
        scope: f.scope.clone(),
        reason: reason.to_string(),
        valid_from_unix_seconds: 1,
        citations: Vec::new(),
    };
    f.store
        .forget_with_kg(
            &f.access,
            &f.ids[0],
            1,
            &source(&f.scope, "page-forget", reason),
            &forgotten,
        )
        .await?;
    assert!(matches!(
        f.reader
            .lane_c_snapshot_page(&f.access, &f.scope, 10, 1, first.next().cloned())
            .await,
        Err(DurableCognitiveStoreError::Conflict(_))
    ));
    assert!(
        f.reader
            .revalidate_lane_c_snapshot_page(&f.access, &f.scope, 10, 1, &first)
            .await
            .is_err()
    );
    let fresh = f
        .reader
        .lane_c_snapshot_page(&f.access, &f.scope, 10, 2, None)
        .await?;
    assert_eq!(fresh.frontiers().tombstone, 1);
    assert!(!fresh.authority().grants_any());
    Ok(())
}
