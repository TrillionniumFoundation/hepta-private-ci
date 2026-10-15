//! Canonical bounded encoding of a complete terminal product decision.
use super::*;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTQE01";
const MAX_METRICS: usize = 128;
const CHECKSUM_DOMAIN: &[u8] = b"hepta.product-qualification-record.checksum.v1";

pub(super) fn encode(
    execution: Digest32,
    signed: &SignedEvaluationDecisionV1,
) -> Result<Vec<u8>, ProductEvidenceSinkErrorV1> {
    let decision = &signed.decision;
    if [
        execution,
        decision.evidence_digest,
        signed.trust_digest,
        signed.authentication_digest,
    ]
    .iter()
    .any(|digest| digest.is_zero())
        || decision.authority.grants_any()
        || decision.failed_metrics.len() > MAX_METRICS
        || decision
            .failed_metrics
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let mut bytes = MAGIC.to_vec();
    for digest in [
        execution,
        decision.evidence_digest,
        signed.trust_digest,
        signed.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for id in [
        &decision.evaluation_id,
        &decision.candidate_id,
        &decision.baseline_id,
    ] {
        put_id(&mut bytes, id);
    }
    bytes.push(match decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(decision.failed_metrics.len() as u16).to_be_bytes());
    for id in &decision.failed_metrics {
        put_id(&mut bytes, id);
    }
    bytes.push(0); // AuthorityPosture::DENY_ALL is the only permitted wire value.
    bytes.extend_from_slice(checksum(&bytes).as_array());
    if bytes.len() as u64 > MAX_EVIDENCE_BYTES {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    Ok(bytes)
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

pub(super) fn decode(
    bytes: &[u8],
) -> Result<(Digest32, SignedEvaluationDecisionV1), ProductEvidenceSinkErrorV1> {
    if bytes.len() < MAGIC.len() + 32 || bytes.len() as u64 > MAX_EVIDENCE_BYTES {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let (body, checksum) = bytes.split_at(bytes.len() - 32);
    if checksum != self::checksum(body).as_array() {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let mut input = body;
    if take(&mut input, MAGIC.len())? != MAGIC {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let mut digests = [Digest32::ZERO; 4];
    for digest in &mut digests {
        let mut raw = [0; 32];
        raw.copy_from_slice(take(&mut input, /*count*/ 32)?);
        *digest = Digest32::from_array(raw);
    }
    let evaluation_id = id(&mut input)?;
    let candidate_id = id(&mut input)?;
    let baseline_id = id(&mut input)?;
    let disposition = match take(&mut input, /*count*/ 1)?[0] {
        0 => IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        1 => IndependentEvaluationDispositionV1::Ineligible,
        2 => IndependentEvaluationDispositionV1::InsufficientEvidence,
        _ => return Err(ProductEvidenceSinkErrorV1::Rejected),
    };
    let count = short(&mut input)? as usize;
    if count > MAX_METRICS {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let mut failed_metrics = Vec::with_capacity(count);
    for _ in 0..count {
        failed_metrics.push(id(&mut input)?);
    }
    let authority = AuthorityPosture::try_from_wire_bytes(take(&mut input, /*count*/ 1)?)
        .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)?;
    if !input.is_empty() {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    let signed = SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id,
            candidate_id,
            baseline_id,
            disposition,
            failed_metrics,
            evidence_digest: digests[1],
            authority,
        },
        trust_digest: digests[2],
        authentication_digest: digests[3],
    };
    if encode(digests[0], &signed)? != bytes {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    Ok((digests[0], signed))
}

fn checksum(body: &[u8]) -> Digest32 {
    Digest32::of_bytes(&[CHECKSUM_DOMAIN, body].concat())
}

fn take<'a>(input: &mut &'a [u8], count: usize) -> Result<&'a [u8], ProductEvidenceSinkErrorV1> {
    let (head, tail) = input
        .split_at_checked(count)
        .ok_or(ProductEvidenceSinkErrorV1::Rejected)?;
    *input = tail;
    Ok(head)
}
fn short(input: &mut &[u8]) -> Result<u16, ProductEvidenceSinkErrorV1> {
    let raw = take(input, /*count*/ 2)?;
    Ok(u16::from_be_bytes([raw[0], raw[1]]))
}
fn id(input: &mut &[u8]) -> Result<StableId, ProductEvidenceSinkErrorV1> {
    let count = short(input)? as usize;
    if !(1..=128).contains(&count) {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    StableId::new(
        std::str::from_utf8(take(input, count)?)
            .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)?,
    )
    .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)
}
