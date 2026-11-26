//! Existing V2 governed admission with original opaque evidence at final use.
use super::AnchoredPlasticityWriterV1;
use super::DurableProposalRegistryError;
use super::LearningEvidenceVerifierV1;
use super::ParameterPlasticityProductErrorV1;
use super::ParameterPlasticityProductReceiptV1;
use super::ParameterPlasticityProductRequestV1;
use super::PlasticityAnchorCommitterV1;
use super::PlasticityWriterStateV1;
use super::SignedEvaluationError;
use super::prepared;

/// Host composition rechecks the original opaque authenticated participants at
/// the final synchronous admission, after proposal encoding and before writing.
/// It preserves the V2 exact-consumer binding and grants no selection authority.
pub fn propose_authenticated_parameter_plasticity_with_final_time_v1(
    request: ParameterPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_committer: &mut impl PlasticityAnchorCommitterV1,
    now: u64,
    final_time: &mut impl FnMut() -> Result<u64, ParameterPlasticityProductErrorV1>,
) -> Result<ParameterPlasticityProductReceiptV1, ParameterPlasticityProductErrorV1> {
    use ParameterPlasticityProductErrorV1 as E;

    if writer.state != PlasticityWriterStateV1::Healthy {
        return Err(E::Registry(DurableProposalRegistryError::Poisoned));
    }
    let prepared = prepared::prepare(&request, verifier, now)?;
    let prepared::Prepared {
        proposal,
        participants,
        disposition,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
    } = prepared;
    let writer_state = &mut writer.state;
    let registry = match writer.registry.append_v2_after_admission(
        request.expected_registry_predecessor,
        proposal.clone(),
        || {
            let final_now = final_time()?;
            if final_now < now {
                return Err(E::Binding("host clock regressed before append"));
            }
            for participant in &participants {
                verifier
                    .revalidate(participant, final_now)
                    .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
            }
            *writer_state = PlasticityWriterStateV1::AppendPendingAnchor;
            Ok::<(), E>(())
        },
    ) {
        Ok(receipt) => receipt,
        Err(error) => {
            writer.state = if matches!(
                error,
                E::Registry(
                    DurableProposalRegistryError::Indeterminate
                        | DurableProposalRegistryError::Poisoned
                        | DurableProposalRegistryError::Io(_)
                )
            ) {
                PlasticityWriterStateV1::Poisoned
            } else {
                PlasticityWriterStateV1::Healthy
            };
            return Err(error);
        }
    };
    let committed_registry_anchor = match writer.registry.current_anchor() {
        Ok(Some(anchor)) => anchor,
        Ok(None) => {
            writer.state = PlasticityWriterStateV1::Poisoned;
            return Err(E::Registry(DurableProposalRegistryError::Corrupt));
        }
        Err(error) => {
            writer.state = PlasticityWriterStateV1::Poisoned;
            return Err(E::Registry(error));
        }
    };
    if !anchor_committer.persist_anchor(
        writer.registry_scope_digest,
        writer.writer_fence,
        committed_registry_anchor,
    ) {
        writer.state = PlasticityWriterStateV1::Poisoned;
        return Err(E::AnchorPersistenceFailed);
    }
    writer.state = PlasticityWriterStateV1::Healthy;

    Ok(prepared::receipt(
        proposal,
        registry,
        request.generated.generator_digest,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
        disposition,
        committed_registry_anchor,
    ))
}
