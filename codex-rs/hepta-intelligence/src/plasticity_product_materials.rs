//! Full raw request/receipt bytes. Decoding does not authenticate use or custody.
use super::wire::*;
use super::*;
use codex_hepta_intelligence_eval::decode_untrusted_plasticity_evaluation_v1;
use codex_hepta_intelligence_eval::decode_untrusted_plasticity_learning_evidence_v1;
use codex_hepta_intelligence_eval::encode_untrusted_plasticity_evaluation_v1;
use codex_hepta_intelligence_eval::encode_untrusted_plasticity_learning_evidence_v1;
use codex_hepta_plasticity::AppendDisposition;
use codex_hepta_plasticity::DurableCompletedProposalV1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
const REQUEST: &[u8] = b"HPTPMQ01";
const RECEIPT: &[u8] = b"HPTPMR01";
pub const MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1: usize = MAX;

pub fn encode_parameter_plasticity_request_v1(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Vec<u8>> {
    verify_generated_parameter_candidates_v3(
        request.generator_profile.clone(),
        &request.generated,
    )?;
    validate_admission_binding(request)?;
    if request.evaluations.len() > 32 {
        return Err(invalid());
    }
    let mut w = Writer(REQUEST.to_vec());
    w.id(&request.proposal_id)?;
    super::profile_wire::write(&request.generator_profile, &mut w)?;
    w.blob(
        &encode_untrusted_plasticity_learning_evidence_v1(&request.generator_attestation)
            .map_err(|_| invalid())?,
    )?;
    write_admission(&request.admission, &mut w)?;
    w.blob(
        &encode_untrusted_plasticity_learning_evidence_v1(&request.admission_attestation)
            .map_err(|_| invalid())?,
    )?;
    match &request.no_change_attestation {
        None => w.u8(0)?,
        Some(e) => {
            w.u8(1)?;
            w.blob(&encode_untrusted_plasticity_learning_evidence_v1(e).map_err(|_| invalid())?)?;
        }
    }
    w.u32(request.evaluations.len())?;
    for e in &request.evaluations {
        w.blob(
            &encode_untrusted_plasticity_evaluation_v1(&e.bundle, &e.metric_roles, &e.evidence)
                .map_err(|_| invalid())?,
        )?;
    }
    w.digest(request.expected_registry_predecessor)?;
    w.finish()
}

pub fn decode_parameter_plasticity_request_v1(
    bytes: &[u8],
) -> Result<ParameterPlasticityProductRequestV1> {
    let mut r = Reader::new(bytes, REQUEST)?;
    let proposal_id = r.id()?;
    let generator_profile = super::profile_wire::read(&mut r)?;
    let generated = generate_parameter_candidates_v3(generator_profile.clone())?;
    let generator_attestation =
        decode_untrusted_plasticity_learning_evidence_v1(r.blob()?).map_err(|_| invalid())?;
    let admission = read_admission(&mut r)?;
    let admission_attestation =
        decode_untrusted_plasticity_learning_evidence_v1(r.blob()?).map_err(|_| invalid())?;
    let no_change_attestation = match r.u8()? {
        0 => None,
        1 => Some(
            decode_untrusted_plasticity_learning_evidence_v1(r.blob()?).map_err(|_| invalid())?,
        ),
        _ => return Err(invalid()),
    };
    let mut evaluations = Vec::new();
    for _ in 0..r.len(32)? {
        let (bundle, metric_roles, evidence) =
            decode_untrusted_plasticity_evaluation_v1(r.blob()?).map_err(|_| invalid())?;
        evaluations.push(CandidateEvaluationAdmissionV1 {
            bundle,
            metric_roles,
            evidence,
        });
    }
    let expected_registry_predecessor = r.digest()?;
    r.finish()?;
    let request = ParameterPlasticityProductRequestV1 {
        proposal_id,
        generator_profile,
        generated,
        generator_attestation,
        admission,
        admission_attestation,
        no_change_attestation,
        evaluations,
        expected_registry_predecessor,
    };
    if encode_parameter_plasticity_request_v1(&request)? != bytes {
        return Err(invalid());
    }
    Ok(request)
}

pub fn encode_parameter_plasticity_receipt_v1(
    receipt: &ParameterPlasticityProductReceiptV1,
) -> Result<Vec<u8>> {
    if receipt.evaluation_digest != receipt.proposal.evaluation_digest
        || receipt.generator_authentication_digest.is_zero()
        || receipt.admission_authentication_digest.is_zero()
        || receipt.evaluation_digest.is_zero()
        || receipt.composition_digest.is_zero()
    {
        return Err(invalid());
    }
    let mut original = receipt.registry.clone();
    original.disposition = AppendDisposition::Inserted;
    let observation = DurableCompletedProposalV1 {
        proposal: receipt.proposal.clone(),
        receipt: original,
        acknowledged_head: receipt.committed_registry_anchor,
    };
    let mut w = Writer(RECEIPT.to_vec());
    w.blob(&observation.to_bytes()?)?;
    w.u8(match receipt.registry.disposition {
        AppendDisposition::Inserted => 0,
        AppendDisposition::Unchanged => 1,
    })?;
    w.u8(match receipt.disposition {
        ParameterPlasticityDispositionV1::UpdateCandidates => 0,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate => 1,
    })?;
    for d in [
        receipt.generator_authentication_digest,
        receipt.admission_authentication_digest,
        receipt.evaluation_digest,
        receipt.composition_digest,
    ] {
        w.digest(d)?;
    }
    w.finish()
}

pub fn decode_parameter_plasticity_receipt_v1(
    bytes: &[u8],
) -> Result<ParameterPlasticityProductReceiptV1> {
    let mut r = Reader::new(bytes, RECEIPT)?;
    let original = DurableCompletedProposalV1::from_bytes(r.blob()?)?;
    let mut registry = original.receipt;
    registry.disposition = match r.u8()? {
        0 => AppendDisposition::Inserted,
        1 => AppendDisposition::Unchanged,
        _ => return Err(invalid()),
    };
    let disposition = match r.u8()? {
        0 => ParameterPlasticityDispositionV1::UpdateCandidates,
        1 => ParameterPlasticityDispositionV1::NoAdmissibleUpdate,
        _ => return Err(invalid()),
    };
    let receipt = ParameterPlasticityProductReceiptV1 {
        proposal: original.proposal,
        registry,
        disposition,
        generator_authentication_digest: r.digest()?,
        admission_authentication_digest: r.digest()?,
        evaluation_digest: r.digest()?,
        composition_digest: r.digest()?,
        committed_registry_anchor: original.acknowledged_head,
    };
    r.finish()?;
    if encode_parameter_plasticity_receipt_v1(&receipt)? != bytes {
        return Err(invalid());
    }
    Ok(receipt)
}

fn write_admission(a: &PlasticityAdmissionEvidenceV1, w: &mut Writer) -> Result<()> {
    w.put(&codex_hepta_plasticity::encode_plasticity_admission_body_v1(a).map_err(|_| invalid())?)
}
fn read_admission(r: &mut Reader<'_>) -> Result<PlasticityAdmissionEvidenceV1> {
    let (a, n) =
        codex_hepta_plasticity::decode_plasticity_admission_body_prefix_v1(r.remaining_bytes())
            .map_err(|_| invalid())?;
    r.take(n)?;
    Ok(a)
}
