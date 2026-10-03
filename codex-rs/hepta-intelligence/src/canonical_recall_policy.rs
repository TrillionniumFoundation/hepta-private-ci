//! Product-level recall policy binding for the canonical intelligence outcome.
//!
//! The core canonical runner supports a selected recall packet or no recall.
//! Product callers must make that choice observable: a bound packet contributes
//! its checked consumer-binding digest, while deliberate absence contributes an
//! explicit non-zero reason digest. The resulting policy digest is folded into
//! the terminal trace and, for ready outcomes, the final host-envelope digest.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CanonicalIntelligenceError;
use crate::CanonicalRecallIntelligenceInputV1;
use crate::CanonicalRunOutcomeV1;
use crate::IntelligenceHostEnvelopeV1;

#[cfg(test)]
use crate::AdvisoryDecisionReceiptV1;
#[cfg(test)]
use crate::AdvisoryDecisionV1;
#[cfg(test)]
use crate::CanonicalTerminalReceiptV1;
#[cfg(test)]
use codex_hepta_types::AuthorityPosture;

const RECALL_POLICY_DOMAIN_V1: &[u8] = b"hepta.intelligence.recall-product-policy.v1\0";
const RECALL_TRACE_DOMAIN_V1: &[u8] = b"hepta.intelligence.recall-policy-trace.v1\0";

pub fn canonical_recall_binding_policy_digest_v1(
    recall: &CanonicalRecallIntelligenceInputV1,
) -> Result<Digest32, CanonicalIntelligenceError> {
    recall.validate()?;
    Ok(Digest32::of_parts(&[
        RECALL_POLICY_DOMAIN_V1,
        b"bound\0",
        recall.consumer_binding.binding_sha256.digest().as_array(),
    ]))
}

pub fn canonical_recall_absence_policy_digest_v1(
    reason_digest: Digest32,
) -> Result<Digest32, CanonicalIntelligenceError> {
    if reason_digest.is_zero() {
        return Err(CanonicalIntelligenceError::CanonicalRecall(
            "explicit recall absence requires a non-zero reason digest".to_owned(),
        ));
    }
    Ok(Digest32::of_parts(&[
        RECALL_POLICY_DOMAIN_V1,
        b"explicitly_absent\0",
        reason_digest.as_array(),
    ]))
}

pub fn bind_recall_policy_outcome_v1(
    outcome: CanonicalRunOutcomeV1,
    policy_digest: Digest32,
) -> Result<CanonicalRunOutcomeV1, CanonicalIntelligenceError> {
    if policy_digest.is_zero() {
        return Err(CanonicalIntelligenceError::CanonicalRecall(
            "recall policy digest must be non-zero".to_owned(),
        ));
    }
    match outcome {
        CanonicalRunOutcomeV1::Ready(mut envelope) => {
            envelope.trace_digest = bind_trace(envelope.trace_digest, policy_digest);
            envelope.envelope_digest = digest_host_envelope(&envelope)?;
            Ok(CanonicalRunOutcomeV1::Ready(envelope))
        }
        CanonicalRunOutcomeV1::Abstained(mut terminal) => {
            terminal.trace_digest = bind_trace(terminal.trace_digest, policy_digest);
            Ok(CanonicalRunOutcomeV1::Abstained(terminal))
        }
        CanonicalRunOutcomeV1::SlowPath(mut terminal) => {
            terminal.trace_digest = bind_trace(terminal.trace_digest, policy_digest);
            Ok(CanonicalRunOutcomeV1::SlowPath(terminal))
        }
    }
}

fn bind_trace(trace_digest: Digest32, policy_digest: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        RECALL_TRACE_DOMAIN_V1,
        trace_digest.as_array(),
        policy_digest.as_array(),
    ])
}

fn digest_host_envelope(
    envelope: &IntelligenceHostEnvelopeV1,
) -> Result<Digest32, CanonicalIntelligenceError> {
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    push_id(&mut bytes, &envelope.run_id)?;
    for digest in [
        envelope.snapshot_digest,
        envelope.objective_digest,
        envelope.candidate_set_digest,
        envelope.utility_receipt_digest,
        envelope.neural_receipt_digest,
        envelope.prompt_receipt_digest,
        envelope.decision.decision_digest,
        envelope.context_receipt_digest,
        envelope.context_binding_digest,
        envelope.evaluation_receipt_digest,
        envelope.trace_digest,
    ] {
        if digest.is_zero() {
            return Err(CanonicalIntelligenceError::EmptyDigest(
                "recall-policy host envelope",
            ));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CanonicalIntelligenceError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn decision() -> AdvisoryDecisionReceiptV1 {
        AdvisoryDecisionReceiptV1 {
            run_id: id("run:recall-policy"),
            candidate_set_digest: digest("candidates"),
            intuition_receipt_digest: digest("intuition"),
            decision: AdvisoryDecisionV1::Abstained,
            decision_digest: digest("decision"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn terminal() -> CanonicalTerminalReceiptV1 {
        CanonicalTerminalReceiptV1 {
            run_id: id("run:recall-policy"),
            snapshot_digest: digest("snapshot"),
            candidate_set_digest: digest("candidates"),
            decision: decision(),
            trace_digest: digest("trace"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn explicit_absence_is_non_zero_and_changes_the_terminal_trace() {
        assert!(canonical_recall_absence_policy_digest_v1(Digest32::ZERO).is_err());
        let first = canonical_recall_absence_policy_digest_v1(digest("reason:first"))
            .expect("first policy");
        let second = canonical_recall_absence_policy_digest_v1(digest("reason:second"))
            .expect("second policy");
        let CanonicalRunOutcomeV1::Abstained(first_outcome) =
            bind_recall_policy_outcome_v1(CanonicalRunOutcomeV1::Abstained(terminal()), first)
                .expect("first outcome")
        else {
            panic!("terminal")
        };
        let CanonicalRunOutcomeV1::Abstained(second_outcome) =
            bind_recall_policy_outcome_v1(CanonicalRunOutcomeV1::Abstained(terminal()), second)
                .expect("second outcome")
        else {
            panic!("terminal")
        };
        assert_ne!(first_outcome.trace_digest, digest("trace"));
        assert_ne!(first_outcome.trace_digest, second_outcome.trace_digest);
    }
}
