//! Prepare actual per-round inputs on the admitted Root route. Original
//! G/O/E/E1/publisher/S3 owners retain every effect, key and consumed slot.
use super::*;
use crate::OriginalParameterEvaluationPreparationResultV1;
use crate::initial_cpu_anchor::*;
use crate::local_cpu_parameter_compiler::FinalRoundParameterAdmissionV3;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;

pub(super) struct Preparation<'a> {
    pub service: &'a RootFrozenGeneratorServiceV1,
    pub blueprint_source: &'a InstalledCpuSourceV1,
    pub client: &'a AgentdClient,
    pub before: &'a codex_hepta_supervisor::SupervisordAgentStatus,
    pub scope: &'a AgentScope,
    pub round: &'a AgentdSelfIterationRoundV1,
    pub canonical: &'a codex_hepta_agentd::CanonicalIterationEnvelopeV1,
}
impl Preparation<'_> {
    pub(super) async fn prepare(self) -> Result<Option<RoundPreparationResultV1>> {
        let (blueprint, blueprint_bytes) = blueprint::Blueprint::read(self.blueprint_source)?;
        ensure!(
            blueprint.worker_program.digest == self.scope.worker_executable_digest,
            "whole enrolled original worker executable changed"
        );
        let subject = StableId::new(self.scope.agent_id.as_str())?;
        let Some(facts) = original_facts::collect(
            &blueprint,
            self.client,
            self.before,
            &self.scope.agent_id,
            self.service.layout.agent(&self.scope.agent_id).home_root(),
            self.round,
            &self.service.configuration.execution_directory,
        )
        .await?
        else {
            return Ok(Some(pending()));
        };
        let Some((request, _)) = admission_projection::Preparation {
            blueprint: &blueprint,
            facts: &facts,
            client: self.client,
            before: self.before,
            subject: &subject,
            round: self.round,
            canonical: self.canonical,
            current: &facts.current,
            registration: &facts.registration,
            snapshot: &facts.snapshot,
            snapshot_receipt: facts.snapshot_receipt,
            phase: parameter_roles::AdmissionPhase::BeforeRegistration,
        }
        .prepare()
        .await?
        else {
            return Ok(Some(pending()));
        };
        let execution = self
            .canonical
            .execution_envelope(u16::try_from(self.round.candidate_admissions())?)
            .map_err(anyhow::Error::msg)?;
        let mut material_blueprint = blueprint.material()?;
        // Body generation is an original factual input, not a policy/lifetime
        // change. All enrolled features, objective and sparse surfaces remain.
        material_blueprint.canary_tick.body_generation =
            Some(facts.indexed.material.runtime.generation.get());
        let materials = crate::derive_cpu_neuron_round_materials_v3(
            self.round,
            self.canonical,
            &execution,
            &facts.indexed.material,
            &request,
            &material_blueprint,
        )?;
        let trust_bytes = configuration::source(&blueprint.learning_trust, 64 * 1024)?;
        let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
        let (root, distribution) = wire.native().map_err(|error| anyhow::anyhow!("{error}"))?;
        let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
        let reviewer_bytes = configuration::source(&blueprint.reviewer_principal, 8192)?;
        let reviewer: PrincipalWire = serde_json::from_slice(&reviewer_bytes)?;
        let reviewer = reviewer
            .principal()
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        reviewer.validate(now_ms()?)?;
        let prepared = crate::prepare_original_parameter_evaluation_publications_v1(
            materials,
            &blueprint.raw_evaluation_template,
            &subject,
            &trust,
            &reviewer,
            |publication, material, original_configuration| {
                publication_configuration::project(
                    &facts.registration,
                    publication,
                    material,
                    original_configuration,
                    &subject,
                    &facts.public,
                )
            },
        )?;
        let complete = match prepared {
            OriginalParameterEvaluationPreparationResultV1::Pending => return Ok(Some(pending())),
            OriginalParameterEvaluationPreparationResultV1::Terminal { source } => {
                ensure!(
                    configuration::source(self.blueprint_source, 262_144)? == blueprint_bytes,
                    "whole original blueprint changed before terminal return"
                );
                return Ok(Some(RoundPreparationResultV1::Terminal {
                    source: RoundPreparationSourceV1 {
                        path: source.path,
                        digest: source.digest,
                    },
                }));
            }
            OriginalParameterEvaluationPreparationResultV1::Completed(complete) => complete,
        };
        ensure!(
            complete.candidates.len() == complete.candidate_publication_configurations.len()
                && complete.candidates.len() == complete.rollbacks.len(),
            "complete original publication and exact rollback frontier differs"
        );
        // H' is independent of the rollback material. Refresh the original
        // installed training baseline against the latest real full ACK.
        let (registration, current) = original_facts::current_registration(
            &facts.registration,
            &facts.indexed.material,
            &subject,
            &facts.public,
        )?;
        let (snapshot_path, receipt) = current
            .protected_current_registry_source(now_ms()?)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        let snapshot_bytes = read_root_review_input(&snapshot_path, 64 * 1024 * 1024)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        ensure!(
            Digest32::of_bytes(&snapshot_bytes) == receipt.file_digest
                && snapshot_bytes.len() == receipt.encoded_bytes,
            "whole latest original snapshot Source changed"
        );
        let snapshot = original_facts::publish(
            &facts.public,
            &format!("registry-{}.bin", receipt.file_digest),
            &snapshot_bytes,
            64 * 1024 * 1024,
        )?;
        let Some((actual, context)) = admission_projection::Preparation {
            blueprint: &blueprint,
            facts: &facts,
            client: self.client,
            before: self.before,
            subject: &subject,
            round: self.round,
            canonical: self.canonical,
            current: &current,
            registration: &registration,
            snapshot: &snapshot,
            snapshot_receipt: receipt,
            phase: parameter_roles::AdmissionPhase::AfterRegistration,
        }
        .prepare()
        .await?
        else {
            return Ok(Some(pending()));
        };
        let original = complete.materials.request();
        ensure!(
            actual.proposal_id == original.proposal_id
                && actual.generator_profile == original.generator_profile
                && actual.generated == original.generated
                && actual.evaluations.is_empty()
                && actual.no_change_attestation == original.no_change_attestation,
            "whole final factual G/O search changed"
        );
        // Preserve the complete opaque-owner-verified original E request.
        // Replace only the freshly authenticated original G/O frontiers.
        let mut final_request = original.clone();
        final_request.generator_attestation = actual.generator_attestation;
        final_request.admission = actual.admission;
        final_request.admission_attestation = actual.admission_attestation;
        final_request.expected_registry_predecessor = actual.expected_registry_predecessor;
        let mut candidates = Vec::new();
        for publication in &complete.candidates {
            let evaluation = history(&publication.evaluation_sources)?;
            candidates.push(evaluation);
        }
        let rollback_evaluations = complete
            .rollbacks
            .iter()
            .map(|entry| history(&entry.publication.evaluation_sources))
            .collect::<Result<Vec<_>>>()?;
        let materials = complete.materials.install_registered_material_pairs_v2(
            &candidates,
            &rollback_evaluations,
            FinalRoundParameterAdmissionV3 {
                request: final_request,
                verifier: trust.verifier(),
                current: &current,
                proposal_registry_predecessor: actual.expected_registry_predecessor,
                now: now_ms()?,
            },
        )?;
        let mut selected = Vec::new();
        let mut registrations = Vec::new();
        for (publication, source) in complete
            .candidates
            .iter()
            .zip(&complete.candidate_publication_configurations)
        {
            let material = materials
                .candidates()
                .iter()
                .find(|candidate| candidate.candidate_id.as_str() == publication.candidate_id)
                .context("whole candidate material absent")?;
            let registration = publication_configuration::project(
                &facts.registration,
                publication,
                &material.generation,
                source,
                &subject,
                &facts.public,
            )?;
            let Some(selection) = selection_projection::Preparation {
                blueprint: &blueprint,
                publication,
                material: &material.generation,
                registration: &registration,
                predecessor: None,
                public: &facts.public,
                effects: &facts.effects,
                round: self.round,
            }
            .select()?
            else {
                return Ok(Some(pending()));
            };
            registrations.push(registration);
            selected.push(selection);
        }
        let mut rollbacks = Vec::new();
        for entry in &complete.rollbacks {
            ensure!(
                entry.publication.candidate_id == entry.candidate_id.as_str(),
                "original rollback publication changed its candidate"
            );
            let predecessor_index = complete
                .candidates
                .iter()
                .position(|publication| publication.candidate_id == entry.candidate_id.as_str())
                .context("original rollback candidate absent")?;
            let predecessor_publication = &complete.candidates[predecessor_index];
            let head = &predecessor_publication.publications[3];
            let predecessor = ParameterPreRegisteredPredecessorV1 {
                evaluation: predecessor_publication.evaluation_sources.clone(),
                registration: CpuProtectedSourceV1 {
                    path: registrations[predecessor_index].path.clone(),
                    digest: registrations[predecessor_index].digest.clone(),
                },
                head_manifest: ParameterRoleSourceV3 {
                    path: head.manifest.path.clone(),
                    digest: head.manifest.digest.clone(),
                },
                head_admission_digest: head.admission_digest.clone(),
                head_artifact_id: head.artifact_id.clone(),
            };
            let material = materials.rollback_for_candidate(&entry.candidate_id)?;
            let rollback_registration = publication_configuration::project(
                &facts.registration,
                &entry.publication,
                material,
                &entry.publication_configuration,
                &subject,
                &facts.public,
            )?;
            let Some(rollback) = selection_projection::Preparation {
                blueprint: &blueprint,
                publication: &entry.publication,
                material,
                registration: &rollback_registration,
                predecessor: Some(predecessor),
                public: &facts.public,
                effects: &facts.effects,
                round: self.round,
            }
            .select()?
            else {
                return Ok(Some(pending()));
            };
            rollbacks.push(rollback);
        }
        trust.revalidate_at(now_ms()?)?;
        current
            .revalidate_current(now_ms()?)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        facts
            .indexed
            .revalidate()
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        ensure!(
            configuration::source(self.blueprint_source, 262_144)? == blueprint_bytes
                && configuration::source(&blueprint.learning_trust, 64 * 1024)? == trust_bytes
                && configuration::source(&blueprint.reviewer_principal, 8192)? == reviewer_bytes,
            "whole original enrolled inputs changed before bundle publication"
        );
        bundle_publication::publish(
            &self.service.configuration.execution_directory,
            &blueprint,
            &materials,
            &context,
            selected,
            rollbacks,
        )?;
        Ok(None)
    }
}
fn pending() -> RoundPreparationResultV1 {
    RoundPreparationResultV1::Refused {
        error: FrozenGeneratorErrorCodeV1::Pending,
    }
}
fn history(
    source: &ParameterPreRegistrationEvaluationSourcesV1,
) -> Result<VerifiedParameterPreRegistrationEvaluationV1> {
    inspect_parameter_pre_registration_history_v1(
        &source.configuration.path,
        source.configuration.digest.parse()?,
        &source.report.path,
        source.report.digest.parse()?,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))
}
