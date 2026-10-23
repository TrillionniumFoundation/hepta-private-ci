//! Local text data contracts only: no dispatch, tokenizer, authority or I10 proof.
//! Text is exact UTF-8, with no normalization, templating or silent truncation.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::error::Error as StdError;
use std::fmt;

const MAX_INPUT_BYTES: usize = 32 * 1024;
const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;

/// Actual input bytes remain available to the runtime; a digest is not input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalTextInputV1(String);

impl LocalTextInputV1 {
    pub fn from_utf8(bytes: &[u8]) -> Result<Self, LocalTextContractError> {
        if bytes.is_empty() || bytes.len() > MAX_INPUT_BYTES {
            return Err(LocalTextContractError::InputLimit);
        }
        let text = std::str::from_utf8(bytes).map_err(|_| LocalTextContractError::InvalidUtf8)?;
        Ok(Self(text.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Selected release references, not evidence that any dependency was loaded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalTextReleaseBindingV1 {
    pub release_root: Digest32,
    pub dependency_closure_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub chat_template_digest: Digest32,
}

/// The runtime must resolve the exact decoding profile and count tokens with
/// the selected tokenizer after preprocessing/template application, before use.
/// These are per-request bounds; 128/8 are pilot settings, not product limits.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalTextGenerationPolicyV1 {
    pub decoding_profile_digest: Digest32,
    pub maximum_input_tokens: u32,
    pub maximum_output_tokens: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalTextRequestV1 {
    pub request_id: StableId,
    pub operation_id: StableId,
    pub owner_generation: Generation,
    pub release: LocalTextReleaseBindingV1,
    pub input: LocalTextInputV1,
    pub generation: LocalTextGenerationPolicyV1,
}

/// Untrusted reported readback. Public fields and shape checks confer no
/// capability, authentication, installation receipt or verified tensor use.
/// A future runtime must actually read tensor/adapter bytes under this attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoadedRootReadbackV1 {
    pub load_operation_id: StableId,
    pub attempt_id: StableId,
    pub owner_generation: Generation,
    pub release: LocalTextReleaseBindingV1,
    pub parent_release_root: Option<Digest32>,
    pub tensor_inventory_digest: Digest32,
    pub adapter_digest: Option<Digest32>,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
}

/// Reported execution state is independent of process/model release.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalTextObservedStatusV1 {
    Completed,
    Failed,
    Indeterminate,
}

/// Untrusted data, including token counts. Partial output can accompany an
/// indeterminate execution; it never establishes terminality or permits replay.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalTextObservationV1 {
    pub request_digest: Digest32,
    pub readback: LoadedRootReadbackV1,
    pub status: LocalTextObservedStatusV1,
    pub output_utf8: Vec<u8>,
    pub observed_input_tokens: Option<u32>,
    pub observed_output_tokens: Option<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalTextContractError {
    InputLimit,
    OutputLimit,
    InvalidUtf8,
    EmptyDigest,
    TokenLimit,
    BindingMismatch,
    MissingReportedUsage,
}

impl fmt::Display for LocalTextContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LocalTextContractError {}

/// Validate structure and hash every semantic field, including the real input.
/// This performs no tokenization, model execution or authority admission.
pub fn local_text_request_digest_v1(
    request: &LocalTextRequestV1,
) -> Result<Digest32, LocalTextContractError> {
    validate_release(&request.release)?;
    nonzero(request.generation.decoding_profile_digest)?;
    for count in [
        request.generation.maximum_input_tokens,
        request.generation.maximum_output_tokens,
    ] {
        if count == 0 || count > MAX_TOKENS {
            return Err(LocalTextContractError::TokenLimit);
        }
    }
    let mut bytes = b"hepta.inference.local-text-request.v1\0".to_vec();
    for value in [request.request_id.as_str(), request.operation_id.as_str()] {
        push_bytes(&mut bytes, value.as_bytes());
    }
    bytes.extend_from_slice(&request.owner_generation.get().to_be_bytes());
    for digest in release_digests(&request.release) {
        bytes.extend_from_slice(digest.as_array());
    }
    push_bytes(&mut bytes, request.input.as_str().as_bytes());
    bytes.extend_from_slice(request.generation.decoding_profile_digest.as_array());
    bytes.extend_from_slice(&request.generation.maximum_input_tokens.to_be_bytes());
    bytes.extend_from_slice(&request.generation.maximum_output_tokens.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

/// Checks untrusted data shape/binding only. Even `Ok(())` is not authenticated
/// readback, a tokenizer observation, execution proof, release or I10 admission.
pub fn validate_local_text_observation_shape_v1(
    request: &LocalTextRequestV1,
    observation: &LocalTextObservationV1,
) -> Result<(), LocalTextContractError> {
    if observation.request_digest != local_text_request_digest_v1(request)?
        || observation.readback.release != request.release
        || observation.readback.owner_generation != request.owner_generation
    {
        return Err(LocalTextContractError::BindingMismatch);
    }
    for digest in [
        Some(observation.readback.tensor_inventory_digest),
        observation.readback.adapter_digest,
        observation.readback.parent_release_root,
        Some(observation.readback.runtime_digest),
        Some(observation.readback.device_digest),
    ]
    .into_iter()
    .flatten()
    {
        nonzero(digest)?;
    }
    if observation.output_utf8.len() > MAX_OUTPUT_BYTES {
        return Err(LocalTextContractError::OutputLimit);
    }
    std::str::from_utf8(&observation.output_utf8)
        .map_err(|_| LocalTextContractError::InvalidUtf8)?;
    if observation
        .observed_input_tokens
        .is_some_and(|count| count > request.generation.maximum_input_tokens)
        || observation
            .observed_output_tokens
            .is_some_and(|count| count > request.generation.maximum_output_tokens)
    {
        return Err(LocalTextContractError::TokenLimit);
    }
    if observation.status == LocalTextObservedStatusV1::Completed
        && (observation.observed_input_tokens.is_none()
            || observation.observed_output_tokens.is_none())
    {
        return Err(LocalTextContractError::MissingReportedUsage);
    }
    if observation.status == LocalTextObservedStatusV1::Completed
        && observation.observed_input_tokens == Some(0)
    {
        return Err(LocalTextContractError::TokenLimit);
    }
    Ok(())
}

/// Identity of an untrusted report, including partial output and missing usage.
/// A digest authenticates neither the reporter nor any claimed loaded bytes.
pub fn local_text_observation_digest_v1(
    request: &LocalTextRequestV1,
    observation: &LocalTextObservationV1,
) -> Result<Digest32, LocalTextContractError> {
    validate_local_text_observation_shape_v1(request, observation)?;
    let mut bytes = b"hepta.inference.local-text-observation.v1\0".to_vec();
    bytes.extend_from_slice(observation.request_digest.as_array());
    let readback = &observation.readback;
    for id in [&readback.load_operation_id, &readback.attempt_id] {
        push_bytes(&mut bytes, id.as_str().as_bytes());
    }
    bytes.extend_from_slice(&readback.owner_generation.get().to_be_bytes());
    for digest in release_digests(&readback.release) {
        bytes.extend_from_slice(digest.as_array());
    }
    for digest in [readback.parent_release_root, readback.adapter_digest] {
        match digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
    }
    for digest in [
        readback.tensor_inventory_digest,
        readback.runtime_digest,
        readback.device_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match observation.status {
        LocalTextObservedStatusV1::Completed => 1,
        LocalTextObservedStatusV1::Failed => 2,
        LocalTextObservedStatusV1::Indeterminate => 3,
    });
    push_bytes(&mut bytes, &observation.output_utf8);
    for count in [
        observation.observed_input_tokens,
        observation.observed_output_tokens,
    ] {
        match count {
            Some(count) => {
                bytes.push(1);
                bytes.extend_from_slice(&count.to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn release_digests(release: &LocalTextReleaseBindingV1) -> [Digest32; 5] {
    [
        release.release_root,
        release.dependency_closure_digest,
        release.tokenizer_digest,
        release.preprocessor_digest,
        release.chat_template_digest,
    ]
}

fn validate_release(release: &LocalTextReleaseBindingV1) -> Result<(), LocalTextContractError> {
    for digest in release_digests(release) {
        nonzero(digest)?;
    }
    Ok(())
}

fn nonzero(digest: Digest32) -> Result<(), LocalTextContractError> {
    if digest.is_zero() {
        return Err(LocalTextContractError::EmptyDigest);
    }
    Ok(())
}

fn push_bytes(target: &mut Vec<u8>, bytes: &[u8]) {
    target.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    target.extend_from_slice(bytes);
}

#[cfg(test)]
#[path = "local_text_tests.rs"]
mod tests;
