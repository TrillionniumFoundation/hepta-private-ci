//! Original archive codec for raw plasticity materials; no sealed admission.
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::recorded_publication::archive::codec::Reader;
use crate::recorded_publication::archive::codec::Wire;
use crate::recorded_publication::archive::codec::Writer;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

pub fn encode_untrusted_plasticity_evaluation_v1(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    evidence: &SignedEvaluationEvidenceV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let mut output = Writer::default();
    output.put(b"hepta.eval.raw-plasticity.v1\0")?;
    bundle.write(&mut output)?;
    roles.to_vec().write(&mut output)?;
    evidence.write(&mut output)?;
    Ok(output.finish())
}

pub fn decode_untrusted_plasticity_evaluation_v1(
    bytes: &[u8],
) -> Result<
    (
        IndependentEvaluationBundleV1,
        Vec<MetricRoleContractV2>,
        SignedEvaluationEvidenceV1,
    ),
    ProductEvaluationError,
> {
    let mut input = Reader::new(bytes)?;
    if input.take(b"hepta.eval.raw-plasticity.v1\0".len())? != b"hepta.eval.raw-plasticity.v1\0" {
        return Err(ProductEvaluationError::Integrity(
            "raw plasticity codec domain",
        ));
    }
    let result = (
        IndependentEvaluationBundleV1::read(&mut input)?,
        Vec::<MetricRoleContractV2>::read(&mut input)?,
        SignedEvaluationEvidenceV1::read(&mut input)?,
    );
    input.finish()?;
    if encode_untrusted_plasticity_evaluation_v1(&result.0, &result.1, &result.2)? != bytes {
        return Err(ProductEvaluationError::Integrity(
            "raw plasticity canonical bytes",
        ));
    }
    Ok(result)
}

pub fn encode_untrusted_plasticity_learning_evidence_v1(
    evidence: &SignedLearningEvidenceV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let mut output = Writer::default();
    evidence.write(&mut output)?;
    Ok(output.finish())
}

pub fn decode_untrusted_plasticity_learning_evidence_v1(
    bytes: &[u8],
) -> Result<SignedLearningEvidenceV1, ProductEvaluationError> {
    let mut input = Reader::new(bytes)?;
    let result = SignedLearningEvidenceV1::read(&mut input)?;
    input.finish()?;
    if encode_untrusted_plasticity_learning_evidence_v1(&result)? != bytes {
        return Err(ProductEvaluationError::Integrity(
            "raw plasticity evidence bytes",
        ));
    }
    Ok(result)
}
