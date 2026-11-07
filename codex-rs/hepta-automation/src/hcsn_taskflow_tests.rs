#![allow(clippy::expect_used, reason = "HCSN effect boundary fixtures")]

use super::*;
use crate::authorized_effect::AuthorizedEffectIntent;
use crate::hcsn_job::HCSN_SUPERVISOR_SCHEMA_VERSION;
use crate::hcsn_job::HcsnJobEvidenceV1;
use crate::hcsn_job::HcsnProcessIdentityV1;
use crate::hcsn_job::HcsnSupervisorActionV1;

const PAYLOAD: &[u8] = b"{\"operation_id\":\"joint-bp\"}";
const SCOPE: &str = "provider:hcsn";

struct ProbeSupervisor {
    commands: Vec<HcsnSupervisorCommandV1>,
    state: Result<HcsnJobStateV1, HcsnSupervisorError>,
    foreign_output: Option<Sha256Digest>,
}

impl HcsnSupervisor for ProbeSupervisor {
    fn exchange(
        &mut self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<HcsnJobObservationV1, HcsnSupervisorError> {
        self.commands.push(command.clone());
        let state = self.state?;
        let evidence = match state {
            HcsnJobStateV1::Succeeded | HcsnJobStateV1::Failed | HcsnJobStateV1::Cancelled => {
                Some(HcsnJobEvidenceV1 {
                    receipt_sha256: Sha256Digest::for_bytes(b"durable-receipt"),
                    candidate_sha256: Some(Sha256Digest::for_bytes(b"candidate")),
                    handoff_sha256: Some(Sha256Digest::for_bytes(b"handoff")),
                })
            }
            HcsnJobStateV1::Reserved | HcsnJobStateV1::Running | HcsnJobStateV1::Unknown => None,
        };
        let mut observation = HcsnJobObservationV1 {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            dispatch: command.dispatch.clone(),
            target: command.target.clone(),
            state,
            process: Some(HcsnProcessIdentityV1 {
                host_id: Sha256Digest::for_bytes(b"host"),
                process_id: 101,
                incarnation: Sha256Digest::for_bytes(b"boot:start-ticks"),
            }),
            evidence,
        };
        if let Some(output) = &self.foreign_output {
            observation.target.output_id = output.clone();
        }
        Ok(observation)
    }
}

fn driver(action: HcsnTaskFlowActionV1) -> HcsnTaskFlowDriver<ProbeSupervisor> {
    HcsnTaskFlowDriver::new(
        SCOPE.to_string(),
        action,
        ProbeSupervisor {
            commands: Vec::new(),
            state: Ok(HcsnJobStateV1::Running),
            foreign_output: None,
        },
    )
    .expect("driver")
}

fn intent(action: HcsnTaskFlowActionV1, payload: &[u8]) -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: "run-one".to_string(),
        step_id: match action {
            HcsnTaskFlowActionV1::Start => "training",
            HcsnTaskFlowActionV1::Cancel => "cancel-training",
        }
        .to_string(),
        attempt: 1,
        operation_id: action.operation_id().to_string(),
        subject_id: "agent-one".to_string(),
        destination_id: SCOPE.to_string(),
        payload_digest: Sha256Digest::for_bytes(payload),
        final_use_scope_digest: Sha256Digest::for_bytes(b"hcsn-scope"),
        policy_generation: 7,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

fn dispatch(
    driver: &mut HcsnTaskFlowDriver<ProbeSupervisor>,
    intent: &AuthorizedEffectIntent,
    payload: &[u8],
) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
    driver.dispatch(&AuthorizedEffectRequest {
        operation_intent: &intent.operation_intent_v1().expect("operation"),
        intent,
        intent_digest: &intent.digest().expect("intent digest"),
        wire_payload: payload,
        binding: &intent.final_use_binding().expect("binding"),
    })
}

fn pending(intent: &AuthorizedEffectIntent) -> AuthorizedEffectPending {
    AuthorizedEffectPending {
        run_id: intent.run_id.clone(),
        step_id: intent.step_id.clone(),
        attempt: intent.attempt,
        intent_digest: intent.digest().expect("digest"),
        payload_digest: intent.payload_digest.clone(),
        binding_digest: Sha256Digest::for_bytes(b"owner-durable-binding"),
        destination_id: intent.destination_id.clone(),
        authority_epoch: 7,
        grant_id: "training-grant".to_string(),
        started_at_ms: 1,
    }
}

#[test]
fn partial_failure_and_cancellation_are_terminal_effects_not_absence() {
    let intent = intent(HcsnTaskFlowActionV1::Start, PAYLOAD);
    let mut driver = driver(HcsnTaskFlowActionV1::Start);
    for (state, outcome) in [
        (
            HcsnJobStateV1::Succeeded,
            AuthorizedEffectOutcome::Succeeded,
        ),
        (HcsnJobStateV1::Failed, AuthorizedEffectOutcome::Failed),
        (HcsnJobStateV1::Cancelled, AuthorizedEffectOutcome::Failed),
        (
            HcsnJobStateV1::Reserved,
            AuthorizedEffectOutcome::Indeterminate,
        ),
        (
            HcsnJobStateV1::Running,
            AuthorizedEffectOutcome::Indeterminate,
        ),
        (
            HcsnJobStateV1::Unknown,
            AuthorizedEffectOutcome::Indeterminate,
        ),
    ] {
        driver.supervisor.state = Ok(state);
        assert_eq!(
            dispatch(&mut driver, &intent, PAYLOAD)
                .expect("receipt")
                .outcome,
            outcome
        );
    }
}

#[test]
fn lost_or_foreign_receipt_stays_unknown_and_recovery_only_queries() {
    let intent = intent(HcsnTaskFlowActionV1::Start, PAYLOAD);
    let mut driver = driver(HcsnTaskFlowActionV1::Start);
    driver.supervisor.state = Err(HcsnSupervisorError::Unknown);
    assert_eq!(
        dispatch(&mut driver, &intent, PAYLOAD)
            .expect("unknown receipt")
            .outcome,
        AuthorizedEffectOutcome::Indeterminate
    );
    let original = driver.supervisor.commands[0].clone();
    assert_eq!(
        driver.lookup(&pending(&intent), PAYLOAD),
        AuthorizedProviderEffectLookup::Unresolved
    );
    driver.supervisor.state = Ok(HcsnJobStateV1::Succeeded);
    driver.supervisor.foreign_output = Some(Sha256Digest::for_bytes(b"foreign-output"));
    assert_eq!(
        driver.lookup(&pending(&intent), PAYLOAD),
        AuthorizedProviderEffectLookup::Unresolved
    );
    driver.supervisor.foreign_output = None;
    assert!(matches!(
        driver.lookup(&pending(&intent), PAYLOAD),
        AuthorizedProviderEffectLookup::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            ..
        })
    ));
    assert_eq!(
        driver.supervisor.commands,
        vec![
            original.clone(),
            original.status(),
            original.status(),
            original.status()
        ]
    );
}

#[test]
fn payload_scope_and_binding_mismatches_never_contact_supervisor() {
    let intent = intent(HcsnTaskFlowActionV1::Start, PAYLOAD);
    let mut driver = driver(HcsnTaskFlowActionV1::Start);
    assert_eq!(
        dispatch(&mut driver, &intent, b"{}"),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    let mut foreign = intent.clone();
    foreign.destination_id = "provider:foreign".to_string();
    assert_eq!(
        dispatch(&mut driver, &foreign, PAYLOAD),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    let mut binding = intent.final_use_binding().expect("binding");
    binding.payload_sha256[0] ^= 1;
    assert_eq!(
        driver.dispatch(&AuthorizedEffectRequest {
            operation_intent: &intent.operation_intent_v1().expect("operation"),
            intent: &intent,
            intent_digest: &intent.digest().expect("digest"),
            wire_payload: PAYLOAD,
            binding: &binding,
        }),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    assert_eq!(
        driver.lookup(&pending(&intent), b"{}"),
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(driver.supervisor.commands.is_empty());
}

#[test]
fn separately_authorized_cancel_keeps_both_dispatch_identities() {
    let original = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        "run-one",
        "training",
        Sha256Digest::for_bytes(PAYLOAD),
    )
    .expect("original job");
    let payload = serde_json::to_vec(&original).expect("cancel payload");
    let intent = intent(HcsnTaskFlowActionV1::Cancel, &payload);
    let mut driver = driver(HcsnTaskFlowActionV1::Cancel);
    driver.supervisor.state = Ok(HcsnJobStateV1::Cancelled);
    assert_eq!(
        dispatch(&mut driver, &intent, &payload)
            .expect("cancel receipt")
            .outcome,
        AuthorizedEffectOutcome::Succeeded
    );
    assert_eq!(
        driver.supervisor.commands,
        vec![HcsnSupervisorCommandV1 {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            action: HcsnSupervisorActionV1::Cancel,
            dispatch: HcsnJobIdentityV1::for_taskflow(
                SCOPE,
                "run-one",
                "cancel-training",
                Sha256Digest::for_bytes(&payload)
            )
            .expect("cancel identity"),
            target: original,
            payload: None,
        }]
    );
    driver.supervisor.state = Ok(HcsnJobStateV1::Succeeded);
    assert!(matches!(
        driver.lookup(&pending(&intent), &payload),
        AuthorizedProviderEffectLookup::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Failed,
            ..
        })
    ));
}
