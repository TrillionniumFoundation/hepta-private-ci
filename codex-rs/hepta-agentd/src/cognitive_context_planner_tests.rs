use super::*;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;

async fn fixture() -> (AgentId, ReadIdsResultV1, CognitiveContextSnapshot) {
    let temporary = tempfile::tempdir().expect("private fixture directory");
    let fleet = temporary.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("fleet directory");
    let fleet = std::fs::canonicalize(fleet).expect("absolute fleet");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000219").expect("owner");
    let layout = HeptaFleetRoot::parse(fleet).expect("fleet root").layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("canonical owner");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store.append_source(&access, &SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "canonical-plan-source".to_string(),
        content: b"verified canonical orchard".to_vec(),
        observed_at_unix_seconds: 100,
    }).await.expect("owner source");
    store.remember_memory(&access, &MemoryDraft {
        stable_key: "canonical-plan-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope: scope.clone(),
            content: "verified canonical orchard".to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: 100,
            valid_to_unix_seconds: None,
            citations: vec![citation],
        },
    }).await.expect("verified memory");
    let mut response = super::super::read(&store, &owner, 1, "orchard", 4, None)
        .await.expect("real owner read");
    assert_eq!(response.items.len(), 1);
    response.plan = None;
    let cut = store.lane_c_snapshot(
        &access, &scope, super::super::now_seconds().expect("owner wall clock"),
    ).await.expect("owner cut");
    let read = super::super::read_selected_items(&cut, &response.items).expect("canonical exact IDs");
    assert_eq!(
        super::super::bind_selected_read(&cut, &read, None).to_string(),
        response.read_digest,
    );
    (owner, read, response)
}

fn plan(
    owner: &AgentId,
    read: &ReadIdsResultV1,
    response: &CognitiveContextSnapshot,
    origin: Instant,
) -> Result<ObservedContextPlanV1, String> {
    plan_authenticated_context(
        owner,
        1,
        read,
        response.read_digest.parse().expect("fixture bound digest"),
        response,
        origin,
        crate::MAX_COGNITIVE_CONTEXT_BYTES,
    )
}

#[tokio::test]
async fn canonical_owner_records_determine_the_count_and_bytes() {
    let (owner, read, response) = fixture().await;
    let planned = plan(&owner, &read, &response, Instant::now()).expect("attested plan");
    assert!(planned.read_allowed);
    assert_eq!(
        planned.context_digest,
        Digest32::of_bytes(&serde_json::to_vec(&response).expect("canonical response")),
    );
}

#[tokio::test]
async fn matching_caller_content_hash_cannot_replace_an_attested_body() {
    let (owner, read, mut response) = fixture().await;
    response.items[0].content = "invented caller body".to_string();
    response.items[0].content_sha256 = Digest32::of_bytes(response.items[0].content.as_bytes()).to_string();
    assert!(plan(&owner, &read, &response, Instant::now()).is_err());
}

#[tokio::test]
async fn caller_revision_cannot_replace_the_canonical_record_revision() {
    let (owner, read, mut response) = fixture().await;
    response.items[0].revision += 1;
    assert!(plan(&owner, &read, &response, Instant::now()).is_err());
}

#[tokio::test]
async fn duplicated_or_omitted_response_items_do_not_change_attested_count() {
    let (owner, read, mut response) = fixture().await;
    response.items.push(response.items[0].clone());
    assert!(plan(&owner, &read, &response, Instant::now()).is_err());
    response.items.clear();
    assert!(plan(&owner, &read, &response, Instant::now()).is_err());
}

#[tokio::test]
async fn a_caller_snapshot_digest_cannot_rebind_an_exact_id_receipt() {
    let (owner, read, mut response) = fixture().await;
    response.snapshot_digest = Digest32::of_bytes(b"another snapshot").to_string();
    assert!(plan(&owner, &read, &response, Instant::now()).is_err());
}

#[tokio::test]
async fn future_and_expired_monotonic_origins_are_rejected() {
    let (owner, read, response) = fixture().await;
    let now = Instant::now();
    assert!(plan(&owner, &read, &response, now + Duration::from_secs(1)).is_err());
    let expired = now.checked_sub(Duration::from_secs(2)).expect("expired test origin");
    assert!(plan(&owner, &read, &response, expired).is_err());
}
