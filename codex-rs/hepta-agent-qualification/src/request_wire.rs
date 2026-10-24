//! Freeze the ordinary body's exact digest and explicit absent header states.
//!
//! No routing hint or Lite header is added. These expected absences are checked
//! by the original API after auth and before physical transport invocation.

use anyhow::Result;
use anyhow::anyhow;
use codex_api::RequestDispatchMetadata;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

const ROUTING_HINT: &str = "x-codex-routing-hint";
const RESPONSES_LITE: &str = "x-openai-internal-codex-responses-lite";

pub(crate) struct PreparedOrdinaryWire {
    body_digest: Digest32,
    semantic_digest: Digest32,
    dispatch: RequestDispatchMetadata,
}

impl PreparedOrdinaryWire {
    pub(super) fn new(body_digest: Digest32, settings_digest: Digest32) -> Result<Self> {
        if body_digest.is_zero() || settings_digest.is_zero() {
            return Err(anyhow!(
                "qualification wire binding requires original nonzero identities"
            ));
        }
        let semantic_digest = Digest32::of_bytes(
            &serde_json::to_vec(&semantic_record(body_digest, settings_digest))
                .map_err(|_| anyhow!("qualification wire semantic encoding failed"))?,
        );
        // All parsing and construction precede original admission. The lease
        // is then transferred immediately into the existing AttemptOwner.
        let dispatch = RequestDispatchMetadata::new_with_expected_headers(vec![
            (
                ROUTING_HINT
                    .parse()
                    .map_err(|_| anyhow!("qualification routing header identity"))?,
                None,
            ),
            (
                RESPONSES_LITE
                    .parse()
                    .map_err(|_| anyhow!("qualification Lite header identity"))?,
                None,
            ),
        ]);
        Ok(Self {
            body_digest,
            semantic_digest,
            dispatch,
        })
    }

    pub(crate) fn body_digest(&self) -> Digest32 {
        self.body_digest
    }
    pub(crate) fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }
    pub(super) fn dispatch_metadata(&self) -> RequestDispatchMetadata {
        self.dispatch.clone()
    }
}

fn semantic_record(body_digest: Digest32, settings_digest: Digest32) -> Value {
    json!({
        "schema":"hepta-native-qualification-ordinary-wire:v2",
        "api_body_sha256":body_digest.to_string(),
        "request_settings_evidence_sha256":settings_digest.to_string(),
        "routing_hint":null,
        "responses_lite":false,
        "expected_absent_headers":[ROUTING_HINT, RESPONSES_LITE],
    })
}

#[cfg(test)]
#[path = "request_wire_tests.rs"]
mod tests;
