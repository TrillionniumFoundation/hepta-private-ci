//! A current signature cannot replace the original owner's evaluation plan.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;
use crate::learning_iteration_channel_scoped_v2;

#[tokio::test]
async fn signed_training_profile_drift_stops_before_evaluation_in_both_scope_profiles() {
    for update_scope in [None, Some(LearningUpdateScopeV2::Cell)] {
        let daemon = AgentdFixture::new();
        let state = daemon.state();
        let mut request = iteration_request(&daemon);
        request.evaluation_profile = digest("owner-preregistered-evaluation");
        let mut ports = IterationPorts::new(
            /*proposal*/ None,
            LearningEvaluationDispositionV1::NoUpdate,
        );
        let scope = update_scope.map(|update_scope| {
            ok(FrozenLearningScopeV2::freeze(
                &request,
                &ports.owners(),
                update_scope,
                digest("test-rule"),
            ))
        });
        ports.scope_binding = scope.as_ref().map(FrozenLearningScopeV2::binding);
        let ports = Arc::new(ports);
        let (_, owner) = ok(match scope {
            Some(scope) => learning_iteration_channel_scoped_v2(
                daemon.identity.agent_id.clone(),
                /*spawn_generation*/ 1,
                ports.owners(),
                ports.clone(),
                ports.verifier.clone(),
                /*capacity*/ 2,
                scope,
            ),
            None => learning_iteration_channel_v1(
                daemon.identity.agent_id.clone(),
                /*spawn_generation*/ 1,
                ports.owners(),
                ports.clone(),
                ports.verifier.clone(),
                /*capacity*/ 2,
            ),
        });
        // The trainer still returns its independently signed frozen-evaluation
        // lineage. It cannot replace the profile selected before the dataset.
        assert!(matches!(
            owner.process(&state, request.clone(), || Ok(50)).await,
            Err(LearningIterationRuntimeErrorV1::Validation(
                LearningIterationError::ContextMismatch
            ))
        ));
        let executed = vec![
            LearningIterationStageV1::Experience,
            LearningIterationStageV1::Dataset,
            LearningIterationStageV1::Training,
        ];
        assert_eq!(ok(ports.executed.lock()).clone(), executed);
        assert_eq!(ok(ports.attested.lock()).clone(), executed);
        let saved = ok(ports.checkpoint.lock()).clone().expect("dataset checkpoint");
        assert_eq!(saved.request, request);
        assert_eq!(saved.receipts.len(), 2);
        let checkpoint_calls = ok(ports.checkpoint_calls.lock()).clone();
        assert_eq!(checkpoint_calls.len(), 3);

        // Submit and read-only recovery both reject rebinding the old operation
        // to the trainer's preferred profile without another owner stage or CAS.
        let rebound = iteration_request(&daemon);
        for error in [
            owner.process(&state, rebound.clone(), || Ok(50)).await,
            owner.process_readback(&state, rebound, || Ok(50)).await,
        ] {
            match update_scope {
                Some(LearningUpdateScopeV2::Cell) => assert!(matches!(
                    error,
                    Err(LearningIterationRuntimeErrorV1::Validation(
                        LearningIterationError::UpdateScopeMismatch
                    ))
                )),
                None => assert!(matches!(
                    error,
                    Err(LearningIterationRuntimeErrorV1::WrongScope)
                )),
                Some(LearningUpdateScopeV2::Organ | LearningUpdateScopeV2::BaseRelease) => {
                    unreachable!("only the declared Cell and unscoped profiles are exercised");
                }
            }
        }
        assert_eq!(ok(ports.executed.lock()).clone(), executed);
        assert_eq!(ok(ports.attested.lock()).clone(), executed);
        assert_eq!(ok(ports.checkpoint_calls.lock()).clone(), checkpoint_calls);
        assert_eq!(ok(ports.checkpoint.lock()).clone(), Some(saved));
    }
}
