//! Bounded transfer of the original Observer signing payload. Decoding creates
//! no authenticated receipt; the existing registered runner verifies its signer.
use crate::PairedClassObservationV1;
use crate::PairedNativeObservationV1;
use crate::PairedObservationCutV1;
use crate::PairedObservedMetricV1;
use crate::PairedRuntimeBindingV1;
use crate::PairedSupervisedErrorV1;
use crate::PairedTaskObservationV1;
use crate::SignedPairedObservationCutV1;
use crate::paired_observation_cut_signing_payload_v1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::decode_review_payload_hex;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const DOMAIN: &[u8] = b"hepta.eval.paired-supervised.observer-cut.v1";
pub(crate) const MAX_TRANSPORT_BYTES: u64 = 65 * 1024 * 1024;
const MAX_PAYLOAD_BYTES: usize = 32 * 1024 * 1024;
type Result<T> = std::result::Result<T, PairedSupervisedErrorV1>;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Transport {
    schema: String,
    payload_hex: String,
    observer_evidence: ReviewEvidenceWireV1,
}

/// Serialize an already signed original O cut for immutable custody transfer.
/// This function has no signing key and does not authenticate caller assertions.
pub fn encode_signed_paired_observation_transport_v1(
    observations: &SignedPairedObservationCutV1,
) -> Result<Vec<u8>> {
    let payload = paired_observation_cut_signing_payload_v1(&observations.cut)?;
    let bytes = serde_json::to_vec(&Transport {
        schema: "hepta.eval.signed-paired-observation-transport.v1".to_owned(),
        payload_hex: payload.iter().map(|byte| format!("{byte:02x}")).collect(),
        observer_evidence: ReviewEvidenceWireV1::from_native(&observations.observer_evidence),
    })
    .map_err(|_| invalid())?;
    if bytes.len() as u64 > MAX_TRANSPORT_BYTES {
        return Err(invalid());
    }
    Ok(bytes)
}

pub(crate) fn decode_transport(bytes: &[u8]) -> Result<SignedPairedObservationCutV1> {
    if bytes.len() as u64 > MAX_TRANSPORT_BYTES {
        return Err(invalid());
    }
    let wire: Transport = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if wire.schema != "hepta.eval.signed-paired-observation-transport.v1"
        || wire.payload_hex.len() > MAX_PAYLOAD_BYTES * 2
        || wire.observer_evidence.signature_hex.len() != 128
    {
        return Err(invalid());
    }
    let payload = decode_review_payload_hex(&wire.payload_hex).map_err(|_| invalid())?;
    let cut = decode_payload(&payload)?;
    let evidence = wire.observer_evidence.native().map_err(|_| invalid())?;
    if evidence.payload_digest != Digest32::of_bytes(&payload) {
        return Err(invalid());
    }
    Ok(SignedPairedObservationCutV1 {
        cut,
        observer_evidence: evidence,
    })
}

fn decode_payload(bytes: &[u8]) -> Result<PairedObservationCutV1> {
    if !bytes.starts_with(DOMAIN) || bytes.len() > MAX_PAYLOAD_BYTES {
        return Err(invalid());
    }
    let mut input = Cursor(&bytes[DOMAIN.len()..]);
    let plan_digest = input.digest()?;
    let source_graph_digest = input.digest()?;
    let runtime = PairedRuntimeBindingV1 {
        candidate_artifact_digest: input.digest()?,
        deployed_baseline_digest: input.digest()?,
        candidate_runtime_digest: input.digest()?,
        baseline_runtime_digest: input.digest()?,
        task_input_contract_digest: input.digest()?,
    };
    let unlearning_receipt_digest = input.digest()?;
    let started_at_unix_micros = input.u64()?;
    let finished_at_unix_micros = input.u64()?;
    let retention_receipt_digests = (0..input.count(128)?)
        .map(|_| input.digest())
        .collect::<Result<Vec<_>>>()?;
    let count = input.count(crate::paired_supervised_plan::MAX_PAIRED_TASKS)?;
    let mut rows = Vec::new();
    for _ in 0..count {
        let source_record_digest = input.digest()?;
        let candidate = input.observation()?;
        let baseline = input.observation()?;
        let observed_metrics = (0..input.count(128)?)
            .map(|_| {
                Ok(PairedObservedMetricV1 {
                    metric_id: input.id()?,
                    candidate: input.q32()?,
                    baseline: input.q32()?,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        rows.push(PairedTaskObservationV1 {
            source_record_digest,
            candidate,
            baseline,
            observed_metrics,
        });
    }
    let cut = PairedObservationCutV1 {
        plan_digest,
        source_graph_digest,
        runtime,
        started_at_unix_micros,
        finished_at_unix_micros,
        rows,
        retention_receipt_digests,
        unlearning_receipt_digest,
    };
    if !input.0.is_empty() || paired_observation_cut_signing_payload_v1(&cut)? != bytes {
        return Err(invalid());
    }
    Ok(cut)
}

struct Cursor<'a>(&'a [u8]);
impl<'a> Cursor<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8]> {
        let (head, tail) = self.0.split_at_checked(count).ok_or_else(invalid)?;
        self.0 = tail;
        Ok(head)
    }
    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| invalid())?,
        ))
    }
    fn count(&mut self, maximum: usize) -> Result<usize> {
        let count = usize::try_from(self.u64()?).map_err(|_| invalid())?;
        if count > maximum {
            return Err(invalid());
        }
        Ok(count)
    }
    fn digest(&mut self) -> Result<Digest32> {
        Ok(Digest32::from_array(
            self.take(32)?.try_into().map_err(|_| invalid())?,
        ))
    }
    fn id(&mut self) -> Result<StableId> {
        let count = u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| invalid())?) as usize;
        StableId::new(std::str::from_utf8(self.take(count)?).map_err(|_| invalid())?)
            .map_err(|_| invalid())
    }
    fn q32(&mut self) -> Result<Option<FixedQ32>> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(FixedQ32::from_raw(i64::from_be_bytes(
                self.take(8)?.try_into().map_err(|_| invalid())?,
            )))),
            _ => Err(invalid()),
        }
    }
    fn observation(&mut self) -> Result<PairedNativeObservationV1> {
        let request_id = self.id()?;
        let input_digest = self.digest()?;
        let original_native_observation_digest = self.digest()?;
        let started_at_unix_micros = self.u64()?;
        let finished_at_unix_micros = self.u64()?;
        let original_elapsed_micros = match self.byte()? {
            0 => None,
            1 => Some(self.u64()?),
            _ => return Err(invalid()),
        };
        let outcome = match self.byte()? {
            0 => {
                let class_id = self.id()?;
                let correct = match self.byte()? {
                    0 => false,
                    1 => true,
                    _ => return Err(invalid()),
                };
                PairedClassObservationV1::Label { class_id, correct }
            }
            1 => PairedClassObservationV1::Abstain,
            2 => PairedClassObservationV1::Censored { reason: self.id()? },
            _ => return Err(invalid()),
        };
        Ok(PairedNativeObservationV1 {
            request_id,
            input_digest,
            original_native_observation_digest,
            started_at_unix_micros,
            finished_at_unix_micros,
            original_elapsed_micros,
            outcome,
        })
    }
}

fn invalid() -> PairedSupervisedErrorV1 {
    PairedSupervisedErrorV1::Binding("original paired Observer transport")
}

#[cfg(test)]
#[path = "paired_observer_transport_tests.rs"]
mod tests;
