//! Compose original factual readers and the isolated Generator in the existing
//! Linux bridge. This owner has no credential or private signing-key reader.
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::frozen_generator_wire::*;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdSelfIterationRoundStatusV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::RootAdmittedFleetPeerV1;
use codex_hepta_supervisor::RootFleetPeerAdmissionV1;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_types::StableId;
use tokio::net::UnixStream;

#[path = "root_frozen_generator_configuration.rs"]
mod configuration;
#[path = "root_frozen_generator_current.rs"]
mod current;
#[path = "root_frozen_generator_execution.rs"]
mod execution;
#[path = "root_frozen_generator_facts.rs"]
mod facts;
#[path = "root_frozen_generator_failure.rs"]
mod failure;
#[path = "root_self_iteration_owners.rs"]
mod independent_owners;
#[path = "root_round_preparation.rs"]
mod preparation;
#[path = "root_frozen_generator_prepared.rs"]
mod prepared;
#[path = "root_frozen_generator_recipe.rs"]
pub(crate) mod recipe;
#[path = "root_frozen_generator_server.rs"]
mod server;
#[path = "root_frozen_generator_validation.rs"]
mod validation;

use configuration::AgentScope;
use configuration::Configuration;

pub(super) enum GeneratorPublication {
    Issue(FrozenGeneratorRequestV1),
    Observe(FrozenGeneratorObservationRequestV2),
}

pub struct RootFrozenGeneratorServiceV1 {
    configuration_path: PathBuf,
    configuration_bytes: Vec<u8>,
    configuration: Configuration,
    admission: RootFleetPeerAdmissionV1,
    layout: HeptaFleetLayout,
    supervisor: SupervisordClient,
    issuance: tokio::sync::Semaphore,
}

impl RootFrozenGeneratorServiceV1 {
    pub async fn open(path: PathBuf) -> Result<Self> {
        let (configuration, configuration_bytes) = Configuration::read(&path)?;
        let admission =
            RootFleetPeerAdmissionV1::open(&configuration.model_authority_policy).await?;
        let layout = HeptaFleetRoot::parse(&configuration.fleet_root)?.layout();
        let supervisor =
            SupervisordClient::new(layout.supervisor_socket().to_owned())?.with_owner_uid(0);
        Ok(Self {
            configuration_path: path,
            configuration_bytes,
            configuration,
            admission,
            layout,
            supervisor,
            issuance: tokio::sync::Semaphore::new(1),
        })
    }

    pub async fn serve(self) -> Result<()> {
        server::serve(Arc::new(self)).await
    }

    pub(super) fn socket(&self) -> &Path {
        &self.configuration.socket
    }

    pub(super) fn socket_group(&self) -> u32 {
        self.configuration.socket_group
    }

    fn configuration_current(&self) -> Result<()> {
        ensure!(
            RootFleetPeerAdmissionV1::read_protected_source(
                &self.configuration_path,
                64 * 1024,
                /*private*/ true,
            )? == self.configuration_bytes,
            "original Generator composition changed"
        );
        Ok(())
    }

    pub(super) async fn admit(&self, stream: &UnixStream) -> Result<RootAdmittedFleetPeerV1> {
        self.configuration_current()?;
        self.admission.admit(stream).await
    }

    async fn current(
        &self,
        scope: &AgentScope,
        peer: &RootAdmittedFleetPeerV1,
    ) -> Result<SupervisordAgentStatus> {
        let current = current::read(&self.supervisor, &scope.agent_id, peer).await?;
        ensure!(
            current.current_release.as_ref() == Some(&scope.current_release)
                && peer.executable_sha256() == scope.agent_executable_digest,
            "current original Agent differs from installed Generator composition"
        );
        Ok(current)
    }

    async fn revalidate(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        scope: &AgentScope,
        before: &SupervisordAgentStatus,
    ) -> Result<()> {
        self.configuration_current()?;
        self.admission.revalidate(stream, peer).await?;
        current::unchanged(before, &self.current(scope, peer).await?)
    }

    async fn status(
        &self,
        scope: &AgentScope,
        current: &SupervisordAgentStatus,
        client: &AgentdClient,
        goal: &StableId,
    ) -> Result<AgentdSelfIterationRoundStatusV1> {
        if scope.round_blueprint.is_some() {
            let (generation, round) = client.self_iteration_current_round().await?;
            current::validate_runtime_generation(current, generation)?;
            let status = round.context("original current round unavailable")?.status;
            let (_, canonical) = self.round_inputs(scope, &status.round)?;
            ensure!(
                status.round.goal_id() == goal.as_str()
                    && status.round.canonical_policy_digest() == canonical.digest(),
                "retained recipe differs from the original Goal and policy"
            );
            return Ok(status);
        }
        let canonical = configuration::canonical_policy(&scope.canonical)?;
        let (generation, status) = client
            .self_iteration_round_status(goal.clone(), canonical.digest())
            .await?;
        current::validate_runtime_generation(current, generation)?;
        Ok(status)
    }

    pub(super) async fn dispatch(
        &self,
        stream: &UnixStream,
        peer: &RootAdmittedFleetPeerV1,
        operation: GeneratorPublication,
    ) -> FrozenGeneratorResponseV1 {
        let result = async {
            let id = AgentId::parse(peer.subject())?;
            let scope = self.configuration.agents.iter().find(|scope| scope.agent_id == id)
                .context("original Generator Agent scope absent")?;
            let before = self.current(scope, peer).await?;
            let client = AgentdClient::new(
                self.layout.agent(&scope.agent_id).agentd_control_socket().to_owned(),
                scope.agent_id.clone(),
                before.spawn_generation.context("original spawn generation absent")?,
            )?.with_peer_process(peer.uid(), peer.pid())?;
            let payload = match &operation {
                GeneratorPublication::Issue(request) => request.payload(),
                GeneratorPublication::Observe(request) => request.payload(),
            }.map_err(|error| anyhow::anyhow!("{error}"))?;
            let candidate = codex_hepta_agent_components::intelligence_eval::inspect_unsigned_self_iteration_candidate_v1(&payload, now_ms()?)?;
            // Caller bytes only name an observation. The original authenticated
            // owner must return this exact whole round under the independent policy.
            let round = codex_hepta_agentd::AgentdSelfIterationRoundV1::decode(
                candidate.generator_round_bytes().context("original full round absent")?,
            )?;
            let goal = StableId::new(round.goal_id())?;
            let status = self.status(scope, &before, &client, &goal).await?;
            ensure!(status.round == round, "candidate names another original round");
            self.revalidate(stream, peer, scope, &before).await?;
            match operation {
                GeneratorPublication::Issue(_) => {
                    // Full model materials stay within the installed service's
                    // memory budget while read-only observations remain available.
                    let _issuance = self.issuance.acquire().await?;
                    self.revalidate(stream, peer, scope, &before).await?;
                    self.issue(stream, peer, scope, &before, &client, &status, &payload).await
                }
                GeneratorPublication::Observe(_) => {
                    self.observe(stream, peer, scope, &before, &status, &payload).await
                }
            }
        }.await;
        match result {
            Ok(Some(evidence)) => FrozenGeneratorResponseV1::Granted(Box::new(
                ReviewEvidenceWireV1::from_native(&evidence),
            )),
            Ok(None) => refused(FrozenGeneratorErrorCodeV1::Pending),
            Err(_) => refused(FrozenGeneratorErrorCodeV1::Unavailable),
        }
    }
}

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}

fn refused(error: FrozenGeneratorErrorCodeV1) -> FrozenGeneratorResponseV1 {
    FrozenGeneratorResponseV1::Refused(FrozenGeneratorFailureV1 { error })
}

#[path = "root_parameter_evaluation_pipeline.rs"]
mod parameter_evaluation_pipeline;
pub use parameter_evaluation_pipeline::OriginalParameterEvaluationPreparationResultV1;
pub use parameter_evaluation_pipeline::OriginalParameterEvaluationPublicationsV1;
pub use parameter_evaluation_pipeline::OriginalParameterEvaluationTemplateV1;
pub use parameter_evaluation_pipeline::OriginalParameterRoleProgramV1;
pub use parameter_evaluation_pipeline::prepare_original_parameter_evaluation_publications_v1;
