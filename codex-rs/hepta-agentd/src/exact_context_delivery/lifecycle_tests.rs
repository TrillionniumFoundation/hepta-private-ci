//! Exercises the existing exact owner, real registry and filesystem. The
//! subprocess is a protocol fixture, not a qualified provider tokenizer.
use super::*;
use crate::prompt_runtime::AgentdPromptPipelineError;
use crate::prompt_runtime::AgentdPromptRuntimeError;
use crate::prompt_runtime::AgentdPromptRuntimeOwner;

fn compiled(fixture: &Fixture) -> PromptRegistryCompiledContextV3 {
    fixture
        .owner
        .state
        .lock()
        .expect("state")
        .staged
        .values()
        .next()
        .expect("initial context")
        .as_ref()
        .clone()
}

#[tokio::test]
async fn sequential_completed_turns_release_more_than_256_stages() {
    let fixture = Fixture::with_lifetime(/*lifetime_ms*/ 299_000);
    let context = compiled(&fixture);
    fixture
        .owner
        .clear_turn_with("thread-a", "turn-a", || {
            Ok::<_, ExactContextDeliveryError>(false)
        })
        .expect("clear unused fixture turn");
    std::fs::write(&fixture.release, b"release").expect("release tokenizer");
    let mut elapsed_micros = Vec::new();
    for index in 0..=256 {
        let started = Instant::now();
        let mut request = fixture.request.clone();
        request.attempt.turn_id = format!("turn-{index}");
        request.attempt.attempt_id = format!("attempt-{index}");
        request.attempt.request_binding_id = format!("binding-{index}");
        fixture
            .owner
            .stage("thread-a", &request.attempt.turn_id, context.clone())
            .expect("stage after previous terminal");
        Arc::clone(&fixture.owner)
            .observe_final_request(request.clone())
            .await
            .expect("exact owner authorization");
        fixture
            .owner
            .observe_final_terminal(terminal_for(
                &request,
                PromptRuntimeProviderTerminalV2::Completed {
                    response_id_digest: digest("response"),
                    response_items_digest: digest("items"),
                    token_usage_digest: digest("usage"),
                    end_turn: Some(true),
                },
                current_unix_ms().expect("clock"),
            ))
            .await
            .expect("durable final observation");
        let state = fixture.owner.state.lock().expect("state");
        assert!(state.staged.is_empty());
        assert!(state.active.is_empty());
        assert_eq!(state.durable.pre_sends.len(), index + 1);
        assert_eq!(state.durable.terminals.len(), index + 1);
        elapsed_micros.push(u64::try_from(started.elapsed().as_micros()).expect("duration"));
    }
    let diagnostics = fixture.owner.diagnostics().expect("diagnostics");
    assert_eq!(
        diagnostics["phases"]["observations"]["live_attempt_completion"]["count"],
        257
    );
    elapsed_micros.sort_unstable();
    let profile = serde_json::json!({
        "schema": "hepta.context-owner-fixture-profile.v1",
        "scenario": "257_sequential_exact_owner_turns_reusing_one_verified_compilation",
        "qualification_scope": "protocol_fixture_not_provider_or_target_host_acceptance",
        "turns": 257,
        "full_owner_turn_p50_micros": elapsed_micros[128],
        "full_owner_turn_p95_micros": elapsed_micros[244],
        "full_owner_turn_p99_micros": elapsed_micros[254],
        "diagnostics": diagnostics,
    });
    println!("CONTEXT_OWNER_PROFILE {profile}");
}

#[test]
fn runtime_stage_failure_does_not_publish_an_exact_stage() {
    let fixture = Fixture::new();
    let context = compiled(&fixture);
    let runtime = AgentdPromptRuntimeOwner::new();
    let result = fixture
        .owner
        .stage_with("thread-a", "new-turn", context.clone(), || {
            runtime
                .stage_compiled_prompt_context_v3(
                    "thread-a",
                    "new-turn",
                    "wrong-model",
                    fixture.now + 30_000,
                    &context,
                )
                .map_err(AgentdPromptPipelineError::Stage)
        });
    assert!(matches!(result, Err(AgentdPromptPipelineError::Stage(_))));
    assert_eq!(runtime.staged_count().expect("runtime count"), 0);
    assert_eq!(fixture.owner.state.lock().expect("state").staged.len(), 1);
}

#[test]
fn runtime_capacity_failure_does_not_consume_exact_capacity() {
    let fixture = Fixture::new();
    let context = compiled(&fixture);
    let runtime = AgentdPromptRuntimeOwner::new();
    for index in 0..256 {
        runtime
            .stage_compiled_prompt_context_v3(
                "thread-a",
                &format!("runtime-turn-{index}"),
                "model",
                fixture.now + 30_000,
                &context,
            )
            .expect("fill runtime stages");
    }
    let result = fixture
        .owner
        .stage_with("thread-a", "new-turn", context.clone(), || {
            runtime
                .stage_compiled_prompt_context_v3(
                    "thread-a",
                    "new-turn",
                    "model",
                    fixture.now + 30_000,
                    &context,
                )
                .map_err(AgentdPromptPipelineError::Stage)
        });
    assert!(matches!(
        result,
        Err(AgentdPromptPipelineError::Stage(
            AgentdPromptRuntimeError::CapacityExceeded
        ))
    ));
    assert_eq!(fixture.owner.state.lock().expect("state").staged.len(), 1);
}

#[test]
fn uncertain_runtime_publication_leaves_no_exact_authorization() {
    let fixture = Fixture::new();
    let context = compiled(&fixture);
    let path = fixture.directory.path().join("projection");
    let runtime = AgentdPromptRuntimeOwner::open_state_dir(&path).expect("runtime");
    runtime.fail_directory_sync_after_rename_once();
    let result = fixture
        .owner
        .stage_with("thread-a", "new-turn", context.clone(), || {
            runtime
                .stage_compiled_prompt_context_v3(
                    "thread-a",
                    "new-turn",
                    "model",
                    fixture.now + 30_000,
                    &context,
                )
                .map_err(AgentdPromptPipelineError::Stage)
        });
    assert!(matches!(
        result,
        Err(AgentdPromptPipelineError::Stage(
            AgentdPromptRuntimeError::IndeterminateDurability
        ))
    ));
    assert!(runtime.requires_reopen());
    drop(runtime);
    let recovered = AgentdPromptRuntimeOwner::open_state_dir(&path).expect("reopen projection");
    assert_eq!(recovered.staged_count().expect("persisted projection"), 1);
    let key = ExactTurnKey {
        thread_id: "thread-a".into(),
        turn_id: "new-turn".into(),
    };
    assert!(matches!(
        fixture.owner.reserve_preparation(&key),
        Err(ExactContextDeliveryError::MissingStagedContext)
    ));
}

#[test]
fn preparation_reservation_blocks_clear_without_calling_runtime() {
    let fixture = Fixture::new();
    let key = ExactTurnKey {
        thread_id: "thread-a".into(),
        turn_id: "turn-a".into(),
    };
    let (_, reservation) = fixture.owner.reserve_preparation(&key).expect("reserve");
    let mut called = false;
    let result = fixture.owner.clear_turn_with("thread-a", "turn-a", || {
        called = true;
        Ok::<_, ExactContextDeliveryError>(true)
    });
    assert_eq!(result, Err(ExactContextDeliveryError::RecoveryRequired));
    assert!(!called);
    drop(reservation);
    assert!(
        fixture
            .owner
            .clear_turn_with("thread-a", "turn-a", || {
                Ok::<_, ExactContextDeliveryError>(false)
            })
            .expect("clear released reservation")
    );
}

#[tokio::test]
async fn tool_continuation_and_unknown_terminal_keep_the_stage() {
    let fixture = Fixture::new();
    std::fs::write(&fixture.release, b"release").expect("release tokenizer");
    Arc::clone(&fixture.owner)
        .observe_final_request(fixture.request.clone())
        .await
        .expect("prepare");
    fixture
        .owner
        .observe_final_terminal(terminal_for(
            &fixture.request,
            PromptRuntimeProviderTerminalV2::Indeterminate {
                reason_code: "fixture_unknown".into(),
                partial_response_digest: None,
            },
            current_unix_ms().expect("clock"),
        ))
        .await
        .expect("unknown");
    assert_eq!(fixture.owner.state.lock().expect("state").staged.len(), 1);
    assert_eq!(
        fixture.owner.clear_turn_with("thread-a", "turn-a", || {
            Ok::<_, ExactContextDeliveryError>(false)
        }),
        Err(ExactContextDeliveryError::RecoveryRequired)
    );
    fixture
        .owner
        .observe_final_terminal(terminal_for(
            &fixture.request,
            PromptRuntimeProviderTerminalV2::Completed {
                response_id_digest: digest("response"),
                response_items_digest: digest("items"),
                token_usage_digest: digest("usage"),
                end_turn: Some(false),
            },
            current_unix_ms().expect("clock"),
        ))
        .await
        .expect("tool continuation");
    let state = fixture.owner.state.lock().expect("state");
    assert_eq!(state.staged.len(), 1);
    assert_eq!(state.durable.observations.len(), 1);
    assert_eq!(state.durable.terminals.len(), 1);
}
