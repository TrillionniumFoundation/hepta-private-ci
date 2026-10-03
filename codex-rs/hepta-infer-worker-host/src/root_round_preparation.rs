//! Observe the immutable prepared round on the original admitted Root route.
//! A missing or partial preparation cannot fall back to generation-one inputs.
use super::*;
use crate::CpuNeuronParameterRootMaterialsV2;
use crate::InstalledSelfIterationIndependentOwnersV1;
use crate::evolving_agentd::installed_cycle::InstalledRoundBundleV1;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agent_components::intelligence_eval::ParameterPreRegistrationPurposeV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_types::Digest32;

#[path = "root_round_admission.rs"]
mod admission_projection;
#[path = "root_round_blueprint.rs"]
mod blueprint;
#[path = "root_round_bundle.rs"]
mod bundle_publication;
#[path = "root_round_context.rs"]
mod context_projection;
#[path = "root_round_fresh.rs"]
mod fresh;
#[path = "root_round_original_facts.rs"]
mod original_facts;
#[path = "root_round_parameter_roles.rs"]
mod parameter_roles;
#[path = "root_round_publication_configuration.rs"]
mod publication_configuration;
#[path = "root_round_search.rs"]
mod search_projection;
#[path = "root_round_selection.rs"]
mod selection_projection;

impl RootFrozenGeneratorServiceV1 {
    pub(super) async fn prepare_round(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        request: RoundPreparationRequestV1,
    ) -> RoundPreparationResponseV1 {
        let payload = request.round_bytes().unwrap_or_default();
        let payload_digest = Digest32::of_bytes(&payload);
        let result = async {
            let round = AgentdSelfIterationRoundV1::decode(&payload)?;
            let subject = AgentId::parse(peer.subject())?;
            let scope = self.configuration.agents.iter()
                .find(|scope| scope.agent_id == subject)
                .context("original round-preparation Agent scope absent")?;
            let before = self.current(scope, peer).await?;
            let client = AgentdClient::new(
                self.layout.agent(&subject).agentd_control_socket().to_owned(),
                subject,
                before.spawn_generation.context("actual spawn generation absent")?,
            )?.with_peer_process(peer.uid(), peer.pid())?;
            let (generation, view) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(&before, generation)?;
            let status = view.context("original admitted round absent")?.status;
            let canonical = configuration::canonical_policy(&scope.canonical)?;
            ensure!(status.round == round
                && round.canonical_policy_digest() == canonical.digest(),
                "Root preparation differs from whole original reservation or policy");
            self.revalidate(stream, peer, scope, &before).await?;
            if let Some(terminal) = &status.preparation {
                let source = InstalledCpuSourceV1 {
                    path: terminal.source_path.clone(),
                    digest: terminal.source_digest.to_string(),
                };
                configuration::source(&source,
                    codex_hepta_agent_components::intelligence_eval::MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1)?;
                ensure!(terminal.facts()?.round_payload_digest == payload_digest,
                    "original preparation terminal names another complete round");
                self.revalidate(stream, peer, scope, &before).await?;
                return Ok(RoundPreparationResultV1::Terminal {
                    source: RoundPreparationSourceV1 { path: source.path, digest: source.digest },
                });
            }
            ensure!(!status.terminal && now_ms()? < round.deadline_ms(),
                "actual original round is terminal or expired");
            let _permit = self.issuance.acquire().await?;
            self.revalidate(stream, peer, scope, &before).await?;
            let directory = self.configuration.execution_directory
                .join(format!("round-materials-{}", round.identity_digest()));
            let path = directory.join("bundle.json");
            if !path.try_exists()?
                && let Some(blueprint_source) = &scope.round_blueprint
            {
                let prepared = fresh::Preparation {
                    service: self, blueprint_source, client: &client,
                    before: &before, scope, round: &round, canonical: &canonical,
                }.prepare().await?;
                self.revalidate(stream, peer, scope, &before).await?;
                if let Some(result) = prepared {
                    return Ok(result);
                }
            }
            if !path.try_exists()? {
                return Ok(RoundPreparationResultV1::Refused {
                    error: FrozenGeneratorErrorCodeV1::Pending,
                });
            }
            execution::protected_directory(&directory)?;
            let bytes = codex_hepta_supervisor::RootFleetPeerAdmissionV1::read_protected_source(
                &path, 64 * 1024, /*private*/ false)?;
            let bundle: InstalledRoundBundleV1 = serde_json::from_slice(&bytes)?;
            let recipe = recipe::retained(&self.configuration.execution_directory, &round)?;
            ensure!(bundle.schema == "hepta.installed-round-bundle.v1"
                && bundle.round == round
                && bundle.materials == recipe.materials
                && bundle.plasticity_context == recipe.plasticity_context,
                "whole prepared bundle differs from original immutable recipe");
            let materials = CpuNeuronParameterRootMaterialsV2::from_protected_source(
                &bundle.materials, scope.worker_executable_digest.parse()?)?;
            ensure!(materials.canonical_envelope().canonical_bytes() == canonical.canonical_bytes()
                && round.execution_envelope_digest()
                    == codex_hepta_agentd::self_iteration_envelope_digest_v1(materials.execution_envelope()),
                "whole preparation policy or execution changed");
            let frontier: std::collections::BTreeSet<_> = bundle.candidates.iter()
                .map(|entry| entry.candidate_id.as_str()).collect();
            ensure!(frontier.len() == bundle.candidates.len()
                && frontier.contains(bundle.rollback.candidate_id.as_str())
                && materials.with_plan(|plan| plan.candidates.len()) == frontier.len(),
                "prepared candidate and exact-rollback frontier changed");
            let validate = |source: &crate::evolving_agentd::installed_cycle::PreparedCandidateAdmissionV1,
                material: &crate::CpuNeuronGenerationPlanV1, purpose| -> Result<()> {
                let actual = crate::initial_cpu_anchor::inspect_parameter_pre_registered_admission_v1(
                    &source.configuration.path, source.configuration.digest.parse()?,
                    &source.selection.path, source.selection.digest.parse()?)
                    .map_err(|error| anyhow::anyhow!("{error}"))?;
                ensure!(actual.candidate_id().as_str() == source.candidate_id
                    && actual.purpose() == purpose
                    && actual.round().round_digest == round.identity_digest().to_string()
                    && actual.round().round_payload_digest == payload_digest.to_string()
                    && codex_hepta_neuron::encode_neuron_generation_material_v2(actual.material())
                        .map_err(|error| anyhow::anyhow!("{error}"))?
                        == codex_hepta_neuron::encode_neuron_generation_material_v2(material)
                            .map_err(|error| anyhow::anyhow!("{error}"))?,
                    "original E1/S3 differs from whole prepared material");
                actual.revalidate_current().map_err(|error| anyhow::anyhow!("{error}"))?;
                Ok(())
            };
            materials.with_plan(|plan| -> Result<()> {
                for candidate in plan.candidates {
                    let source = bundle.candidates.iter()
                        .find(|entry| entry.candidate_id == candidate.candidate_id.as_str())
                        .context("complete prepared candidate missing")?;
                    validate(source, candidate.generation, ParameterPreRegistrationPurposeV1::Candidate)?;
                }
                validate(&bundle.rollback, materials.rollback(), ParameterPreRegistrationPurposeV1::ExactRollback)
            })?;
            InstalledSelfIterationIndependentOwnersV1::from_protected_source(
                &bundle.independent_owners, round.clone(), &materials)?;
            materials.revalidate_sources()?;
            self.revalidate(stream, peer, scope, &before).await?;
            let (generation, after) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(&before, generation)?;
            let mut after = after.context("original round disappeared")?.status;
            ensure!(after.observed_clock_ms >= status.observed_clock_ms
                && after.observed_clock_ms < round.deadline_ms(), "actual observation clock crossed original window");
            after.observed_clock_ms = status.observed_clock_ms;
            ensure!(after == status
                && codex_hepta_supervisor::RootFleetPeerAdmissionV1::read_protected_source(
                    &path, 64 * 1024, /*private*/ false)? == bytes,
                "actual original preparation changed before return");
            Ok::<_, anyhow::Error>(RoundPreparationResultV1::Prepared {
                bundle: RoundPreparationSourceV1 { path, digest: Digest32::of_bytes(&bytes).to_string() },
            })
        }.await;
        RoundPreparationResponseV1 {
            schema_version: 8,
            round_payload_digest: payload_digest.to_string(),
            result: result.unwrap_or_else(|error| {
                eprintln!("original round preparation {payload_digest} unavailable: {error}");
                RoundPreparationResultV1::Refused {
                    error: FrozenGeneratorErrorCodeV1::Unavailable,
                }
            }),
        }
    }
}
