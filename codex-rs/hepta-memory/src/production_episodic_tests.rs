use std::sync::Arc;

use pretty_assertions::assert_eq;

use super::test_support::Fixture;
use super::test_support::fixture;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::MemoryVerification;
use crate::ProductionDurableWriter;
use crate::StableMemoryId;
use crate::cognitive_test_support;
use crate::episodic_test_support::GOLDEN;
use crate::episodic_test_support::SourceWitness;
use crate::episodic_test_support::TestResult;

#[tokio::test]
async fn committed_import_reopens_and_reconciles_lost_response_without_rewriting() -> TestResult {
    let Fixture {
        directory,
        store,
        writer,
        authority,
        verifier,
        access,
        ..
    } = fixture().await?;
    let capability = writer.cognitive_mutation_capability()?;
    let witness = SourceWitness::current(GOLDEN);
    let committed = capability
        .import_episodic_snapshot(&access, &CognitiveScope::AgentPrivate, GOLDEN, &witness)
        .await?;
    let id = StableMemoryId::parse(&committed.bindings[0].memory_id)?;
    let original_memory = store.latest_memory(&access, &id).await?;
    assert_eq!(original_memory.content, "Use route blue.");
    assert_eq!(original_memory.verification, MemoryVerification::Verified);
    let candidates = store
        .retrieve_memory_candidates(
            &access,
            &crate::RetrievalRequest::new("route blue", /*now_unix_seconds*/ 100),
        )
        .await?;
    assert_eq!(
        candidates
            .candidates
            .iter()
            .map(|candidate| candidate.memory.id.memory_id.clone())
            .collect::<Vec<_>>(),
        vec![id.clone()]
    );
    let cut = writer.recovery_anchor().await?;
    drop(capability);
    drop(writer); // The client loses the response before its own state advances.
    store.close().await;
    let layout = cognitive_test_support::layout(&directory, &authority.agent_id);
    let recovered = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &authority,
        verifier.as_ref(),
    )
    .await?;
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            recovered.clone(),
            authority,
            verifier,
            "episodic-original-writer",
            /*generation*/ 1,
        )
        .await?,
    );
    let replay = writer
        .cognitive_mutation_capability()?
        .import_episodic_snapshot(&access, &CognitiveScope::AgentPrivate, GOLDEN, &witness)
        .await?;
    assert_eq!(replay, committed);
    assert_eq!(writer.recovery_anchor().await?, cut);
    assert_eq!(
        recovered.latest_memory(&access, &id).await?,
        original_memory
    );
    Ok(())
}
