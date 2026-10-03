//! Join a lookup tuple to the complete original completed model request.
use super::*;
use codex_hepta_agentd::self_iteration_model_request_digest_v1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_supervisor::RootModelOutcomeReceiptV1;

pub(super) struct CompletedBinding {
    request: SelfIterationModelRequestV1,
    native_bytes: String,
    root_bytes: Vec<u8>,
}
pub(super) async fn completed(
    service: &RootFrozenGeneratorServiceV1,
    peer: &RootAdmittedFleetPeerV1,
    scope: &AgentScope,
    before: &SupervisordAgentStatus,
    client: &AgentdClient,
    status: &AgentdSelfIterationRoundStatusV1,
    wire: &SelfIterationOwnerRequestV1,
) -> Result<Option<CompletedBinding>> {
    let role = match wire.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => 1,
        SelfIterationOwnerPurposeV1::Select => 2,
        SelfIterationOwnerPurposeV1::Observe => 3,
    };
    let stage = status
        .model_stages
        .get(role)
        .context("original role model stage absent")?;
    ensure!(
        stage.role as usize == role
            && stage.failure.is_none()
            && stage.request_id == wire.model_facts.request_id
            && stage
                .candidate_digest
                .map(|value| value.to_string())
                .as_deref()
                == Some(wire.model_facts.candidate_digest.as_str())
            && stage
                .output_digest
                .map(|value| value.to_string())
                .as_deref()
                == Some(wire.model_facts.output_digest.as_str())
            && stage
                .native_run_digest
                .map(|value| value.to_string())
                .as_deref()
                == Some(wire.model_facts.native_run_digest.as_str())
            && status.round.execution_envelope_digest().to_string()
                == wire.model_facts.envelope_digest,
        "caller lookup differs from full original durable completed role stage"
    );
    let (generation, bytes) = client
        .native_model_receipt(stage.request_id.clone())
        .await?;
    current::validate_runtime_generation(before, generation)?;
    let Some(bytes) = bytes else {
        return Ok(None);
    };
    let record: NativeRunRecord = serde_json::from_str(&bytes)?;
    let (outcome, root_bytes) = RootModelOutcomeReceiptV1::read_original_protected_with_bytes(
        &service.configuration.terminal_receipt_directory,
        peer.subject(),
        &stage.request_id,
    )?;
    let RootModelOutcomeReceiptV1::Completed { receipt: witness } = outcome else {
        return Ok(None);
    };
    let request =
        crate::self_iteration_model_request_from_native_prompt_v1(&witness.native_prompt)?;
    let expected = match wire.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => SelfIterationModelRoleV1::Evaluator,
        SelfIterationOwnerPurposeV1::Select => SelfIterationModelRoleV1::Selector,
        SelfIterationOwnerPurposeV1::Observe => SelfIterationModelRoleV1::Observer,
    };
    ensure!(
        request.role == expected
            && request.request_id.as_str() == stage.request_id
            && request.candidate_digest == stage.candidate_digest
            && request.envelope_digest == status.round.execution_envelope_digest()
            && request.deadline_ms == status.round.deadline_ms()
            && self_iteration_model_request_digest_v1(&request) == stage.request_digest,
        "Root-observed exact native prompt differs from original admitted request"
    );
    service.admission.validate_historical_model_scope(
        peer,
        &witness.subject,
        &witness.cgroup,
        &witness.executable_sha256,
    )?;
    let assessment = crate::validate_root_native_assessment_facts_v1(
        &request,
        &record,
        &witness,
        &crate::RootNativeAssessmentScopeV1 {
            subject: peer.subject(),
            model: &scope.model,
            model_provider: &scope.model_provider,
            app_server_executable_digest: scope.app_server_executable_digest.parse()?,
            cgroup: &witness.cgroup,
            agentd_socket: service
                .layout
                .agent(&scope.agent_id)
                .agentd_control_socket(),
            native_timeout_ms: u128::from(scope.native_timeout_ms),
        },
        now_ms()?,
    )?;
    ensure!(
        assessment.native_run_digest.to_string() == wire.model_facts.native_run_digest
            && Digest32::of_bytes(assessment.model_output.as_bytes()).to_string()
                == wire.model_facts.output_digest,
        "actual completed native output differs from original journal"
    );
    Ok(Some(CompletedBinding {
        request,
        native_bytes: bytes,
        root_bytes,
    }))
}
pub(super) async fn revalidate(
    service: &RootFrozenGeneratorServiceV1,
    peer: &RootAdmittedFleetPeerV1,
    client: &AgentdClient,
    before: &SupervisordAgentStatus,
    original: &CompletedBinding,
) -> Result<()> {
    original.request.validate(now_ms()?)?;
    let (generation, native) = client
        .native_model_receipt(original.request.request_id.to_string())
        .await?;
    current::validate_runtime_generation(before, generation)?;
    ensure!(
        native.as_deref() == Some(original.native_bytes.as_str())
            && RootModelOutcomeReceiptV1::read_original_protected_with_bytes(
                &service.configuration.terminal_receipt_directory,
                peer.subject(),
                original.request.request_id.as_str(),
            )?
            .1 == original.root_bytes,
        "same original native/Root whole publications changed"
    );
    Ok(())
}
