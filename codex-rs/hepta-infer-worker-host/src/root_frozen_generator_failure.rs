//! Read-only failure facts join the same admitted round, native owner and Root
//! relay publications. A late fact settles no physical effect in this service.
use super::*;
use codex_hepta_agentd::self_iteration_model_request_digest_v1;
use codex_hepta_infer_core::SelfIterationModelFailureFactsV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_supervisor::RootModelOutcomeReceiptV1;

impl RootFrozenGeneratorServiceV1 {
    pub(super) async fn observe_model_failure(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        wire: SelfIterationModelFailureObservationRequestV1,
    ) -> SelfIterationModelFailureObservationResponseV1 {
        let result = async {
            let request = wire.request().map_err(|error| anyhow::anyhow!("{error}"))?;
            let id = AgentId::parse(peer.subject())?;
            let scope = self
                .configuration
                .agents
                .iter()
                .find(|scope| scope.agent_id == id)
                .context("original failure Agent scope absent")?;
            let before = self.current(scope, peer).await?;
            let client = AgentdClient::new(
                self.layout
                    .agent(&scope.agent_id)
                    .agentd_control_socket()
                    .to_owned(),
                scope.agent_id.clone(),
                before
                    .spawn_generation
                    .context("original spawn generation absent")?,
            )?
            .with_peer_process(peer.uid(), peer.pid())?;
            let (generation, current) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(&before, generation)?;
            let Some(current) = current else {
                return Ok(None);
            };
            let status = current.status;
            let (_, canonical) = self.round_inputs(scope, &status.round)?;
            ensure!(
                status.round.canonical_policy_digest() == canonical.digest(),
                "original failure policy differs from installed Root source"
            );
            validate_request(&status, &request)?;
            let (generation, record) = client
                .native_model_receipt(request.request_id.to_string())
                .await?;
            current::validate_runtime_generation(&before, generation)?;
            let Some(record) = record else {
                return Ok(None);
            };
            let native_record: NativeRunRecord = serde_json::from_str(&record)?;
            let (outcome, root_outcome_bytes) =
                RootModelOutcomeReceiptV1::read_original_protected_with_bytes(
                    &self.configuration.terminal_receipt_directory,
                    peer.subject(),
                    request.request_id.as_str(),
                )?;
            let RootModelOutcomeReceiptV1::Failed { admission, .. } = &outcome else {
                return Ok(None);
            };
            self.admission.validate_historical_model_scope(
                peer,
                &admission.subject,
                &admission.cgroup,
                &admission.executable_sha256,
            )?;
            let facts = SelfIterationModelFailureFactsV1 {
                request: request.clone(),
                native_record,
                root_outcome_bytes,
                observed_at_ms: now_ms()?,
            };
            crate::validate_root_native_failure_facts_v1(
                &facts,
                &crate::RootNativeAssessmentScopeV1 {
                    subject: peer.subject(),
                    model: &scope.model,
                    model_provider: &scope.model_provider,
                    app_server_executable_digest: scope.app_server_executable_digest.parse()?,
                    cgroup: &admission.cgroup,
                    agentd_socket: self.layout.agent(&scope.agent_id).agentd_control_socket(),
                    native_timeout_ms: u128::from(scope.native_timeout_ms),
                },
            )?;
            // Return only a stable observation. No dispatch, clock extension,
            // reconciliation, journal open or issuer is involved in this route.
            self.revalidate(stream, peer, scope, &before).await?;
            let (generation, fresh) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(&before, generation)?;
            let fresh = fresh.context("original failure round disappeared")?.status;
            validate_request(&fresh, &request)?;
            ensure!(
                fresh.round == status.round && fresh.model_stages == status.model_stages,
                "original model stages changed during failure observation"
            );
            let (generation, final_record) = client
                .native_model_receipt(request.request_id.to_string())
                .await?;
            current::validate_runtime_generation(&before, generation)?;
            ensure!(
                final_record.as_deref() == Some(record.as_str())
                    && RootModelOutcomeReceiptV1::read_original_protected_with_bytes(
                        &self.configuration.terminal_receipt_directory,
                        peer.subject(),
                        request.request_id.as_str(),
                    )?
                    .1 == facts.root_outcome_bytes,
                "original failed publications changed during observation"
            );
            self.revalidate(stream, peer, scope, &before).await?;
            Ok::<_, anyhow::Error>(Some(
                SelfIterationModelFailureObservationFactsV1::from_facts(&facts)
                    .map_err(|error| anyhow::anyhow!("{error}"))?,
            ))
        }
        .await;
        match result {
            Ok(Some(facts)) => SelfIterationModelFailureObservationResponseV1::Facts(facts),
            Ok(None) => failure_refused(FrozenGeneratorErrorCodeV1::Pending),
            Err(_) => failure_refused(FrozenGeneratorErrorCodeV1::Unavailable),
        }
    }
}

fn failure_refused(
    error: FrozenGeneratorErrorCodeV1,
) -> SelfIterationModelFailureObservationResponseV1 {
    SelfIterationModelFailureObservationResponseV1::Refused(FrozenGeneratorFailureV1 { error })
}

fn validate_request(
    status: &AgentdSelfIterationRoundStatusV1,
    request: &SelfIterationModelRequestV1,
) -> Result<()> {
    status.to_json()?;
    request.validate(
        request
            .deadline_ms
            .checked_sub(1)
            .context("original model deadline absent")?,
    )?;
    let role = match request.role {
        SelfIterationModelRoleV1::Generator => 0,
        SelfIterationModelRoleV1::Evaluator => 1,
        SelfIterationModelRoleV1::Selector => 2,
        SelfIterationModelRoleV1::Observer => 3,
    };
    let stage = status
        .model_stages
        .get(role)
        .context("original model stage was not admitted")?;
    ensure!(
        request.request_id.as_str() == stage.request_id
            && request.candidate_digest == stage.candidate_digest
            && self_iteration_model_request_digest_v1(request) == stage.request_digest
            && request.envelope_digest == status.round.execution_envelope_digest()
            && request.deadline_ms == status.round.deadline_ms()
            && stage.output_digest.is_none()
            && stage.native_run_digest.is_none(),
        "failure request differs from the entire original admitted model stage"
    );
    Ok(())
}
