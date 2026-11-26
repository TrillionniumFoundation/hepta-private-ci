//! Read whole original completed facts before the single original G effect.
use super::*;
use codex_hepta_agent_components::intelligence::materialize_completed_parameter_receipt_v1;
use codex_hepta_agent_components::intelligence_eval::inspect_unsigned_self_iteration_candidate_v1;
use codex_hepta_agent_components::learning_ledger::ReviewTrustWireV1;
use codex_hepta_agent_components::learning_ledger::activate_learning_trust;
use codex_hepta_agent_components::learning_ledger::execute_root_approved_frozen_generator;
use codex_hepta_agent_components::learning_ledger::observe_root_approved_frozen_generator;
use codex_hepta_agentd::AgentdSelfIterationCandidateEffectsV1;
use codex_hepta_agentd::self_iteration_generator_model_request_v1;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_supervisor::RootModelOutcomeReceiptV1;

use crate::CpuNeuronParameterAdviceContextV2;
use crate::CpuNeuronParameterRootMaterialsV2;
use crate::RootNativeAssessmentScopeV1;
use crate::describe_cpu_neuron_parameter_choices_v2;
use crate::validate_cpu_neuron_parameter_advice_v2;
use crate::validate_root_native_assessment_facts_v1;

impl RootFrozenGeneratorServiceV1 {
    pub(super) async fn issue(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        scope: &AgentScope,
        before: &SupervisordAgentStatus,
        client: &AgentdClient,
        status: &AgentdSelfIterationRoundStatusV1,
        payload: &[u8],
    ) -> Result<Option<SignedLearningEvidenceV1>> {
        let (material_source, canonical) = self.round_inputs(scope, &status.round)?;
        let materials = CpuNeuronParameterRootMaterialsV2::from_protected_source(
            &material_source,
            scope.worker_executable_digest.parse()?,
        )?;
        ensure!(
            materials.canonical_envelope().canonical_bytes() == canonical.canonical_bytes(),
            "whole original canonical material differs from independently installed policy"
        );
        let description = describe_cpu_neuron_parameter_choices_v2(
            materials.baseline().model_manifest_digest,
            materials.baseline().runtime.generation,
            materials.request(),
        )?;
        let objective_bytes = configuration::source(&scope.objective_prompt, 2048)?;
        let objective_prompt = std::str::from_utf8(&objective_bytes)?;
        let request = self_iteration_generator_model_request_v1(
            &status.round,
            materials.execution_envelope(),
            objective_prompt,
            &description,
        )?;
        let (generation, record) = client
            .native_model_receipt(request.request_id.to_string())
            .await?;
        current::validate_runtime_generation(before, generation)?;
        let Some(record) = record else {
            return Ok(None);
        };
        let record: NativeRunRecord = serde_json::from_str(&record)?;
        let RootModelOutcomeReceiptV1::Completed { receipt: witness } =
            RootModelOutcomeReceiptV1::read_original_protected(
                &self.configuration.terminal_receipt_directory,
                peer.subject(),
                request.request_id.as_str(),
            )?
        else {
            anyhow::bail!("original provider outcome was a failure");
        };
        self.admission.validate_historical_model_scope(
            peer,
            &witness.subject,
            &witness.cgroup,
            &witness.executable_sha256,
        )?;
        let now = now_ms()?;
        let assessment = validate_root_native_assessment_facts_v1(
            &request,
            &record,
            &witness,
            &RootNativeAssessmentScopeV1 {
                subject: peer.subject(),
                model: &scope.model,
                model_provider: &scope.model_provider,
                app_server_executable_digest: scope.app_server_executable_digest.parse()?,
                cgroup: &witness.cgroup,
                agentd_socket: self.layout.agent(&scope.agent_id).agentd_control_socket(),
                native_timeout_ms: u128::from(scope.native_timeout_ms),
            },
            now,
        )?;
        let (generation, observation) = client
            .plasticity_completed_proposal(materials.request().proposal_id.clone())
            .await?;
        current::validate_runtime_generation(before, generation)?;
        let Some(observation) = observation else {
            return Ok(None);
        };
        let wire: ReviewTrustWireV1 = serde_json::from_slice(&configuration::source(
            &self.configuration.generator_public_trust,
            64 * 1024,
        )?)?;
        let (root, distribution) = wire.native().map_err(|error| anyhow::anyhow!("{error}"))?;
        let trust = activate_learning_trust(&root, distribution, None, now)?;
        let receipt = materialize_completed_parameter_receipt_v1(
            materials.request(),
            &observation,
            trust.verifier(),
            now,
        )?;
        let selected = validate_cpu_neuron_parameter_advice_v2(
            CpuNeuronParameterAdviceContextV2 {
                envelope: materials.execution_envelope(),
                original_round: Some(&status.round),
            },
            materials.execution_envelope(),
            materials.request(),
            &assessment,
        )?;
        let (tick, port) = materials
            .candidate_canary(&selected)
            .context("selected original full canary material absent")?;
        let principal = codex_hepta_types::StableId::new("native-unprivileged-generator")?;
        let validate = |status: &AgentdSelfIterationRoundStatusV1, observed| {
            materials.with_plan(|plan| {
                validation::validate_original_generator_candidate(
                    payload,
                    &validation::OriginalGeneratorMaterials {
                        canonical: materials.canonical_envelope(),
                        independent_policy_pin: canonical.digest(),
                        plan,
                        admitted: &receipt,
                        generator_principal: &principal,
                        canary_tick: tick,
                        canary_port: port,
                    },
                    status,
                    &request,
                    &assessment,
                    observed,
                )
            })
        };
        let goal = StableId::new(status.round.goal_id())?;
        let fresh_status = self.status(scope, before, client, &goal).await?;
        let facts = validate(&fresh_status, now_ms()?)?;
        prepared::pair(client, before, &materials, &selected).await?;
        materials.revalidate_sources()?;
        trust.revalidate_at(now_ms()?)?;
        self.revalidate(stream, peer, scope, before).await?;
        let execution = execution::prepare(
            &self.configuration,
            peer.subject(),
            material_source.digest.parse()?,
            payload,
            &fresh_status,
            &facts,
        )?;
        // Recheck the original fence and protected sources immediately before G.
        materials.revalidate_sources()?;
        self.revalidate(stream, peer, scope, before).await?;
        let latest_status = self.status(scope, before, client, &goal).await?;
        let latest_facts = validate(&latest_status, now_ms()?)?;
        prepared::pair(client, before, &materials, &selected).await?;
        self.revalidate(stream, peer, scope, before).await?;
        ensure!(
            latest_facts.round_digest == facts.round_digest
                && latest_facts.payload_digest == facts.payload_digest
                && execution::observe(
                    &self.configuration,
                    peer.subject(),
                    material_source.digest.parse()?,
                    payload,
                    &latest_status,
                    &latest_facts
                )?
                .is_some(),
            "original admitted Generator window changed before execution"
        );
        let program = self.configuration.generator_program.path.clone();
        let evidence = tokio::task::spawn_blocking(move || {
            execute_root_approved_frozen_generator(&program, &execution.request, &execution.output)
                .map_err(|error| anyhow::anyhow!("{error}"))
        })
        .await??;
        self.revalidate(stream, peer, scope, before).await?;
        materials.revalidate_sources()?;
        trust.revalidate_at(now_ms()?)?;
        Ok(Some(evidence))
    }

    pub(super) async fn observe(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        scope: &AgentScope,
        before: &SupervisordAgentStatus,
        status: &AgentdSelfIterationRoundStatusV1,
        payload: &[u8],
    ) -> Result<Option<SignedLearningEvidenceV1>> {
        let now = now_ms()?;
        let candidate = inspect_unsigned_self_iteration_candidate_v1(payload, now)?;
        let (material_source, canonical) = self.round_inputs(scope, &status.round)?;
        ensure!(
            candidate.canonical_envelope_bytes() == Some(canonical.canonical_bytes())
                && candidate.generator_round_bytes()
                    == Some(status.round.canonical_bytes()?.as_slice())
                && status.round.canonical_policy_digest() == canonical.digest()
                && status.candidate_effects == AgentdSelfIterationCandidateEffectsV1::Started
                && status.rejected_proposal.is_none()
                && status
                    .frozen_digest
                    .is_none_or(|digest| digest == candidate.payload_digest())
                && status.generator_request_id.as_ref() == candidate.generator_model_request_id()
                && status.generator_native_run_digest == candidate.generator_native_run_digest()
                && status.generator_output_digest == candidate.generator_model_output_digest(),
            "original immutable observation differs from its actual round"
        );
        let facts = validation::OriginalGeneratorFacts {
            payload_digest: candidate.payload_digest(),
            round_digest: status.round.identity_digest(),
            expires_at_ms: status.round.deadline_ms(),
        };
        let Some(execution) = execution::observe(
            &self.configuration,
            peer.subject(),
            material_source.digest.parse()?,
            payload,
            status,
            &facts,
        )?
        else {
            return Ok(None);
        };
        self.revalidate(stream, peer, scope, before).await?;
        let program = self.configuration.generator_program.path.clone();
        let evidence = tokio::task::spawn_blocking(move || {
            observe_root_approved_frozen_generator(&program, &execution.request, &execution.output)
                .map_err(|error| anyhow::anyhow!("{error}"))
        })
        .await??;
        self.revalidate(stream, peer, scope, before).await?;
        Ok(evidence)
    }
}
