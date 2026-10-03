//! Original Agentd and finite G/O preparation for the two publication phases.
//! Both borrow the same actual training/Serving facts and original sealed Round.
use super::*;
use codex_hepta_agent_components::intelligence::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_agent_components::plasticity::*;
use original_facts::OriginalFacts;

pub(super) struct Preparation<'a> {
    pub blueprint: &'a blueprint::Blueprint,
    pub facts: &'a OriginalFacts,
    pub client: &'a AgentdClient,
    pub before: &'a codex_hepta_supervisor::SupervisordAgentStatus,
    pub subject: &'a StableId,
    pub round: &'a AgentdSelfIterationRoundV1,
    pub canonical: &'a codex_hepta_agentd::CanonicalIterationEnvelopeV1,
    pub current: &'a RegisteredArtifactCurrentFactsV3,
    pub registration: &'a InstalledCpuSourceV1,
    pub snapshot: &'a InstalledCpuSourceV1,
    pub snapshot_receipt: RegistrySnapshotReceipt,
    pub phase: parameter_roles::AdmissionPhase,
}
impl Preparation<'_> {
    pub(super) async fn prepare(
        self,
    ) -> Result<Option<(ParameterPlasticityProductRequestV1, InstalledCpuSourceV1)>> {
        let spawn = self
            .before
            .spawn_generation
            .context("actual original spawn absent")?;
        let context = context_projection::project(
            self.blueprint,
            self.facts,
            self.subject,
            spawn,
            self.round,
            self.snapshot,
            self.snapshot_receipt,
            self.phase,
        )?;
        let (generation, input, admission, predecessor) = match self.phase {
            parameter_roles::AdmissionPhase::BeforeRegistration => {
                let (generation, input, admission, baseline) = self
                    .client
                    .prepare_parameter_input_from_context_v2(
                        self.round.clone(),
                        context.path.clone(),
                        context.digest.parse()?,
                        self.facts.search.path.clone(),
                        self.facts.search.digest.parse()?,
                    )
                    .await?;
                ensure!(
                    baseline.baseline.material_source
                        == self
                            .facts
                            .indexed
                            .material_source
                            .path
                            .to_str()
                            .context("original material path encoding")?
                        && baseline.baseline.material_digest
                            == self.facts.indexed.material_source.digest,
                    "same original full prepared baseline Source changed"
                );
                (
                    generation,
                    input,
                    admission,
                    baseline.proposal_registry_predecessor.parse::<Digest32>()?,
                )
            }
            parameter_roles::AdmissionPhase::AfterRegistration => {
                let generation = self
                    .client
                    .refresh_parameter_input_context_v2(
                        self.round.clone(),
                        context.path.clone(),
                        context.digest.parse()?,
                    )
                    .await?;
                current::validate_runtime_generation(self.before, generation)?;
                let (generation, input, admission, baseline) = self
                    .client
                    .prepare_parameter_input_from_context_v2(
                        self.round.clone(),
                        context.path.clone(),
                        context.digest.parse()?,
                        self.facts.search.path.clone(),
                        self.facts.search.digest.parse()?,
                    )
                    .await?;
                ensure!(
                    baseline.baseline.context_source
                        == context
                            .path
                            .to_str()
                            .context("original context path encoding")?
                        && baseline.baseline.context_digest == context.digest
                        && baseline.baseline.material_source
                            == self
                                .facts
                                .indexed
                                .material_source
                                .path
                                .to_str()
                                .context("original material path encoding")?
                        && baseline.baseline.material_digest
                            == self.facts.indexed.material_source.digest,
                    "unique final context differs from original prepared Sources"
                );
                (
                    generation,
                    input,
                    admission,
                    baseline.proposal_registry_predecessor.parse::<Digest32>()?,
                )
            }
        };
        current::validate_runtime_generation(self.before, generation)?;
        ensure!(
            input.baseline_id == self.facts.baseline_id
                && input.baseline_generation == self.facts.indexed.material.runtime.generation
                && input.objective_digest == self.facts.indexed.material.scope.objective_digest,
            "actual complete prepared numerical baseline changed"
        );
        let phase = match self.phase {
            parameter_roles::AdmissionPhase::BeforeRegistration => "pre-registration",
            parameter_roles::AdmissionPhase::AfterRegistration => "registered",
        };
        let profile = original_facts::publish(
            &self.facts.public,
            &format!("{phase}-profile.bin"),
            &encode_untrusted_parameter_generator_profile_v3(&input.generator_profile)
                .map_err(|error| anyhow::anyhow!("{error}"))?,
            1024 * 1024,
        )?;
        let admitted = original_facts::publish(
            &self.facts.public,
            &format!("{phase}-admission.bin"),
            &encode_untrusted_plasticity_admission_v1(&admission)
                .map_err(|error| anyhow::anyhow!("{error}"))?,
            1024 * 1024,
        )?;
        let sources = [&profile, &self.facts.indexed.material_source, &admitted].map(|source| {
            ParameterRoleSourceV3 {
                path: source.path.clone(),
                digest: source.digest.clone(),
            }
        });
        let Some([generator_attestation, admission_attestation]) =
            parameter_roles::OriginalParameterRolePreparation {
                round: self.round,
                canonical: self.canonical,
                baseline: &self.facts.indexed.material,
                input: &input,
                admission: &admission,
                sources,
                current: crate::RootParameterObserverCurrentV1 {
                    facts: self.current,
                    source: ParameterRoleSourceV3 {
                        path: self.registration.path.clone(),
                        digest: self.registration.digest.clone(),
                    },
                    subject: self.subject,
                },
                trust: &self.blueprint.learning_trust,
                routes: [&self.blueprint.generator, &self.blueprint.observer],
                public_directory: &self.facts.public,
                effects_directory: &self.facts.effects,
                phase: self.phase,
            }
            .execute()?
        else {
            return Ok(None);
        };
        let proposal_id = StableId::new(format!(
            "cpu.parameter.round.{}",
            self.round.identity_digest()
        ))?;
        self.current
            .revalidate_current(now_ms()?)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        self.facts
            .indexed
            .revalidate()
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        Ok(Some((
            ParameterPlasticityProductRequestV1 {
                proposal_id,
                generator_profile: input.generator_profile,
                generated: input.generated,
                generator_attestation,
                admission,
                admission_attestation,
                no_change_attestation: None,
                evaluations: Vec::new(),
                expected_registry_predecessor: predecessor,
            },
            context,
        )))
    }
}
