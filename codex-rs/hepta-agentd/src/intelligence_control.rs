//! Product host handoff for the intelligence.control V3 facade.
//!
//! This caller consumes a fully validated IntelligenceHostEnvelopeV1, admits
//! the immutable run snapshot into Agentd and attaches the compiled context. It
//! deliberately stops at ContextAttached: Codex dispatch remains owned by the
//! existing Agentd/App Server path and requires the normal runtime transition.

use std::error::Error;
use std::fmt;

use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::CompositionDispositionV3;
use codex_hepta_intelligence::CompositionErrorV3;
use codex_hepta_intelligence::CompositionPipelineReceiptV3;
use codex_hepta_intelligence::CompositionPortsV3;
use codex_hepta_intelligence::CompositionRunRequestV3;
use codex_hepta_intelligence::prepare_intelligence_run_v3;
use codex_hepta_types::Digest32;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::ContextAttachment;
use crate::RunReceipt;
use crate::RunSnapshot;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceAdmissionReceiptV1 {
    pub run: RunReceipt,
    pub envelope_digest: Digest32,
    pub composition_trace_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceCompositionAdmissionReceiptV1 {
    pub composition: CompositionPipelineReceiptV3,
    pub admission: Option<IntelligenceAdmissionReceiptV1>,
}

#[derive(Debug)]
pub enum IntelligenceControlCallerErrorV1 {
    Composition(CompositionErrorV3),
    NotPrepared,
    DeadlineOverflow,
    Runtime(AgentRunError),
}

impl fmt::Display for IntelligenceControlCallerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for IntelligenceControlCallerErrorV1 {}

/// Invoke intelligence.control V3 and, only when it prepares a host envelope,
/// admit that envelope into the existing Agentd run coordinator.
///
/// Abstain, slow-path, cancellation, deadline and typed failure dispositions are
/// returned as composition receipts with no Agentd run admission.
pub fn compose_and_admit_intelligence_run_v1<P, C>(
    coordinator: &mut AgentRunCoordinator,
    now_unix_ms: u64,
    request: CompositionRunRequestV3,
    ports: &mut P,
    control: &C,
) -> Result<IntelligenceCompositionAdmissionReceiptV1, IntelligenceControlCallerErrorV1>
where
    P: CompositionPortsV3,
    C: CompositionControlV3,
{
    let composition = prepare_intelligence_run_v3(request, ports, control)
        .map_err(IntelligenceControlCallerErrorV1::Composition)?;
    let admission = if composition.disposition == CompositionDispositionV3::HostEnvelopePrepared {
        Some(admit_intelligence_run_v1(
            coordinator,
            now_unix_ms,
            &composition,
        )?)
    } else {
        None
    };
    Ok(IntelligenceCompositionAdmissionReceiptV1 {
        composition,
        admission,
    })
}

/// Admit a V3 intelligence run into the real Agentd run coordinator.
///
/// Successful return proves only product-host admission plus context attachment.
/// It does not call mark_dispatched, invoke Codex, execute a tool/effect, append
/// an Outcome/Credit, or grant any authority.
pub fn admit_intelligence_run_v1(
    coordinator: &mut AgentRunCoordinator,
    now_unix_ms: u64,
    composition: &CompositionPipelineReceiptV3,
) -> Result<IntelligenceAdmissionReceiptV1, IntelligenceControlCallerErrorV1> {
    composition
        .validate()
        .map_err(IntelligenceControlCallerErrorV1::Composition)?;
    if composition.disposition != CompositionDispositionV3::HostEnvelopePrepared {
        return Err(IntelligenceControlCallerErrorV1::NotPrepared);
    }
    let envelope = composition
        .envelope
        .as_ref()
        .ok_or(IntelligenceControlCallerErrorV1::NotPrepared)?;
    envelope
        .validate()
        .map_err(IntelligenceControlCallerErrorV1::Composition)?;

    let deadline_unix_ms = envelope
        .deadline_unix_micros
        .checked_add(999)
        .ok_or(IntelligenceControlCallerErrorV1::DeadlineOverflow)?
        / 1_000;

    let started = coordinator
        .start_run(
            now_unix_ms,
            RunSnapshot {
                run_id: envelope.run_id.to_string(),
                request_digest: envelope.request_digest.to_string(),
                objective_digest: envelope.objective_digest.to_string(),
                body_digest: envelope.body_digest.to_string(),
                artifact_set_digest: envelope.artifact_set_digest.to_string(),
                authority_epoch: envelope.authority_epoch,
                deadline_ms: deadline_unix_ms,
            },
        )
        .map_err(IntelligenceControlCallerErrorV1::Runtime)?;

    let run = coordinator
        .attach_context(
            started.revision,
            ContextAttachment {
                run_id: envelope.run_id.to_string(),
                request_digest: envelope.request_digest.to_string(),
                objective_digest: envelope.objective_digest.to_string(),
                body_digest: envelope.body_digest.to_string(),
                artifact_set_digest: envelope.artifact_set_digest.to_string(),
                context_digest: envelope.context_digest.to_string(),
                compilation_receipt_digest: envelope.context_receipt_digest.to_string(),
            },
        )
        .map_err(IntelligenceControlCallerErrorV1::Runtime)?;

    Ok(IntelligenceAdmissionReceiptV1 {
        run,
        envelope_digest: envelope.envelope_digest,
        composition_trace_digest: envelope.composition_trace_digest,
    })
}

#[cfg(test)]
#[path = "intelligence_control_tests.rs"]
mod tests;
