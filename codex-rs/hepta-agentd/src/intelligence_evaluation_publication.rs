//! Product evaluation publication through the ordinary Agentd evidence endpoint.
//! No new database, implicit signer, test credentials or publication authority.
use std::sync::Arc;

use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReceiptKindV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::qualification_envelope_bytes;
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::product_qualification_publication_payload_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::Value;
use tokio::runtime::Handle;
use tokio::runtime::RuntimeFlavor;

use crate::AgentdClient;
use crate::KernelEvidenceAppendIngress;

/// Envelope payload for the existing kernel.evidence product protocol.
/// Sign the full envelope using `kernel_evidence_claims`, not this JSON alone.
pub fn evaluation_publication_envelope_payload(terminal_payload: &[u8]) -> Value {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut hex = String::with_capacity(terminal_payload.len().saturating_mul(2));
    for byte in terminal_payload {
        hex.push(char::from(HEX[usize::from(byte >> 4)]));
        hex.push(char::from(HEX[usize::from(byte & 15)]));
    }
    serde_json::json!({
        "schema": "hepta.learning-eval.terminal-publication.v1",
        "terminal_payload_hex": hex,
    })
}

/// One publication identity per frozen evaluation plan in this Agent's existing
/// evidence namespace. Changed inputs/results or a new transport message cannot
/// create a second successful publication for the same plan.
pub fn evaluation_publication_evidence_id(
    evaluation_id: &StableId,
) -> Result<EvidenceId, ProductEvidenceSinkErrorV1> {
    let mut bytes = b"hepta.learning-eval.publication-identity.v1".to_vec();
    bytes.extend_from_slice(evaluation_id.as_str().as_bytes());
    EvidenceId::parse(format!("evaluation:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)
}

/// A fixed, durably retained signed intent, submitted through the real daemon.
/// Construct only after the host has persisted this exact ingress in its
/// existing operation/outbox owner. Recovery supplies that same ingress again;
/// neither a lost response nor a new connection generates a new message or
/// evidence identity. The evidence owner performs transactional deduplication.
pub struct AgentdEvaluationEvidenceSinkV1 {
    client: Arc<AgentdClient>,
    runtime: Handle,
    request: KernelEvidenceAppendIngress,
    envelope: QualificationEvidenceEnvelopeV1,
    publication_digest: Digest32,
}

impl AgentdEvaluationEvidenceSinkV1 {
    pub fn from_signed_intent(
        client: Arc<AgentdClient>,
        runtime: Handle,
        request: KernelEvidenceAppendIngress,
    ) -> Result<Self, ProductEvidenceSinkErrorV1> {
        use ProductEvidenceSinkErrorV1::Rejected;
        if runtime.runtime_flavor() != RuntimeFlavor::MultiThread {
            return Err(ProductEvidenceSinkErrorV1::Unavailable);
        }
        if request.envelope_json.len()
            > codex_hepta_agent_protocol::MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES
        {
            return Err(Rejected);
        }
        let envelope: QualificationEvidenceEnvelopeV1 =
            serde_json::from_str(&request.envelope_json).map_err(|_| Rejected)?;
        envelope.validate().map_err(|_| Rejected)?;
        if envelope.receipt_kind != EvidenceReceiptKindV1::Evidence
            || envelope.issuer_role != EvidenceIssuerRoleV1::Evaluator
            // This adapter publishes causal qualification, not a separately
            // accepted real-future-window or operator-acceptance claim.
            || envelope.claim_class != EvidenceClaimClassV1::Causal
            || envelope.expires_unix_ms.is_none()
        {
            return Err(Rejected);
        }
        let canonical = qualification_envelope_bytes(&envelope).map_err(|_| Rejected)?;
        if canonical.as_slice() != request.envelope_json.as_bytes() {
            return Err(Rejected);
        }
        Ok(Self {
            client,
            runtime,
            request,
            envelope,
            publication_digest: Digest32::of_bytes(&canonical),
        })
    }
}

impl ProductQualificationEvidenceSinkV1 for AgentdEvaluationEvidenceSinkV1 {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        use ProductEvidenceSinkErrorV1::Indeterminate;
        use ProductEvidenceSinkErrorV1::Rejected;
        use ProductEvidenceSinkErrorV1::Unavailable;
        let terminal = product_qualification_publication_payload_v1(execution_digest, decision)
            .map_err(|_| Rejected)?;
        if self.envelope.evidence_id
            != evaluation_publication_evidence_id(&decision.decision.evaluation_id)?
            || self.envelope.candidate.candidate_id != decision.decision.candidate_id.as_str()
            || self.envelope.payload != evaluation_publication_envelope_payload(&terminal)
        {
            return Err(Rejected);
        }
        // Never panic or deadlock by blocking a single-thread async executor.
        // Product evaluations run on the existing bounded blocking worker;
        // block_in_place also permits a multithread host to use this sync port.
        if Handle::try_current().is_ok_and(|h| h.runtime_flavor() == RuntimeFlavor::CurrentThread) {
            return Err(Unavailable);
        }
        let result = tokio::task::block_in_place(|| {
            self.runtime
                .block_on(self.client.append_kernel_evidence(self.request.clone()))
        });
        // The ordinary client has a bounded transport deadline. Any transport,
        // response or post-commit readiness failure is conservatively unknown:
        // it may already have committed, so never issue a fresh signed intent.
        let id = result.map_err(|_| Indeterminate)?;
        if id != self.envelope.evidence_id {
            return Err(Indeterminate);
        }
        Ok(self.publication_digest)
    }
}
