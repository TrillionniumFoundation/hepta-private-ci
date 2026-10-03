//! Exact original signed-head bytes. Decoding authenticates no history, current
//! frontier, writer lease or eligibility; those remain original Owner duties.
use super::*;
pub fn encode_untrusted_signed_artifact_head_v1(head: &SignedCurrentArtifactHeadV1) -> Vec<u8> {
    encode_signed_head(head)
}
pub fn decode_untrusted_signed_artifact_head_v1(
    bytes: &[u8],
) -> Result<SignedCurrentArtifactHeadV1, ArtifactOwnerHostError> {
    if bytes.len() > MAX_SMALL_RECORD_BYTES {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    let head = decode_signed_head(bytes)?;
    if encode_signed_head(&head) != bytes {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    Ok(head)
}
