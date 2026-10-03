//! One finite portable codec for the original request and complete failure facts.
use super::*;

// JSON escaping expands a valid 8 KiB original prompt by at most six times.
pub const MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1: usize = 64 * 1024;
pub const MAX_SELF_ITERATION_NATIVE_FAILURE_RECORD_BYTES_V1: usize = 64 * 1024;
pub const MAX_SELF_ITERATION_ROOT_FAILURE_OUTCOME_BYTES_V1: usize = 256 * 1024;
pub const MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1: usize = 512 * 1024;
const MAGIC: &[u8; 8] = b"HPTSMF01";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RequestWire {
    request_id: String,
    role: u8,
    envelope_digest: String,
    candidate_digest: Option<String>,
    prompt: String,
    deadline_ms: u64,
    maximum_response_bytes: u32,
}

pub fn encode_self_iteration_model_request_v1(
    request: &SelfIterationModelRequestV1,
) -> Result<Vec<u8>, SelfIterationModelErrorV1> {
    request.validate(
        request
            .deadline_ms
            .checked_sub(1)
            .ok_or(SelfIterationModelErrorV1::InvalidRequest)?,
    )?;
    let bytes = serde_json::to_vec(&RequestWire {
        request_id: request.request_id.to_string(),
        role: request.role as u8,
        envelope_digest: request.envelope_digest.to_string(),
        candidate_digest: request.candidate_digest.map(|digest| digest.to_string()),
        prompt: request.prompt.clone(),
        deadline_ms: request.deadline_ms,
        maximum_response_bytes: request.maximum_response_bytes,
    })
    .map_err(|_| SelfIterationModelErrorV1::InvalidRequest)?;
    bounded(&bytes, MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1)?;
    Ok(bytes)
}

pub fn decode_self_iteration_model_request_v1(
    bytes: &[u8],
) -> Result<SelfIterationModelRequestV1, SelfIterationModelErrorV1> {
    bounded(bytes, MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1)?;
    let wire: RequestWire =
        serde_json::from_slice(bytes).map_err(|_| SelfIterationModelErrorV1::InvalidRequest)?;
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new(wire.request_id)
            .map_err(|_| SelfIterationModelErrorV1::InvalidRequest)?,
        role: match wire.role {
            0 => SelfIterationModelRoleV1::Generator,
            1 => SelfIterationModelRoleV1::Evaluator,
            2 => SelfIterationModelRoleV1::Selector,
            3 => SelfIterationModelRoleV1::Observer,
            _ => return Err(SelfIterationModelErrorV1::InvalidRequest),
        },
        envelope_digest: wire
            .envelope_digest
            .parse()
            .map_err(|_| SelfIterationModelErrorV1::InvalidRequest)?,
        candidate_digest: wire
            .candidate_digest
            .map(|digest| digest.parse())
            .transpose()
            .map_err(|_| SelfIterationModelErrorV1::InvalidRequest)?,
        prompt: wire.prompt,
        deadline_ms: wire.deadline_ms,
        maximum_response_bytes: wire.maximum_response_bytes,
    };
    if encode_self_iteration_model_request_v1(&request)? != bytes {
        return Err(SelfIterationModelErrorV1::InvalidRequest);
    }
    Ok(request)
}

pub fn encode_self_iteration_model_failure_facts_v1(
    facts: &SelfIterationModelFailureFactsV1,
) -> Result<Vec<u8>, SelfIterationModelErrorV1> {
    if facts.observed_at_ms == 0 {
        return Err(SelfIterationModelErrorV1::InvalidResponse);
    }
    let request = encode_self_iteration_model_request_v1(&facts.request)?;
    let native = serde_json::to_vec(&facts.native_record)
        .map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?;
    bounded(&native, MAX_SELF_ITERATION_NATIVE_FAILURE_RECORD_BYTES_V1)?;
    bounded(
        &facts.root_outcome_bytes,
        MAX_SELF_ITERATION_ROOT_FAILURE_OUTCOME_BYTES_V1,
    )?;
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(&facts.observed_at_ms.to_be_bytes());
    for blob in [&request, &native, &facts.root_outcome_bytes] {
        let len =
            u32::try_from(blob.len()).map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?;
        bytes.extend_from_slice(&len.to_be_bytes());
        bytes.extend_from_slice(blob);
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bounded(&bytes, MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1)?;
    Ok(bytes)
}

pub fn decode_self_iteration_model_failure_facts_v1(
    bytes: &[u8],
) -> Result<SelfIterationModelFailureFactsV1, SelfIterationModelErrorV1> {
    bounded(bytes, MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1)?;
    if bytes.len() < 60 || &bytes[..8] != MAGIC {
        return Err(SelfIterationModelErrorV1::InvalidResponse);
    }
    let end = bytes.len() - 32;
    if Digest32::of_bytes(&bytes[..end]).as_array() != &bytes[end..] {
        return Err(SelfIterationModelErrorV1::InvalidResponse);
    }
    let observed_at_ms = u64::from_be_bytes(
        bytes[8..16]
            .try_into()
            .map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?,
    );
    let mut cursor = 16usize;
    let mut read = |limit| -> Result<&[u8], SelfIterationModelErrorV1> {
        let len_end = cursor
            .checked_add(4)
            .ok_or(SelfIterationModelErrorV1::InvalidResponse)?;
        let len = u32::from_be_bytes(
            bytes
                .get(cursor..len_end)
                .ok_or(SelfIterationModelErrorV1::InvalidResponse)?
                .try_into()
                .map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?,
        ) as usize;
        let blob_end = len_end
            .checked_add(len)
            .ok_or(SelfIterationModelErrorV1::InvalidResponse)?;
        if blob_end > end || len == 0 || len > limit {
            return Err(SelfIterationModelErrorV1::InvalidResponse);
        }
        cursor = blob_end;
        bytes
            .get(len_end..blob_end)
            .ok_or(SelfIterationModelErrorV1::InvalidResponse)
    };
    let request =
        decode_self_iteration_model_request_v1(read(MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1)?)?;
    let native = read(MAX_SELF_ITERATION_NATIVE_FAILURE_RECORD_BYTES_V1)?;
    let native_record =
        serde_json::from_slice(native).map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?;
    let root_outcome_bytes = read(MAX_SELF_ITERATION_ROOT_FAILURE_OUTCOME_BYTES_V1)?.to_vec();
    let facts = SelfIterationModelFailureFactsV1 {
        request,
        native_record,
        root_outcome_bytes,
        observed_at_ms,
    };
    if cursor != end || encode_self_iteration_model_failure_facts_v1(&facts)? != bytes {
        return Err(SelfIterationModelErrorV1::InvalidResponse);
    }
    Ok(facts)
}

fn bounded(bytes: &[u8], limit: usize) -> Result<(), SelfIterationModelErrorV1> {
    if bytes.is_empty() || bytes.len() > limit {
        Err(SelfIterationModelErrorV1::InvalidResponse)
    } else {
        Ok(())
    }
}

#[cfg(test)]
#[path = "self_iteration_failure_codec_tests.rs"]
mod tests;
