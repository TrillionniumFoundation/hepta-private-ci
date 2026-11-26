use super::*;
use crate::ContextAttachment;
use crate::RunSnapshot;

#[tokio::test]
async fn restart_dispatch_rechecks_original_receipt_generation_and_fence_for_both_methods()
-> anyhow::Result<()> {
    let (_directory, _registry, state) = super::isolation_tests::fixture_with_readiness(false)?;
    let cognitive = CognitiveStore::open(&state.identity.layout).await?;
    state.attach_cognitive_store(Arc::new(cognitive))?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    let generation = state.current_generation()?;
    let deadline = unix_now_ms()?
        .checked_add(60_000)
        .ok_or_else(|| anyhow::anyhow!("fixture deadline overflow"))?;
    for (index, (run_generation, fence)) in [
        (
            generation - 1,
            objective_run_fence(&state.identity, generation - 1),
        ),
        (generation, "a".repeat(64)),
    ]
    .into_iter()
    .enumerate()
    {
        let run_id = format!("prior.{index}");
        let snapshot = RunSnapshot {
            run_id: run_id.clone(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 1,
            generation: run_generation,
            fence_digest: fence.clone(),
            deadline_ms: deadline,
        };
        let attachment = ContextAttachment {
            run_id: run_id.clone(),
            request_digest: snapshot.request_digest.clone(),
            objective_digest: snapshot.objective_digest.clone(),
            body_digest: snapshot.body_digest.clone(),
            artifact_set_digest: snapshot.artifact_set_digest.clone(),
            authority_epoch: 1,
            generation: run_generation,
            fence_digest: fence,
            deadline_ms: deadline,
            context_digest: "5".repeat(64),
            compilation_receipt_digest: "6".repeat(64),
        };
        // This is deliberately owner-local history injection in a fixture,
        // never a product admission API or a current execution grant.
        let revision = {
            let mut runs = state.runs.lock().map_err(poisoned_state)?;
            let mut candidate = runs.clone();
            candidate.start_run(unix_now_ms()?, snapshot)?;
            let context = candidate.attach_context(unix_now_ms()?, 1, attachment)?;
            runs.publish_candidate(candidate, context.revision)?
        };
        let path = state
            .identity
            .run_root
            .join("runtime-codex-agent-runs-v1.json");
        let before = std::fs::read(&path)?;
        for method in [
            crate::AgentdMethod::RunMarkDispatched {
                run_id: run_id.clone(),
                expected_revision: revision,
            },
            crate::AgentdMethod::RunMarkDispatchedBound {
                run_id: run_id.clone(),
                expected_revision: revision,
                dispatch_binding_digest: "7".repeat(64),
                pre_effect_abort_commitment_digest: "8".repeat(64),
            },
        ] {
            let result = state
                .response(100, state.identity.spawn_generation, method)
                .await;
            assert!(
                matches!(result, Err(AgentdError::GenerationFenced(_))),
                "original tuple must be fenced: {result:?}"
            );
            assert_eq!(std::fs::read(&path)?, before);
        }
    }
    Ok(())
}
