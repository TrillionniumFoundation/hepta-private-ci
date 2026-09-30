//! Public durable-owner tests for lost acknowledgements, competing heads and reopen.
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

fn owner(suffix: u8) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012x}")).expect("valid owner")
}

fn layout(temporary: &TempDir, owner: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let fleet = temporary.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("create fleet root");
    HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(owner)
}

fn source(event_key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

fn first_memory(stable_key: &str, content: &str) -> MemoryDraft {
    MemoryDraft {
        stable_key: stable_key.to_string(),
        revision: correction(content),
    }
}

fn correction(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test]
async fn committed_unknown_result_reconciles_exact_receipt_after_reopen() {
    let temporary = TempDir::new().expect("temporary directory");
    let owner = owner(221);
    let owner_layout = layout(&temporary, &owner);
    let access = CognitiveAccess::agent_private(owner);
    let writer = CognitiveStore::open(&owner_layout).await.expect("writer");

    let initial_content = "Ada owns the first knowledge graph revision.";
    let remembered = writer
        .remember_with_kg(
            &access,
            &source("delivery-initial", initial_content),
            &first_memory("delivery-memory", initial_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("initial publication");

    let corrected_content = "Ada owns the committed knowledge graph revision.";
    let correction_source = source("delivery-correction", corrected_content);
    let correction_draft = correction(corrected_content);
    let committed = writer
        .correct_with_kg(
            &access,
            &remembered.memory.id.memory_id,
            1,
            &correction_source,
            &correction_draft,
            &KgFactSetDraft::default(),
        )
        .await
        .expect("committed correction");

    // Simulate a caller that lost the successful response: a new handle first
    // retries the immutable source acknowledgement, then retries the stale CAS.
    let reconciler = CognitiveStore::open(&owner_layout)
        .await
        .expect("reopen after unknown result");
    assert_eq!(
        reconciler
            .append_source(&access, &correction_source)
            .await
            .expect("idempotent source acknowledgement retry"),
        committed.source
    );
    let stale_retry = reconciler
        .correct_with_kg(
            &access,
            &remembered.memory.id.memory_id,
            1,
            &correction_source,
            &correction_draft,
            &KgFactSetDraft::default(),
        )
        .await
        .expect_err("stale whole-operation retry must not publish again");
    assert!(matches!(stale_retry, CognitiveStoreError::Conflict(_)));

    let head = reconciler
        .read_memory_head(&access, &remembered.memory.id.memory_id)
        .await
        .expect("reconciled head");
    let explanation = reconciler
        .explain_memory_head(&access, &remembered.memory.id.memory_id)
        .await
        .expect("reconciled projection binding");
    assert_eq!(head, committed.memory);
    assert_eq!(explanation.memory, committed.memory);
    assert_eq!(
        explanation.kg_projection_generation,
        Some(committed.projection.generation)
    );
    assert_eq!(
        explanation.kg_projection_generation_sha256,
        Some(committed.projection.generation_sha256)
    );
}

#[tokio::test]
async fn competing_head_reopen_selects_one_complete_receipt() {
    let temporary = TempDir::new().expect("temporary directory");
    let owner = owner(222);
    let owner_layout = layout(&temporary, &owner);
    let access = CognitiveAccess::agent_private(owner);
    let seed = CognitiveStore::open(&owner_layout)
        .await
        .expect("seed writer");
    let initial_content = "The predecessor remains fully recoverable.";
    let remembered = seed
        .remember_with_kg(
            &access,
            &source("head-initial", initial_content),
            &first_memory("head-memory", initial_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed publication");
    drop(seed);

    let first = CognitiveStore::open(&owner_layout)
        .await
        .expect("first writer");
    let second = CognitiveStore::open(&owner_layout)
        .await
        .expect("second writer");
    let first_source = source("head-first", "The first correction wins or rolls back.");
    let second_source = source("head-second", "The second correction wins or rolls back.");
    let first_draft = correction("The first correction wins or rolls back.");
    let second_draft = correction("The second correction wins or rolls back.");
    let first_facts = KgFactSetDraft::default();
    let second_facts = KgFactSetDraft::default();

    let (first_result, second_result) = tokio::join!(
        first.correct_with_kg(
            &access,
            &remembered.memory.id.memory_id,
            1,
            &first_source,
            &first_draft,
            &first_facts,
        ),
        second.correct_with_kg(
            &access,
            &remembered.memory.id.memory_id,
            1,
            &second_source,
            &second_draft,
            &second_facts,
        ),
    );
    let winner = match (first_result, second_result) {
        (Ok(receipt), Err(CognitiveStoreError::Conflict(_)))
        | (Err(CognitiveStoreError::Conflict(_)), Ok(receipt)) => receipt,
        outcomes => panic!("expected one complete commit and one conflict: {outcomes:?}"),
    };

    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("reopen competing head");
    let head = reopened
        .read_memory_head(&access, &remembered.memory.id.memory_id)
        .await
        .expect("winner head");
    let explanation = reopened
        .explain_memory_head(&access, &remembered.memory.id.memory_id)
        .await
        .expect("winner projection binding");
    assert_eq!(head, winner.memory);
    assert_eq!(explanation.memory, winner.memory);
    assert_eq!(
        explanation.kg_projection_generation,
        Some(winner.projection.generation)
    );
    assert_eq!(
        explanation.kg_projection_generation_sha256,
        Some(winner.projection.generation_sha256)
    );
}

#[path = "kg_prepared_and_plans.rs"]
mod prepared_and_plans;
