//! Concrete transport for the original evaluator's one signing operation.
//! The independent actor receives only the exact original request data. The
//! original Product runner authenticates its response before completing its
//! already durable execution claim; this adapter never signs an execution.

use std::sync::Arc;

use codex_hepta_intelligence_eval::{
    ProductEvaluationExecutionAttestationRequestV1, ProductEvaluationExecutionAttestorV1,
    ProductEvaluationExecutionKeyV1, ProductProviderErrorV1, SignedEvaluationEvidenceV1,
};
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};

use crate::{AgentdError, CellEvaluationPlanV1, CellQ24PreparedLearningV1};
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;

use super::exchange::{OriginalActorExchange, OriginalActorExchangeData, OriginalActorWait};
use super::files::OriginalDeploymentFiles;
use super::learning_data::SignedEvidenceData;
use super::{deployment_error, deployment_refused};

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalExecutionSigningData<'a> {
    schema_version: u32,
    purpose: &'static str,
    phase: &'a str,
    learning_operation: &'a str,
    plan_id: &'a str,
    execution_binding: [u8; 32],
    execution_digest: [u8; 32],
    payload: &'a [u8],
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalExecutionResponseData {
    schema_version: u32,
    request_digest: [u8; 32],
    execution_digest: [u8; 32],
    signed: SignedEvidenceData,
}

pub(super) struct OriginalExecutionAttestor<'a> {
    context: Arc<OriginalSameActorRootContext>,
    prepared: &'a CellQ24PreparedLearningV1,
    expected: ProductEvaluationExecutionKeyV1,
    exchange: Option<OriginalActorExchange>,
    files: &'a mut OriginalDeploymentFiles,
    wait: &'a mut OriginalActorWait,
    failure: Option<AgentdError>,
}

impl<'a> OriginalExecutionAttestor<'a> {
    pub(super) fn new(
        context: Arc<OriginalSameActorRootContext>,
        prepared: &'a CellQ24PreparedLearningV1,
        expected: ProductEvaluationExecutionKeyV1,
        exchange: OriginalActorExchangeData,
        files: &'a mut OriginalDeploymentFiles,
        wait: &'a mut OriginalActorWait,
    ) -> Result<Self, AgentdError> {
        OriginalSameActorRootContext::require_current(&context)?;
        prepared.revalidate_source().map_err(deployment_error)?;
        Ok(Self {
            context, prepared, expected,
            exchange: Some(OriginalActorExchange::new(exchange)?),
            files, wait, failure: None,
        })
    }

    pub(super) fn take_original_failure(&mut self) -> Option<AgentdError> {
        self.failure.take()
    }

    fn exchange_original_request(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, AgentdError> {
        self.wait.require_original_live()?;
        if request.key() != &self.expected {
            return Err(deployment_refused("actual evaluator request differs from its original key"));
        }
        let exchange = self.exchange.take()
            .ok_or_else(|| deployment_refused("original evaluator operation already consumed"))?;
        let raw = OriginalExecutionSigningData {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.execution-signing.v1",
            phase: &self.context.descriptor().phase,
            learning_operation: self.prepared.initial().request.operation_id.as_str(),
            plan_id: request.key().plan_id.as_str(),
            execution_binding: request.key().binding_digest.into_array(),
            execution_digest: request.execution().execution_digest.into_array(),
            payload: request.signing_payload(),
        };
        let (digest, response) = exchange.exchange_original(&raw, self.files, self.wait)?;
        let signed: OriginalExecutionResponseData = response.parse_original()?;
        if signed.schema_version != 1
            || signed.request_digest != digest.into_array()
            || signed.execution_digest != raw.execution_digest
        {
            return Err(deployment_refused("original evaluator response binding differs"));
        }
        let evidence = signed.signed.original()?;
        response.require_original_pin()?;
        self.wait.require_original_live()?;
        // Signature, role, full principal and objective authentication remains
        // in Product::authenticate immediately after this exact trait return.
        Ok(evidence)
    }
}

impl ProductEvaluationExecutionAttestorV1 for OriginalExecutionAttestor<'_> {
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1> {
        match self.exchange_original_request(request) {
            Ok(signed) => Ok(signed),
            Err(error) => {
                self.failure = Some(error);
                // Actual execution was already claimed and performed. A
                // missing/failed external reply is never "not executed".
                Err(ProductProviderErrorV1::Indeterminate)
            }
        }
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalQualificationSigningData<'a> {
    schema_version: u32,
    purpose: &'static str,
    phase: &'a str,
    learning_operation: &'a str,
    execution_digest: [u8; 32],
    frozen_plan_digest: [u8; 32],
    generator_payload: &'a [u8],
    evaluator_payload: &'a [u8],
    actual_cell_record: serde_json::Value,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalQualificationResponseData {
    schema_version: u32,
    request_digest: [u8; 32],
    execution_digest: [u8; 32],
    generator_plan: SignedEvidenceData,
    evaluator_bundle: SignedEvidenceData,
}

/// Called only after actual Cell evaluation returns a sealed receipt and the
/// SAME runner builds its qualification bundle and canonical signing payload.
pub(super) struct OriginalQualificationSigningRequest<'a> {
    pub context: &'a OriginalSameActorRootContext,
    pub prepared: &'a CellQ24PreparedLearningV1,
    pub plan: &'a CellEvaluationPlanV1,
    pub execution_digest: Digest32,
    pub evaluator_payload: &'a [u8],
}

pub(super) fn request_original_qualification(
    original: OriginalQualificationSigningRequest<'_>,
    exchange: OriginalActorExchangeData,
    files: &mut OriginalDeploymentFiles,
    wait: &mut OriginalActorWait,
) -> Result<SignedEvaluationEvidenceV1, AgentdError> {
    wait.require_original_live()?;
    let generator = original.plan.product_plan().frozen_plan.plan_digest;
    let request = OriginalQualificationSigningData {
        schema_version: 1,
        purpose: "hepta.same-actor-q24-deployment.qualification-signing.v1",
        phase: &original.context.descriptor().phase,
        learning_operation: original.prepared.initial().request.operation_id.as_str(),
        execution_digest: original.execution_digest.into_array(),
        frozen_plan_digest: generator.into_array(),
        generator_payload: generator.as_array(),
        evaluator_payload: original.evaluator_payload,
        actual_cell_record: serde_json::to_value(original.plan.record()).map_err(deployment_error)?,
    };
    let (digest, response) = OriginalActorExchange::new(exchange)?
        .exchange_original(&request, files, wait)?;
    let signed: OriginalQualificationResponseData = response.parse_original()?;
    if signed.schema_version != 1 || signed.request_digest != digest.into_array()
        || signed.execution_digest != request.execution_digest
    {
        return Err(deployment_refused("actual qualification response binding differs"));
    }
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: signed.generator_plan.original()?,
        evaluator_bundle: signed.evaluator_bundle.original()?,
    };
    response.require_original_pin()?;
    wait.require_original_live()?;
    Ok(evidence)
}
