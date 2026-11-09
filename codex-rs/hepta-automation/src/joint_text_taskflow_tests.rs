//! Data-only effect probes: no registered owner, signed grant or worker run is
//! manufactured here. Real permission remains with the original effect host.

use super::*;
use crate::authorized_effect::AuthorizedEffectIntent;
use crate::joint_text_job::JointTextFileDigestV1;
use crate::joint_text_job::JointTextInputManifestV1;
use crate::joint_text_job::JointTextInputRefV1;
use crate::joint_text_job::JointTextJobEvidenceV1;
use crate::joint_text_job::JointTextProfileV1;
use crate::joint_text_job::JointTextSupervisorActionV1;
use pretty_assertions::assert_eq;

const SCOPE: &str = "provider:joint-text";

struct Probe {
    commands: Vec<JointTextJobCommandV1>,
    observed: Result<JointTextJobStateV1, JointTextSupervisorError>,
}

impl JointTextSupervisor for Probe {
    fn exchange(
        &mut self,
        command: &JointTextJobCommandV1,
    ) -> Result<JointTextJobObservationV1, JointTextSupervisorError> {
        self.commands.push(command.clone());
        let state = self.observed?;
        let evidence = match state {
            JointTextJobStateV1::Failed | JointTextJobStateV1::Cancelled => {
                Some(JointTextJobEvidenceV1::Stopped {
                    terminal: JointTextFileDigestV1 {
                        sha256: Sha256Digest::for_bytes(b"terminal"),
                        bytes: 8,
                    },
                })
            }
            JointTextJobStateV1::Reserved
            | JointTextJobStateV1::Running
            | JointTextJobStateV1::Succeeded
            | JointTextJobStateV1::Unknown => None,
        };
        Ok(JointTextJobObservationV1 {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            dispatch: command.dispatch.clone(),
            target: command.target.clone(),
            state,
            process: None,
            evidence,
        })
    }
}

fn payload() -> Vec<u8> {
    JointTextInputRefV1::from_manifest(JointTextInputManifestV1 {
        schema_version: 1,
        profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
        request_sha256: Sha256Digest::for_bytes(b"request"),
        request_bytes: 7,
        request_binding_digest: Sha256Digest::for_bytes(b"framed binding"),
        predecessor_sha256: Sha256Digest::for_bytes(b"packet"),
        predecessor_bytes: 6,
        worker_execution_source_digest: Sha256Digest::for_bytes(b"worker source"),
    })
    .expect("descriptor")
    .encode()
    .expect("payload")
}

fn intent(action: JointTextTaskFlowActionV1, payload: &[u8]) -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: "run-one".to_owned(),
        step_id: match action {
            JointTextTaskFlowActionV1::Start => "training",
            JointTextTaskFlowActionV1::Cancel => "cancel-training",
        }
        .to_owned(),
        attempt: 1,
        operation_id: action.operation_id().to_owned(),
        subject_id: "agent-one".to_owned(),
        destination_id: SCOPE.to_owned(),
        payload_digest: Sha256Digest::for_bytes(payload),
        final_use_scope_digest: Sha256Digest::for_bytes(b"joint scope"),
        policy_generation: 7,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

fn dispatch(
    driver: &mut JointTextTaskFlowDriver<Probe>,
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

#[test]
fn lost_ack_lookup_queries_only_the_original_dispatch_and_preserves_failure() {
    let payload = payload();
    let intent = intent(JointTextTaskFlowActionV1::Start, &payload);
    let mut driver = JointTextTaskFlowDriver::new(
        SCOPE.to_owned(),
        JointTextTaskFlowActionV1::Start,
        Probe {
            commands: Vec::new(),
            observed: Err(JointTextSupervisorError::Unknown),
        },
    )
    .expect("driver");
    assert_eq!(
        dispatch(&mut driver, &intent, &payload)
            .expect("unknown")
            .outcome,
        AuthorizedEffectOutcome::Indeterminate
    );
    let original = driver.supervisor.commands[0].clone();
    let pending = AuthorizedEffectPending {
        run_id: intent.run_id.clone(),
        step_id: intent.step_id.clone(),
        attempt: intent.attempt,
        intent_digest: intent.digest().expect("digest"),
        payload_digest: intent.payload_digest.clone(),
        binding_digest: Sha256Digest::for_bytes(b"original owner binding"),
        destination_id: SCOPE.to_owned(),
        authority_epoch: 7,
        grant_id: "original-grant".to_owned(),
        started_at_ms: 1,
    };
    assert_eq!(
        driver.lookup(&pending, &payload),
        AuthorizedProviderEffectLookup::Unresolved
    );
    driver.supervisor.observed = Ok(JointTextJobStateV1::Failed);
    assert!(matches!(
        driver.lookup(&pending, &payload),
        AuthorizedProviderEffectLookup::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Failed,
            ..
        })
    ));
    assert_eq!(
        driver.supervisor.commands,
        vec![original.clone(), original.status(), original.status()]
    );
}

#[test]
fn old_operation_wrong_payload_and_wrong_final_use_binding_do_not_contact() {
    let payload = payload();
    let mut intent = intent(JointTextTaskFlowActionV1::Start, &payload);
    let mut driver = JointTextTaskFlowDriver::new(
        SCOPE.to_owned(),
        JointTextTaskFlowActionV1::Start,
        Probe {
            commands: Vec::new(),
            observed: Ok(JointTextJobStateV1::Reserved),
        },
    )
    .expect("driver");
    intent.operation_id = "hcsn.training.start".to_owned();
    assert_eq!(
        dispatch(&mut driver, &intent, &payload),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    intent.operation_id = JointTextTaskFlowActionV1::Start.operation_id().to_owned();
    assert_eq!(
        dispatch(&mut driver, &intent, b"{}"),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    let mut binding = intent.final_use_binding().expect("binding");
    binding.payload_sha256[0] ^= 1;
    assert_eq!(
        driver.dispatch(&AuthorizedEffectRequest {
            operation_intent: &intent.operation_intent_v1().expect("operation"),
            intent: &intent,
            intent_digest: &intent.digest().expect("intent"),
            wire_payload: &payload,
            binding: &binding,
        }),
        Err(AuthorizedEffectDriverError::BeforeProviderContact)
    );
    assert!(driver.supervisor.commands.is_empty());
}

#[test]
fn separately_authorized_cancel_preserves_target_and_cannot_accept_partial_success() {
    let original_payload = payload();
    let target = JointTextJobIdentityV1::for_taskflow(
        SCOPE,
        "run-one",
        "training",
        Sha256Digest::for_bytes(&original_payload),
    )
    .expect("target");
    let payload = serde_json::to_vec(&target).expect("cancel payload");
    let intent = intent(JointTextTaskFlowActionV1::Cancel, &payload);
    let mut driver = JointTextTaskFlowDriver::new(
        SCOPE.to_owned(),
        JointTextTaskFlowActionV1::Cancel,
        Probe {
            commands: Vec::new(),
            observed: Ok(JointTextJobStateV1::Cancelled),
        },
    )
    .expect("driver");
    assert_eq!(
        dispatch(&mut driver, &intent, &payload)
            .expect("cancel receipt")
            .outcome,
        AuthorizedEffectOutcome::Succeeded
    );
    let command = &driver.supervisor.commands[0];
    assert_eq!(command.target, target);
    assert_eq!(command.action, JointTextSupervisorActionV1::Cancel);
    assert_ne!(command.dispatch.key, command.target.key);
    driver.supervisor.observed = Ok(JointTextJobStateV1::Succeeded);
    assert_eq!(
        dispatch(&mut driver, &intent, &payload)
            .expect("partial success refused")
            .outcome,
        AuthorizedEffectOutcome::Indeterminate
    );
}
