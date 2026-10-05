//! Installed E/S/O ports reuse the original authenticated Root route. The
//! Agent holds public pins only; each physical role remains an independent
//! fixed-purpose process with its original signer and evidence owner.
use super::*;
use crate::CpuNeuronParameterRootMaterialsV2;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agentd::AgentdSelfIterationCanaryVerdictV1;
use codex_hepta_agentd::AgentdSelfIterationIndependentOwnersV1;
use codex_hepta_agentd::AgentdSelfIterationRecordV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::AgentdSignedEvaluationV1;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use serde::Deserialize;
use serde::Serialize;
use std::sync::Arc;

#[path = "installed_self_iteration_owners_configuration.rs"]
mod configuration;
use configuration::CandidateBinding;
use configuration::Configuration;
pub use configuration::InstalledSelfIterationIndependentOwnersConfigV1;
use configuration::now;
use configuration::read_source;
pub use configuration::self_iteration_independent_owner_materials_digest_v1;

pub struct InstalledSelfIterationIndependentOwnersV1 {
    configuration: Configuration,
    source: InstalledCpuSourceV1,
    source_bytes: Vec<u8>,
    round: AgentdSelfIterationRoundV1,
    trust: Arc<ActivatedLearningTrustV1>,
    trust_bytes: Vec<u8>,
    candidates: Vec<CandidateBinding>,
    consumer: Option<Vec<u8>>,
}
impl InstalledSelfIterationIndependentOwnersV1 {
    pub fn from_protected_source(
        source: &InstalledCpuSourceV1,
        original_round: AgentdSelfIterationRoundV1,
        materials: &CpuNeuronParameterRootMaterialsV2,
    ) -> Result<Self, AgentdError> {
        materials.revalidate_sources()?;
        let source_bytes = read_source(source, 64 * 1024)?;
        let configuration: Configuration = serde_json::from_slice(&source_bytes)?;
        let current = now()?;
        configuration.validate(&original_round, materials, current)?;
        let trust_bytes = read_source(&configuration.learning_trust, 64 * 1024)?;
        let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
        let (root, distribution) = wire.native().map_err(protocol)?;
        let trust = Arc::new(
            activate_learning_trust(&root, distribution, None, current).map_err(protocol)?,
        );
        configuration.validate_roster(&trust, current)?;
        Route::read(
            &configuration.route.path,
            configuration.route.digest.parse().map_err(protocol)?,
        )
        .map_err(protocol)?;
        let candidates = materials.with_plan(configuration::candidate_bindings)?;
        Ok(Self {
            configuration,
            source: source.clone(),
            source_bytes,
            round: original_round,
            trust,
            trust_bytes,
            candidates,
            consumer: None,
        })
    }
    fn revalidate(&self) -> Result<u64, AgentdError> {
        if read_source(&self.source, 64 * 1024)? != self.source_bytes
            || read_source(&self.configuration.learning_trust, 64 * 1024)? != self.trust_bytes
        {
            return Err(protocol("installed independent owner Source changed"));
        }
        let current = now()?;
        if current >= self.round.deadline_ms() {
            return Err(protocol("original independent owner round expired"));
        }
        self.trust.revalidate_at(current).map_err(protocol)?;
        self.configuration.validate_roster(&self.trust, current)?;
        Ok(current)
    }
    fn validate_consumer(
        &self,
        bytes: &[u8],
        record: &AgentdSelfIterationRecordV1,
    ) -> Result<(), AgentdError> {
        let current = self.revalidate()?;
        let frozen = inspect_signed_self_iteration_frozen_consumer_v1(bytes, &self.trust, current)
            .map_err(protocol)?;
        let round = AgentdSelfIterationRoundV1::decode(
            frozen
                .generator_round_bytes()
                .ok_or_else(|| protocol("full original round missing"))?,
        )?;
        let expected = self
            .candidates
            .iter()
            .find(|c| c.id == record.candidate_id)
            .ok_or_else(|| protocol("candidate absent from original full materials"))?;
        if round != self.round
            || frozen.generator().principal().principal_id.as_str() != self.configuration.generator
            || frozen.canonical_envelope_digest() != Some(self.round.canonical_policy_digest())
            || frozen.frozen_digest() != record.frozen_digest
            || frozen.candidate_id().as_str() != record.candidate_id
            || frozen.base_generation() != expected.base_generation
            || frozen.successor_configuration() != expected.successor_configuration
            || frozen.successor_body() != expected.successor_body
            || frozen.rollback_configuration() != expected.rollback_configuration
            || frozen.rollback_body() != expected.rollback_body
            || record.base_generation != frozen.base_generation()
            || record.objective_digest != frozen.objective_digest()
            || record.successor_generation
                != frozen
                    .base_generation()
                    .checked_add(1)
                    .ok_or_else(|| protocol("candidate generation overflow"))?
            || record.rollback_generation
                != frozen
                    .base_generation()
                    .checked_add(2)
                    .ok_or_else(|| protocol("rollback generation overflow"))?
            || record.successor_configuration != frozen.successor_configuration()
            || record.successor_body != frozen.successor_body()
            || record.rollback_configuration != frozen.rollback_configuration()
            || record.rollback_body != frozen.rollback_body()
        {
            return Err(protocol(
                "installed owner whole original frozen/material binding",
            ));
        }
        Ok(())
    }
    fn request(
        &self,
        purpose: SelfIterationOwnerPurposeV1,
        record: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> Result<SelfIterationOwnerRequestV1, AgentdError> {
        let role = match purpose {
            SelfIterationOwnerPurposeV1::Evaluate => SelfIterationModelRoleV1::Evaluator,
            SelfIterationOwnerPurposeV1::Select => SelfIterationModelRoleV1::Selector,
            SelfIterationOwnerPurposeV1::Observe => SelfIterationModelRoleV1::Observer,
        };
        if assessment.role != role
            || assessment.request_id
                != self
                    .round
                    .model_request_id(role, Some(record.frozen_digest))?
            || assessment.envelope_digest != self.round.execution_envelope_digest()
            || assessment.candidate_digest != Some(record.frozen_digest)
            || assessment.model_output.is_empty()
            || assessment.model_output.len() > 64 * 1024
            || assessment.native_run_digest.is_zero()
            || assessment.authority.grants_any()
        {
            return Err(protocol(
                "installed owner requires exact actual original model stage",
            ));
        }
        let consumer = self
            .consumer
            .as_ref()
            .ok_or_else(|| protocol("original signed frozen consumer unavailable"))?;
        self.validate_consumer(consumer, record)?;
        SelfIterationOwnerRequestV1::from_original_bytes(
            purpose,
            consumer,
            &serde_json::to_vec(record)?,
            SelfIterationOwnerModelFactsV1 {
                request_id: assessment.request_id.to_string(),
                envelope_digest: assessment.envelope_digest.to_string(),
                candidate_digest: record.frozen_digest.to_string(),
                output_digest: Digest32::of_bytes(assessment.model_output.as_bytes()).to_string(),
                native_run_digest: assessment.native_run_digest.to_string(),
            },
        )
        .map_err(protocol)
    }
    async fn exchange(
        &self,
        request: &SelfIterationOwnerRequestV1,
        frozen: Digest32,
    ) -> Result<Vec<u8>, AgentdError> {
        self.revalidate()?;
        let route = Route::read(
            &self.configuration.route.path,
            self.configuration.route.digest.parse().map_err(protocol)?,
        )
        .map_err(protocol)?;
        let bytes = encode_self_iteration_owner_request_v1(request).map_err(protocol)?;
        let exchange = async {
            validate_issuer_socket(&route.socket, 0).map_err(protocol)?;
            let mut stream = UnixStream::connect(&route.socket).await?;
            let response = exchange_connected_bytes(
                &mut stream,
                &route,
                &bytes,
                request.purpose.maximum_response_bytes(),
            )
            .await?;
            Route::read(
                &self.configuration.route.path,
                self.configuration.route.digest.parse().map_err(protocol)?,
            )
            .map_err(protocol)?;
            self.revalidate()?;
            match decode_self_iteration_owner_response_v1(request.purpose, &response)
                .map_err(protocol)?
            {
                SelfIterationOwnerResponseV1::Granted(value)
                    if value.frozen_digest == frozen.to_string() =>
                {
                    value.publication().map_err(protocol)
                }
                SelfIterationOwnerResponseV1::Granted(_) => Err(protocol(
                    "independent owner response changed frozen candidate",
                )),
                SelfIterationOwnerResponseV1::Refused(value) => Err(protocol(format!(
                    "independent owner outcome unavailable: {:?}",
                    value.error
                ))),
            }
        };
        tokio::time::timeout(
            Duration::from_millis(route.maximum_request_duration_ms),
            exchange,
        )
        .await
        .map_err(|_| protocol("independent owner exchange outcome unknown"))?
    }
}
impl AgentdSelfIterationIndependentOwnersV1 for InstalledSelfIterationIndependentOwnersV1 {
    async fn evaluate(
        &mut self,
        candidate: &AgentdSelfIterationCandidateV1,
        frozen: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSignedEvaluationV1, AgentdError> {
        if candidate.round.as_ref() != Some(&self.round) {
            return Err(protocol("candidate belongs to another original round"));
        }
        let payload = self_iteration_frozen_candidate_payload_v1(candidate)?;
        let consumer =
            encode_self_iteration_frozen_consumer_v1(&payload, &candidate.generator_attestation)
                .map_err(protocol)?;
        self.validate_consumer(&consumer, frozen)?;
        if self
            .consumer
            .as_ref()
            .is_some_and(|original| original != &consumer)
        {
            return Err(protocol("retained independent owner consumer changed"));
        }
        self.consumer = Some(consumer);
        let request = self.request(SelfIterationOwnerPurposeV1::Evaluate, frozen, assessment)?;
        let bytes = self.exchange(&request, frozen.frozen_digest).await?;
        let signed = AgentdSignedEvaluationV1::from_self_iteration_transport(
            &bytes,
            frozen.frozen_digest,
            &self.trust,
            self.revalidate()?,
        )?;
        if signed.use_attestation.principal_id.as_str() != self.configuration.evaluator {
            return Err(protocol(
                "installed independent Evaluator principal changed",
            ));
        }
        Ok(signed)
    }
    async fn select(
        &mut self,
        record: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> Result<SignedLearningEvidenceV1, AgentdError> {
        let request = self.request(SelfIterationOwnerPurposeV1::Select, record, assessment)?;
        let bytes = self.exchange(&request, record.frozen_digest).await?;
        let value: Selection = serde_json::from_slice(&bytes)?;
        if value.schema != "hepta.cpu-neuron.self-iteration-stage-selection.v1"
            || value.selector_uid != self.configuration.selector_uid
            || value.frozen_digest != record.frozen_digest.to_string()
            || value.evaluation_digest
                != record
                    .evaluation_digest
                    .ok_or_else(|| protocol("actual evaluation missing"))?
                    .to_string()
            || value
                .configuration_digest
                .parse::<Digest32>()
                .map_err(protocol)?
                .is_zero()
            || value.artifact_publication
            || value.production_activation
        {
            return Err(protocol("whole original stage selection changed"));
        }
        let evidence = value.selector_evidence.native().map_err(protocol)?;
        self.verify(
            LearningEvidenceRoleV1::Selector,
            &evidence,
            &codex_hepta_agentd::self_iteration_stage_payload_v1(
                record.frozen_digest,
                record
                    .evaluation_digest
                    .ok_or_else(|| protocol("evaluation missing"))?,
            ),
            &self.configuration.selector,
        )?;
        Ok(evidence)
    }
    async fn observe(
        &mut self,
        record: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> Result<(AgentdSelfIterationCanaryVerdictV1, SignedLearningEvidenceV1), AgentdError> {
        let request = self.request(SelfIterationOwnerPurposeV1::Observe, record, assessment)?;
        let bytes = self.exchange(&request, record.frozen_digest).await?;
        let value: Observation = serde_json::from_slice(&bytes)?;
        let verdict = match value.verdict.as_str() {
            "accept" => AgentdSelfIterationCanaryVerdictV1::Accept,
            "rollback" => AgentdSelfIterationCanaryVerdictV1::RollBack,
            _ => return Err(protocol("original canary verdict")),
        };
        if value.schema != "hepta.cpu-neuron.self-iteration-canary-observation.v1"
            || value.frozen_digest != record.frozen_digest.to_string()
            || value
                .configuration_digest
                .parse::<Digest32>()
                .map_err(protocol)?
                .is_zero()
            || value
                .canary_receipt_digest
                .parse::<Digest32>()
                .map_err(protocol)?
                .is_zero()
            || value.canary_operation_digest
                != record.canary_operation_digest.map(|d| d.to_string())
            || value.canary_checkpoint_digest
                != record.canary_checkpoint_digest.map(|d| d.to_string())
            || Some(value.physical_observation) != record.canary_observation
            || value.production_activation
        {
            return Err(protocol("whole original physical canary result changed"));
        }
        let evidence = value.observer_evidence.native().map_err(protocol)?;
        self.verify(
            LearningEvidenceRoleV1::Observer,
            &evidence,
            &codex_hepta_agentd::self_iteration_canary_payload_v1(record, verdict)?,
            &self.configuration.observer,
        )?;
        Ok((verdict, evidence))
    }
}
impl InstalledSelfIterationIndependentOwnersV1 {
    fn verify(
        &self,
        role: LearningEvidenceRoleV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        principal: &str,
    ) -> Result<(), AgentdError> {
        let verified = self
            .trust
            .verifier()
            .verify(role, evidence, payload, self.revalidate()?)
            .map_err(protocol)?;
        if verified.principal().principal_id.as_str() != principal {
            return Err(protocol("installed original independent principal changed"));
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    schema: String,
    configuration_digest: String,
    frozen_digest: String,
    evaluation_digest: String,
    selector_uid: u32,
    selector_evidence: ReviewEvidenceWireV1,
    artifact_publication: bool,
    production_activation: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Observation {
    schema: String,
    configuration_digest: String,
    frozen_digest: String,
    canary_receipt_digest: String,
    canary_operation_digest: Option<String>,
    canary_checkpoint_digest: Option<String>,
    physical_observation: codex_hepta_agentd::AgentdSelfIterationCanaryObservationV1,
    verdict: String,
    observer_evidence: ReviewEvidenceWireV1,
    production_activation: bool,
}
