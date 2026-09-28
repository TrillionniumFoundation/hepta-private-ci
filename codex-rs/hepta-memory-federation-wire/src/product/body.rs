use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::MAX_FEDERATED_RESULTS_V2;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::error::FederationProductErrorV1;
use super::packet::require_body_bound;

const QUERY_BODY_SCHEMA: &str = "hepta.memory-federation.product-query.v1";
const RESPONSE_BODY_SCHEMA: &str = "hepta.memory-federation.product-response.v1";
const BODY_VERSION: u16 = 1;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct QueryBodyV1 {
    schema: String,
    version: u16,
    query_id: String,
    peer_id: String,
    principal_id: String,
    scope_digest: [u8; 32],
    purpose_digest: [u8; 32],
    generation_vector_digest: [u8; 32],
    query_digest: [u8; 32],
    maximum_results: u32,
    deadline_unix_ms: u64,
    lease_epoch: u64,
    nonce_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceBodyV1 {
    source_owner_id: String,
    record_id: String,
    record_revision: u64,
    record_digest: [u8; 32],
    support_digest: [u8; 32],
    validity_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ResponseBodyV1 {
    schema: String,
    version: u16,
    peer_id: String,
    query_binding_digest: [u8; 32],
    scope_digest: [u8; 32],
    purpose_digest: [u8; 32],
    generation_vector_digest: [u8; 32],
    response_digest: [u8; 32],
    observed_frontier: u64,
    expires_unix_ms: u64,
    items: Vec<EvidenceBodyV1>,
    completeness: u8,
    terminal_observed: bool,
}

pub fn encode_query_v2(query: &FederatedQueryV2) -> Result<Vec<u8>, FederationProductErrorV1> {
    encode_body(&QueryBodyV1 {
        schema: QUERY_BODY_SCHEMA.to_string(),
        version: BODY_VERSION,
        query_id: query.query_id.as_str().to_string(),
        peer_id: query.peer_id.as_str().to_string(),
        principal_id: query.principal_id.as_str().to_string(),
        scope_digest: query.scope_digest.into_array(),
        purpose_digest: query.purpose_digest.into_array(),
        generation_vector_digest: query.generation_vector_digest.into_array(),
        query_digest: query.query_digest.into_array(),
        maximum_results: query.maximum_results,
        deadline_unix_ms: query.deadline_unix_ms,
        lease_epoch: query.lease_epoch,
        nonce_digest: query.nonce_digest.into_array(),
    })
}

pub fn decode_query_v2(payload: &[u8]) -> Result<FederatedQueryV2, FederationProductErrorV1> {
    let body: QueryBodyV1 = decode_body(payload)?;
    if body.schema != QUERY_BODY_SCHEMA || body.version != BODY_VERSION {
        return Err(FederationProductErrorV1::BodySchemaMismatch);
    }
    Ok(FederatedQueryV2 {
        query_id: decode_id(body.query_id)?,
        peer_id: decode_id(body.peer_id)?,
        principal_id: decode_id(body.principal_id)?,
        scope_digest: Digest32::from_array(body.scope_digest),
        purpose_digest: Digest32::from_array(body.purpose_digest),
        generation_vector_digest: Digest32::from_array(body.generation_vector_digest),
        query_digest: Digest32::from_array(body.query_digest),
        maximum_results: body.maximum_results,
        deadline_unix_ms: body.deadline_unix_ms,
        lease_epoch: body.lease_epoch,
        nonce_digest: Digest32::from_array(body.nonce_digest),
    })
}

pub fn encode_response_v2(
    response: &RemoteFederatedResponseV2,
) -> Result<Vec<u8>, FederationProductErrorV1> {
    validate_response_shape(response)?;
    let items = response
        .items
        .iter()
        .map(|item| EvidenceBodyV1 {
            source_owner_id: item.source_owner_id.as_str().to_string(),
            record_id: item.record_id.as_str().to_string(),
            record_revision: item.record_revision.get(),
            record_digest: item.record_digest.into_array(),
            support_digest: item.support_digest.into_array(),
            validity_digest: item.validity_digest.into_array(),
        })
        .collect();
    encode_body(&ResponseBodyV1 {
        schema: RESPONSE_BODY_SCHEMA.to_string(),
        version: BODY_VERSION,
        peer_id: response.peer_id.as_str().to_string(),
        query_binding_digest: response.query_binding_digest.into_array(),
        scope_digest: response.scope_digest.into_array(),
        purpose_digest: response.purpose_digest.into_array(),
        generation_vector_digest: response.generation_vector_digest.into_array(),
        response_digest: response.response_digest.into_array(),
        observed_frontier: response.observed_frontier,
        expires_unix_ms: response.expires_unix_ms,
        items,
        completeness: completeness_code(response.completeness),
        terminal_observed: response.terminal_observed,
    })
}

pub fn decode_response_v2(
    payload: &[u8],
) -> Result<RemoteFederatedResponseV2, FederationProductErrorV1> {
    let body: ResponseBodyV1 = decode_body(payload)?;
    if body.schema != RESPONSE_BODY_SCHEMA || body.version != BODY_VERSION {
        return Err(FederationProductErrorV1::BodySchemaMismatch);
    }
    if body.items.len() > MAX_FEDERATED_RESULTS_V2 {
        return Err(FederationProductErrorV1::BodyOversize);
    }
    let mut items = Vec::with_capacity(body.items.len());
    for item in body.items {
        items.push(FederatedEvidenceItemV2 {
            source_owner_id: decode_id(item.source_owner_id)?,
            record_id: decode_id(item.record_id)?,
            record_revision: Revision::new(item.record_revision)
                .map_err(|_| FederationProductErrorV1::InvalidRevision)?,
            record_digest: Digest32::from_array(item.record_digest),
            support_digest: Digest32::from_array(item.support_digest),
            validity_digest: Digest32::from_array(item.validity_digest),
        });
    }
    let response = RemoteFederatedResponseV2 {
        peer_id: decode_id(body.peer_id)?,
        query_binding_digest: Digest32::from_array(body.query_binding_digest),
        scope_digest: Digest32::from_array(body.scope_digest),
        purpose_digest: Digest32::from_array(body.purpose_digest),
        generation_vector_digest: Digest32::from_array(body.generation_vector_digest),
        response_digest: Digest32::from_array(body.response_digest),
        observed_frontier: body.observed_frontier,
        expires_unix_ms: body.expires_unix_ms,
        items,
        completeness: decode_completeness(body.completeness)?,
        terminal_observed: body.terminal_observed,
    };
    validate_response_shape(&response)?;
    Ok(response)
}

pub(super) fn validate_response_for_query(
    response: &RemoteFederatedResponseV2,
    query: &FederatedQueryV2,
) -> Result<(), FederationProductErrorV1> {
    validate_response_shape(response)?;
    if response.peer_id != query.peer_id
        || response.query_binding_digest != query.binding_digest()
        || response.scope_digest != query.scope_digest
        || response.purpose_digest != query.purpose_digest
        || response.generation_vector_digest != query.generation_vector_digest
    {
        return Err(FederationProductErrorV1::ResponseBindingMismatch);
    }
    Ok(())
}

pub(super) fn validate_response_shape(
    response: &RemoteFederatedResponseV2,
) -> Result<(), FederationProductErrorV1> {
    let sealed = response.clone().seal()?;
    if sealed.response_digest != response.response_digest {
        return Err(FederationProductErrorV1::ResponseDigestMismatch);
    }
    Ok(())
}

fn encode_body<T: Serialize>(value: &T) -> Result<Vec<u8>, FederationProductErrorV1> {
    let bytes = serde_json::to_vec(value).map_err(|_| FederationProductErrorV1::BodyCodec)?;
    require_body_bound(&bytes)?;
    Ok(bytes)
}

fn decode_body<T>(payload: &[u8]) -> Result<T, FederationProductErrorV1>
where
    T: for<'de> Deserialize<'de>,
{
    require_body_bound(payload)?;
    serde_json::from_slice(payload).map_err(|_| FederationProductErrorV1::BodyCodec)
}

fn decode_id(value: String) -> Result<StableId, FederationProductErrorV1> {
    StableId::new(value).map_err(|_| FederationProductErrorV1::InvalidIdentity)
}

fn completeness_code(value: FederatedCompletenessV2) -> u8 {
    match value {
        FederatedCompletenessV2::Complete => 0,
        FederatedCompletenessV2::Partial => 1,
        FederatedCompletenessV2::Empty => 2,
        FederatedCompletenessV2::Indeterminate => 3,
    }
}

fn decode_completeness(value: u8) -> Result<FederatedCompletenessV2, FederationProductErrorV1> {
    match value {
        0 => Ok(FederatedCompletenessV2::Complete),
        1 => Ok(FederatedCompletenessV2::Partial),
        2 => Ok(FederatedCompletenessV2::Empty),
        3 => Ok(FederatedCompletenessV2::Indeterminate),
        _ => Err(FederationProductErrorV1::InvalidCompleteness),
    }
}
