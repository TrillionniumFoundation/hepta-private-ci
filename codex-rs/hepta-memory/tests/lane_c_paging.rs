use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

fn layout(temp: &TempDir, owner: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("create fleet");
    HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(owner)
}

fn source(scope: CognitiveScope, key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

fn revision(scope: CognitiveScope, content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test]
async fn lineage_pages_keep_whole_histories_and_one_exact_cut() {
    let temp = TempDir::new().expect("tempdir");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000a01").expect("owner");
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;

    let first = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "source:first:v1", "first-v1"),
            &MemoryDraft {
                stable_key: "memory:first".to_string(),
                revision: revision(scope.clone(), "first-v1"),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("remember first");
    let first_id = first.memory.id.memory_id.clone();
    store
        .correct_with_kg(
            &access,
            &first_id,
            1,
            &source(scope.clone(), "source:first:v2", "first-v2"),
            &revision(scope.clone(), "first-v2"),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("correct first");
    let reason = "privacy-delete-first";
    store
        .forget_with_kg(
            &access,
            &first_id,
            2,
            &source(scope.clone(), "source:first:delete", reason),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: reason.to_string(),
                valid_from_unix_seconds: 100,
                citations: Vec::new(),
            },
        )
        .await
        .expect("forget first");

    for index in 0..2 {
        let content = format!("other-{index}");
        store
            .remember_with_kg(
                &access,
                &source(
                    scope.clone(),
                    &format!("source:other:{index}"),
                    &content,
                ),
                &MemoryDraft {
                    stable_key: format!("memory:other:{index}"),
                    revision: revision(scope.clone(), &content),
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("remember other");
    }

    let mut cursor = None;
    let mut cut = None;
    let mut pages = 0_usize;
    let mut saw_tombstoned_history = false;
    loop {
        let page = store
            .lane_c_lineage_page(&access, &scope, cut.as_ref(), cursor.as_ref(), 1)
            .await
            .expect("lineage page");
        pages += 1;
        assert_eq!(page.frontiers.memory, 5);
        assert_eq!(page.frontiers.tombstone, 1);
        if let Some(expected) = &cut {
            assert_eq!(&page.cut_digest, expected);
        } else {
            cut = Some(page.cut_digest.clone());
        }
        if let Some(first_record) = page.records.first() {
            assert!(page
                .records
                .iter()
                .all(|record| record.id.memory_id == first_record.id.memory_id));
            for (index, record) in page.records.iter().enumerate() {
                assert_eq!(record.id.revision, u64::try_from(index + 1).expect("revision"));
                assert_eq!(
                    record.supersedes_revision,
                    (index > 0).then_some(u64::try_from(index).expect("predecessor"))
                );
            }
            if first_record.id.memory_id == first_id {
                assert_eq!(page.records.len(), 3);
                assert!(matches!(
                    &page.records.last().expect("last").lifecycle,
                    MemoryLifecycleState::Tombstoned { .. }
                ));
                saw_tombstoned_history = true;
            }
        }
        match page.next_after_memory_id {
            Some(next) => cursor = Some(next),
            None => break,
        }
    }
    assert_eq!(pages, 3);
    assert!(saw_tombstoned_history);
}

#[tokio::test]
async fn lineage_cursor_fails_closed_after_owner_mutation() {
    let temp = TempDir::new().expect("tempdir");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000a02").expect("owner");
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;

    for index in 0..2 {
        let content = format!("seed-{index}");
        store
            .remember_with_kg(
                &access,
                &source(scope.clone(), &format!("source:seed:{index}"), &content),
                &MemoryDraft {
                    stable_key: format!("memory:seed:{index}"),
                    revision: revision(scope.clone(), &content),
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("seed memory");
    }

    let first = store
        .lane_c_lineage_page(&access, &scope, None, None, 1)
        .await
        .expect("first page");
    let cursor = first
        .next_after_memory_id
        .clone()
        .expect("second page exists");

    store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "source:mutation", "mutation"),
            &MemoryDraft {
                stable_key: "memory:mutation".to_string(),
                revision: revision(scope.clone(), "mutation"),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("mutate owner");

    let error = store
        .lane_c_lineage_page(
            &access,
            &scope,
            Some(&first.cut_digest),
            Some(&cursor),
            1,
        )
        .await
        .expect_err("stale cursor must fail");
    assert!(error
        .to_string()
        .contains("cursor belongs to a different owner cut"));
}
