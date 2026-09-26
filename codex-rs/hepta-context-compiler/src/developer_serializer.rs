use std::collections::BTreeSet;
use std::fmt;

use serde::Serialize;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CanonicalSerializerIdentityV2;
use crate::ContextCompilerV2Error;
use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;
use crate::ContextSerializerV2;
use crate::MAX_CONTEXT_CANDIDATES_V2;
use crate::MAX_SERIALIZED_PAYLOAD_BYTES_V2;

const FRAME_OPEN: &[u8] = b"<hepta_context schema=\"2\" role=\"developer_policy\">\n";
const FRAME_CLOSE: &[u8] = b"</hepta_context>";
const FRAMING_DOMAIN: &[u8] = b"hepta.context.developer-policy-framing.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeveloperPolicySegmentKindV2 {
    Header,
    Item,
    Footer,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeveloperPolicySegmentV2 {
    pub kind: DeveloperPolicySegmentKindV2,
    pub item_id: Option<StableId>,
    pub start_offset: u64,
    pub end_offset: u64,
    pub segment_digest: Digest32,
}

#[derive(Clone, Eq, PartialEq)]
pub struct DeveloperPolicyPayloadV2 {
    bytes: Vec<u8>,
    segments: Vec<DeveloperPolicySegmentV2>,
    payload_digest: Digest32,
}

impl fmt::Debug for DeveloperPolicyPayloadV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DeveloperPolicyPayloadV2")
            .field("payload_bytes", &self.bytes.len())
            .field("segment_count", &self.segments.len())
            .field("payload_digest", &self.payload_digest)
            .finish()
    }
}

impl DeveloperPolicyPayloadV2 {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn segments(&self) -> &[DeveloperPolicySegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn into_bytes(self) -> Vec<u8> {
        self.bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalDeveloperPolicySerializerV2 {
    identity: CanonicalSerializerIdentityV2,
}

impl CanonicalDeveloperPolicySerializerV2 {
    pub fn new(
        identity: CanonicalSerializerIdentityV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        identity.validate()?;
        if identity.framing_digest != developer_policy_framing_digest_v2() {
            return Err(ContextCompilerV2Error::SerializerProfileMismatch);
        }
        Ok(Self { identity })
    }

    #[must_use]
    pub const fn identity(&self) -> &CanonicalSerializerIdentityV2 {
        &self.identity
    }

    pub fn serialize_with_segments(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<DeveloperPolicyPayloadV2, ContextCompilerV2Error> {
        if items.is_empty() {
            return Err(ContextCompilerV2Error::EmptySerializedPayload);
        }
        if items.len() > MAX_CONTEXT_CANDIDATES_V2 {
            return Err(ContextCompilerV2Error::CandidateLimitExceeded);
        }

        let mut seen = BTreeSet::new();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FRAME_OPEN);
        let mut segments = vec![segment(
            DeveloperPolicySegmentKindV2::Header,
            None,
            0,
            bytes.len(),
            &bytes,
        )?];

        for item in items {
            if item.role != ContextRoleV2::TrustedInstruction {
                return Err(ContextCompilerV2Error::RealizedRoleMismatch(
                    item.item_id.to_string(),
                ));
            }
            if !seen.insert(item.item_id.clone()) {
                return Err(ContextCompilerV2Error::DuplicateRealization(
                    item.item_id.to_string(),
                ));
            }
            let content = std::str::from_utf8(&item.content).map_err(|_| {
                ContextCompilerV2Error::RealizedContentMismatch(item.item_id.to_string())
            })?;
            let start = bytes.len();
            let line = DeveloperPolicyItemWireV2 {
                schema: 2,
                item_id: item.item_id.as_str(),
                role: "trusted_instruction",
                content_sha256: Digest32::of_bytes(&item.content).to_string(),
                content,
            };
            serde_json::to_writer(&mut bytes, &line)
                .map_err(|_| ContextCompilerV2Error::SerializationMismatch)?;
            bytes.push(b'\n');
            segments.push(segment(
                DeveloperPolicySegmentKindV2::Item,
                Some(item.item_id.clone()),
                start,
                bytes.len(),
                &bytes,
            )?);
            if bytes.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2 {
                return Err(ContextCompilerV2Error::SerializedPayloadTooLarge);
            }
        }

        let footer_start = bytes.len();
        bytes.extend_from_slice(FRAME_CLOSE);
        segments.push(segment(
            DeveloperPolicySegmentKindV2::Footer,
            None,
            footer_start,
            bytes.len(),
            &bytes,
        )?);
        if bytes.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2 {
            return Err(ContextCompilerV2Error::SerializedPayloadTooLarge);
        }

        Ok(DeveloperPolicyPayloadV2 {
            payload_digest: Digest32::of_bytes(&bytes),
            bytes,
            segments,
        })
    }
}

impl ContextSerializerV2 for CanonicalDeveloperPolicySerializerV2 {
    fn serializer_digest(&self) -> Digest32 {
        self.identity.digest()
    }

    fn template_digest(&self) -> Digest32 {
        self.identity.template_digest
    }

    fn tool_schema_digest(&self) -> Digest32 {
        self.identity.tool_schema_digest
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        self.serialize_with_segments(items)
            .map(DeveloperPolicyPayloadV2::into_bytes)
    }
}

#[must_use]
pub fn developer_policy_framing_digest_v2() -> Digest32 {
    let mut bytes = FRAMING_DOMAIN.to_vec();
    bytes.extend_from_slice(FRAME_OPEN);
    bytes.extend_from_slice(FRAME_CLOSE);
    Digest32::of_bytes(&bytes)
}

#[derive(Serialize)]
struct DeveloperPolicyItemWireV2<'a> {
    schema: u32,
    item_id: &'a str,
    role: &'static str,
    content_sha256: String,
    content: &'a str,
}

fn segment(
    kind: DeveloperPolicySegmentKindV2,
    item_id: Option<StableId>,
    start: usize,
    end: usize,
    bytes: &[u8],
) -> Result<DeveloperPolicySegmentV2, ContextCompilerV2Error> {
    let raw = bytes
        .get(start..end)
        .ok_or(ContextCompilerV2Error::Arithmetic)?;
    Ok(DeveloperPolicySegmentV2 {
        kind,
        item_id,
        start_offset: u64::try_from(start).map_err(|_| ContextCompilerV2Error::Arithmetic)?,
        end_offset: u64::try_from(end).map_err(|_| ContextCompilerV2Error::Arithmetic)?,
        segment_digest: Digest32::of_bytes(raw),
    })
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use crate::CanonicalSerializerIdentityV2;
    use crate::ContextRealizedItemV2;
    use crate::ContextRoleV2;
    use crate::ContextSerializerV2;

    use super::CanonicalDeveloperPolicySerializerV2;
    use super::developer_policy_framing_digest_v2;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|error| panic!("valid id: {error:?}"))
    }

    fn serializer() -> CanonicalDeveloperPolicySerializerV2 {
        CanonicalDeveloperPolicySerializerV2::new(CanonicalSerializerIdentityV2 {
            model_digest: digest("model"),
            provider_id_digest: digest("provider"),
            provider_model_digest: digest("provider-model"),
            implementation_digest: digest("developer-serializer-binary"),
            version_digest: digest("developer-serializer-v2"),
            framing_digest: developer_policy_framing_digest_v2(),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        })
        .unwrap_or_else(|error| panic!("serializer: {error:?}"))
    }

    #[test]
    fn exact_utf8_payload_is_deterministic_and_segment_complete() {
        let items = vec![
            ContextRealizedItemV2 {
                item_id: id("developer-one"),
                role: ContextRoleV2::TrustedInstruction,
                content: b"Never reveal secrets.".to_vec(),
            },
            ContextRealizedItemV2 {
                item_id: id("developer-two"),
                role: ContextRoleV2::TrustedInstruction,
                content: "Use exact bytes: <tag> & \"quote\"".as_bytes().to_vec(),
            },
        ];
        let serializer = serializer();
        let first = serializer
            .serialize_with_segments(&items)
            .unwrap_or_else(|error| panic!("serialize: {error:?}"));
        let second = ContextSerializerV2::serialize(&serializer, &items)
            .unwrap_or_else(|error| panic!("serialize: {error:?}"));
        assert_eq!(first.bytes(), second);
        assert_eq!(first.payload_digest(), Digest32::of_bytes(&second));
        assert_eq!(first.segments().len(), 4);
        assert!(std::str::from_utf8(&second).is_ok());
        assert!(!format!("{first:?}").contains("Never reveal secrets"));
    }

    #[test]
    fn non_instruction_role_is_rejected() {
        let error = serializer()
            .serialize(&[ContextRealizedItemV2 {
                item_id: id("evidence"),
                role: ContextRoleV2::UntrustedEvidence,
                content: b"untrusted".to_vec(),
            }])
            .err()
            .unwrap_or_else(|| panic!("role confusion must fail"));
        assert!(matches!(
            error,
            crate::ContextCompilerV2Error::RealizedRoleMismatch(_)
        ));
    }
}
