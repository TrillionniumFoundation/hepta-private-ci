//! A bounded installation acknowledgement. It carries Root's independently
//! derived frozen scope, never a peer-authored profile or an iteration result.

use super::*;

pub(crate) const POST_A_PURPOSE: &str = "runtime.learning.post-a-frozen-learning.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PostAFrozenLearningResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) data_cut: String,
    pub(crate) frozen_scope: String,
}

pub(crate) fn require_post_a_learning_reply(
    bytes: &[u8],
    request_id: u64,
    profile: &str,
) -> io::Result<PostAFrozenLearningResponseV1> {
    if bytes.is_empty() || bytes.len() > WIRE_BOUND || !(1..=MAX_READS).contains(&request_id) {
        return Err(io::Error::other("post-A reply exceeds original bounds"));
    }
    let response: PostAFrozenLearningResponseV1 =
        serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if response.schema != 1
        || response.purpose != POST_A_PURPOSE
        || response.request_id != request_id
        || response.profile != profile
    {
        return Err(io::Error::other(
            "post-A acknowledgement differs from request",
        ));
    }
    canonical_digest(profile)?;
    canonical_digest(&response.data_cut)?;
    canonical_digest(&response.frozen_scope)?;
    Ok(response)
}

#[cfg(test)]
#[path = "root_post_a_learning_protocol_tests.rs"]
mod tests;
