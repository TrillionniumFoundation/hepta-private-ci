#![cfg(unix)]

use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use core_test_support::responses;

mod support;

use support::fleet::FleetHarness;

const AGENT: &str = "019153a4-3088-7e03-a56a-9b1964f75df0";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn tombstone_between_owner_reads_invalidates_the_native_dispatch_receipt_pair() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT, "workspace-cognitive-dispatch-race")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;

    let store = CognitiveStore::open(&agent.layout).await?;
    let access = CognitiveAccess::agent_private(agent.agent_id.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "native-dispatch-receipt-race".to_string(),
                content: b"verified lemon orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "native-dispatch-lemon".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified lemon orchard".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await?;

    // This is the worker's first dispatch-boundary observation.
    let observed = control.cognitive_context("lemon".to_string(), 4).await?;
    ensure!(
        observed
            .items
            .iter()
            .any(|item| item.memory_id == memory.id.memory_id.as_str()
                && item.content == "verified lemon orchard"),
        "initial owner read did not expose the verified memory"
    );

    // Deterministically mutate the canonical owner between the worker's two
    // dispatch-boundary reads. A historical cut must not survive this change.
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdraw before model dispatch".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await?;

    let current = control.cognitive_context("lemon".to_string(), 4).await?;
    ensure!(
        observed.snapshot_digest != current.snapshot_digest
            || observed.read_digest != current.read_digest,
        "tombstone did not invalidate the dispatch receipt pair"
    );
    ensure!(
        current
            .items
            .iter()
            .all(|item| item.memory_id != memory.id.memory_id.as_str()),
        "withdrawn text remained visible in the current owner read"
    );

    // `hepta-infer-worker-host` requires exact equality of this pair before
    // durable dispatch and TurnStart; therefore this race is fail-closed.
    Ok(())
}
