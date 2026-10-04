//! Finite E/S/O purposes inside the existing authenticated Root service.
//! Model suggestions are joined to original durable Native and protected
//! provider facts; only independently signed native outputs are returned.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agentd::AgentdSelfIterationRecordV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_types::Digest32;

#[path = "root_self_iteration_owners_native.rs"]
mod native;
#[path = "root_self_iteration_owners_execution.rs"]
pub(super) mod roles;

use crate::RootSelfIterationOwnersRoundConfigurationV1 as RoundConfiguration;
use crate::root_self_iteration_owners_configuration_path_v1;

impl RootFrozenGeneratorServiceV1 {
    pub(super) async fn dispatch_independent_owner(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        request: SelfIterationOwnerRequestV1,
    ) -> SelfIterationOwnerResponseV1 {
        let result = async {
            let subject = AgentId::parse(peer.subject())?;
            let scope = self
                .configuration
                .agents
                .iter()
                .find(|scope| scope.agent_id == subject)
                .context("original independent role Agent scope absent")?;
            let before = self.current(scope, peer).await?;
            let client = AgentdClient::new(
                self.layout
                    .agent(&scope.agent_id)
                    .agentd_control_socket()
                    .to_owned(),
                scope.agent_id.clone(),
                before.spawn_generation.context("actual spawn absent")?,
            )?
            .with_peer_process(peer.uid(), peer.pid())?;
            let (generation, current_round) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(&before, generation)?;
            let status = current_round
                .context("original admitted round absent")?
                .status;
            let (_, canonical) = self.round_inputs(scope, &status.round)?;
            let config_path = root_self_iteration_owners_configuration_path_v1(
                &self.configuration.execution_directory,
                &status.round,
            );
            let (config, config_bytes) = RoundConfiguration::read(&config_path, &status.round)?;
            let materials = crate::CpuNeuronParameterRootMaterialsV2::from_protected_source(
                &config.materials,
                scope.worker_executable_digest.parse()?,
            )?;
            ensure!(
                materials.canonical_envelope().canonical_bytes() == canonical.canonical_bytes(),
                "whole role material differs from independently installed canonical policy"
            );
            let guard = crate::InstalledSelfIterationIndependentOwnersV1::from_protected_source(
                &config.client_configuration,
                status.round.clone(),
                &materials,
            )?;
            let (consumer, record_bytes) = request
                .original_bytes()
                .map_err(|error| anyhow::anyhow!("{error}"))?;
            let record: AgentdSelfIterationRecordV1 = serde_json::from_slice(&record_bytes)?;
            guard.validate_consumer(&consumer, &record)?;
            let trust_bytes =
                configuration::source(&self.configuration.generator_public_trust, 64 * 1024)?;
            let trust_wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
            let (root, distribution) = trust_wire
                .native()
                .map_err(|error| anyhow::anyhow!("{error}"))?;
            let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
            let frozen =
                inspect_signed_self_iteration_frozen_consumer_v1(&consumer, &trust, now_ms()?)?;
            let actual_round = AgentdSelfIterationRoundV1::decode(
                frozen
                    .generator_round_bytes()
                    .context("full original signed round absent")?,
            )?;
            ensure!(
                actual_round == status.round
                    && !status.terminal
                    && status.frozen_digest == Some(frozen.frozen_digest()),
                "independent role differs from actual active frozen round"
            );
            let native_binding =
                native::completed(self, peer, scope, &before, &client, &status, &request).await?;
            let Some(native_binding) = native_binding else {
                return Ok(None);
            };
            let _permit = self.issuance.acquire(&scope.agent_id).await?;
            self.revalidate(stream, peer, scope, &before).await?;
            let goal = StableId::new(status.round.goal_id())?;
            let fresh_status = self.status(scope, &before, &client, &goal).await?;
            ensure!(
                fresh_status.round == status.round
                    && fresh_status.frozen_digest == status.frozen_digest
                    && fresh_status.model_stages == status.model_stages,
                "original role stage changed before effect"
            );
            native::revalidate(self, peer, &client, &before, &native_binding).await?;
            let directory = config_path
                .parent()
                .context("original round directory absent")?
                .join("independent-role-effects");
            roles::prepare_effect_directory(&directory)?;
            let consumer_source =
                roles::publish_consumer(&config, &consumer, frozen.frozen_digest())?;
            let input = roles::RoleInput {
                configuration: config.clone(),
                configuration_path: config_path.clone(),
                configuration_bytes: config_bytes.clone(),
                original_round: status.round.clone(),
                purpose: request.purpose,
                consumer: consumer_source,
                record,
                original_request_digest: Digest32::of_bytes(
                    &encode_self_iteration_owner_request_v1(&request)
                        .map_err(|error| anyhow::anyhow!("{error}"))?,
                ),
                directory,
                frozen_digest: frozen.frozen_digest(),
            };
            let canary = if request.purpose == SelfIterationOwnerPurposeV1::Observe {
                Some(roles::actual_canary(&client, &before, &materials, &input).await?)
            } else {
                None
            };
            let output = tokio::task::spawn_blocking(move || {
                roles::execute(input, canary).map_err(|error| anyhow::anyhow!("{error}"))
            })
            .await??;
            self.revalidate(stream, peer, scope, &before).await?;
            native::revalidate(self, peer, &client, &before, &native_binding).await?;
            materials.revalidate_sources()?;
            guard.validate_consumer(&consumer, &serde_json::from_slice(&record_bytes)?)?;
            trust.revalidate_at(now_ms()?)?;
            ensure!(
                RoundConfiguration::read(&config_path, &status.round)?.1 == config_bytes,
                "original finite role configuration changed during execution"
            );
            let Some(output) = output else {
                return Ok(None);
            };
            Ok::<_, anyhow::Error>(Some(
                SelfIterationOwnerGrantedV1::from_publication(
                    request.purpose,
                    frozen.frozen_digest(),
                    &output,
                )
                .map_err(|error| anyhow::anyhow!("{error}"))?,
            ))
        }
        .await;
        match result {
            Ok(Some(output)) => SelfIterationOwnerResponseV1::Granted(output),
            Ok(None) => SelfIterationOwnerResponseV1::Refused(FrozenGeneratorFailureV1 {
                error: FrozenGeneratorErrorCodeV1::Pending,
            }),
            Err(_) => SelfIterationOwnerResponseV1::Refused(FrozenGeneratorFailureV1 {
                error: FrozenGeneratorErrorCodeV1::Unavailable,
            }),
        }
    }
}
