use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use crate::*;

struct ProbeProvider {
    calls: Arc<AtomicUsize>,
    status: ProviderEffectAckStatus,
}

impl ProviderEffectAdapter for ProbeProvider {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            ProviderEffectDispatch::Ack(ProviderEffectAck::new(
                intent.key.clone(),
                intent.payload_sha256.clone(),
                Sha256Digest::for_bytes(b"provider-operation"),
                self.status,
            ))
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::NotFound })
    }
}

#[derive(Clone, Copy)]
enum ObservationCase {
    Satisfied,
    Error,
    OldAttempt,
    WrongContract,
    WrongPayload,
    Partial,
    Waiting,
}

struct ProbeObserver(ObservationCase);

impl ActionSkillObserver for ProbeObserver {
    fn observer_id(&self) -> &str {
        "independent-observer"
    }

    async fn check_initiation(
        &self,
        binding: &ActionSkillBindingV1,
        _body: &[u8],
    ) -> Result<ActionInitiationObservationV1, ActionSkillError> {
        Ok(ActionInitiationObservationV1 {
            binding: binding.clone(),
            observer_id: self.observer_id().to_string(),
            evidence_digest: Sha256Digest::for_bytes(b"initiation"),
            condition: ActionConditionV1::Met,
        })
    }

    async fn observe(
        &self,
        binding: &ActionSkillBindingV1,
        provider_receipt_digest: &Sha256Digest,
    ) -> Result<ActionSkillObservationV1, ActionSkillError> {
        let mut observed = ActionSkillObservationV1 {
            binding: binding.clone(),
            provider_receipt_digest: provider_receipt_digest.clone(),
            observer_id: self.observer_id().to_string(),
            evidence_digest: Sha256Digest::for_bytes(b"goal"),
            absence_proof_digest: None,
            execution: ActionExecutionStateV1::Returned { exit_code: Some(0) },
            cancellation: ActionCancellationStateV1::Requested,
            termination: ActionConditionV1::Met,
            goal: ActionGoalStateV1::Satisfied,
        };
        match self.0 {
            ObservationCase::Satisfied => {}
            ObservationCase::Error => return Err(ActionSkillError::Observation),
            ObservationCase::OldAttempt => {
                observed.binding.effect_intent_digest = Sha256Digest::for_bytes(b"old-attempt")
            }
            ObservationCase::WrongContract => {
                observed.binding.contract_digest = Sha256Digest::for_bytes(b"other-skill")
            }
            ObservationCase::WrongPayload => {
                observed.binding.provider_intent.payload_sha256 =
                    Sha256Digest::for_bytes(b"other-payload")
            }
            ObservationCase::Partial => observed.goal = ActionGoalStateV1::Partial,
            ObservationCase::Waiting => {
                observed.execution = ActionExecutionStateV1::WaitingForInput
            }
        }
        Ok(observed)
    }
}

fn contract() -> ActionSkillContractV1 {
    ActionSkillContractV1 {
        schema_version: ACTION_SKILL_SCHEMA_VERSION,
        skill_id: "create-task".to_string(),
        version: 1,
        destination_id: "automation-test".to_string(),
        observer_id: "independent-observer".to_string(),
        initiation_digest: Sha256Digest::for_bytes(b"initiate"),
        policy_digest: Sha256Digest::for_bytes(b"policy"),
        termination_digest: Sha256Digest::for_bytes(b"terminal"),
        goal_digest: Sha256Digest::for_bytes(b"goal"),
        budget: ActionSkillBudgetV1 {
            max_wire_bytes: 4096,
            provider_timeout_ms: 1000,
            observer_timeout_ms: 1000,
        },
        recovery: ActionSkillRecoveryV1::ReconcileOriginalIdentity,
    }
}

fn effect(wire: &[u8]) -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: "run".to_string(),
        step_id: "step".to_string(),
        attempt: 1,
        operation_id: "operation".to_string(),
        subject_id: "agent".to_string(),
        destination_id: "automation-test".to_string(),
        payload_digest: Sha256Digest::for_bytes(wire),
        final_use_scope_digest: Sha256Digest::for_bytes(b"scope"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

// Decorator-level probes only; the ACT-1 integration suite uses the durable
// AutomationStore owner and independent final-use authority.
async fn invoke(
    driver: &mut GoalCheckedActionSkillDriver<ProbeProvider, ProbeObserver>,
    intent: &AuthorizedEffectIntent,
    wire: &[u8],
) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
    let digest = intent.digest().expect("intent");
    let operation = intent.operation_intent_v1().expect("operation");
    let binding = intent.final_use_binding().expect("binding");
    let key = ProviderEffectKey::for_logical_effect(&intent.destination_id, "taskflow:run:step")
        .expect("key");
    driver
        .dispatch(AuthorizedProviderEffectRequest {
            operation_intent: &operation,
            intent,
            intent_digest: &digest,
            binding: &binding,
            provider_intent: ProviderEffectIntent::new(key, intent.payload_digest.clone()),
            wire_payload: wire,
        })
        .await
}

#[tokio::test]
async fn changed_skill_contract_is_rejected_before_provider_contact() {
    let mut contract = contract();
    let wire = contract
        .encode_invocation(b"create".to_vec())
        .expect("wire");
    contract.policy_digest = Sha256Digest::for_bytes(b"changed-policy");
    let calls = Arc::new(AtomicUsize::new(0));
    let mut driver = GoalCheckedActionSkillDriver::new(
        contract,
        ProbeProvider {
            calls: Arc::clone(&calls),
            status: ProviderEffectAckStatus::Completed,
        },
        ProbeObserver(ObservationCase::Satisfied),
    )
    .expect("driver");
    assert_eq!(
        invoke(&mut driver, &effect(&wire), &wire).await,
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn unbound_or_nonterminal_evidence_never_closes_a_completed_provider_effect() {
    for case in [
        ObservationCase::Error,
        ObservationCase::OldAttempt,
        ObservationCase::WrongContract,
        ObservationCase::WrongPayload,
        ObservationCase::Partial,
        ObservationCase::Waiting,
    ] {
        let contract = contract();
        let wire = contract
            .encode_invocation(b"create".to_vec())
            .expect("wire");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut driver = GoalCheckedActionSkillDriver::new(
            contract,
            ProbeProvider {
                calls: Arc::clone(&calls),
                status: ProviderEffectAckStatus::Completed,
            },
            ProbeObserver(case),
        )
        .expect("driver");
        let receipt = invoke(&mut driver, &effect(&wire), &wire)
            .await
            .expect("contact is not absence");
        assert_eq!(receipt.outcome, AuthorizedEffectOutcome::Indeterminate);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn cancellation_and_rejection_do_not_erase_observed_effects() {
    for (status, case, expected) in [
        (
            ProviderEffectAckStatus::Completed,
            ObservationCase::Satisfied,
            AuthorizedEffectOutcome::Succeeded,
        ),
        (
            ProviderEffectAckStatus::Rejected,
            ObservationCase::Partial,
            AuthorizedEffectOutcome::Indeterminate,
        ),
        (
            ProviderEffectAckStatus::Rejected,
            ObservationCase::Satisfied,
            AuthorizedEffectOutcome::Indeterminate,
        ),
    ] {
        let contract = contract();
        let wire = contract
            .encode_invocation(b"create".to_vec())
            .expect("wire");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut driver = GoalCheckedActionSkillDriver::new(
            contract,
            ProbeProvider {
                calls: Arc::clone(&calls),
                status,
            },
            ProbeObserver(case),
        )
        .expect("driver");
        let intent = effect(&wire);
        assert_eq!(
            invoke(&mut driver, &intent, &wire)
                .await
                .expect("observed")
                .outcome,
            expected
        );
        let pending = AuthorizedEffectPending {
            run_id: intent.run_id.clone(),
            step_id: intent.step_id.clone(),
            attempt: intent.attempt,
            intent_digest: intent.digest().expect("intent"),
            payload_digest: intent.payload_digest.clone(),
            binding_digest: Sha256Digest::for_bytes(b"binding"),
            destination_id: intent.destination_id.clone(),
            authority_epoch: 1,
            grant_id: "grant".to_string(),
            started_at_ms: 1,
        };
        // A provider NotFound after contact never grants a new attempt.
        assert_eq!(
            driver.lookup(&pending, &wire).await,
            AuthorizedProviderEffectLookup::Unresolved
        );
        let feedback = driver
            .observe_pending(&pending, &wire)
            .await
            .expect("read-only feedback");
        assert_eq!(feedback.cancellation, ActionCancellationStateV1::Requested);
        let plan = ActionCheckPlanV1 {
            binding: feedback.binding.clone(),
            generation: 1,
            effective_model_digest: Sha256Digest::for_bytes(b"model"),
            source_frontier_digest: Sha256Digest::for_bytes(b"source"),
            checker_digest: Sha256Digest::for_bytes(b"checker"),
            remediation_digest: Sha256Digest::for_bytes(b"response"),
            cost_unit: "test-unit".to_string(),
            timing: ActionCheckTimeV1::Unknown,
            estimate: ActionCheckEstimateV1 {
                error_ppm: 1_000_000,
                detection_ppm: 1_000_000,
                false_positive_ppm: 0,
                remediation_success_ppm: 1_000_000,
                error_loss: 100,
                check_cost: 1,
                true_positive_response_cost: 1,
                false_positive_response_cost: 1,
            },
        };
        assert_eq!(
            driver
                .observe_check_plan(&pending, &wire, &plan, &ActionCheckClockV1::Unknown)
                .await,
            Ok(ActionCheckReadbackV1 {
                observation: feedback,
                assessment: plan
                    .assess(&plan.binding, &ActionCheckClockV1::Unknown)
                    .expect("assessment"),
            })
        );
        // Readback never dispatches, even when its estimate favors checking.
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
