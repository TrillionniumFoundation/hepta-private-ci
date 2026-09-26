use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContextCompilerV2Error;
use crate::ContextModelProfileV2;
use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;
use crate::ContextSerializerV2;
use crate::ExactTokenizerV2;
use crate::MAX_CONTEXT_CANDIDATES_V2;

const TOKENIZER_IDENTITY_DOMAIN: &[u8] = b"hepta.context-qualified-tokenizer.v2";
const SERIALIZER_IDENTITY_DOMAIN: &[u8] = b"hepta.context-canonical-serializer.v2";
const CANONICAL_PAYLOAD_DOMAIN: &[u8] = b"hepta.context-canonical-payload.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizerIdentityV2 {
    pub model_digest: Digest32,
    pub provider_id_digest: Digest32,
    pub provider_model_digest: Digest32,
    pub implementation_digest: Digest32,
    pub version_digest: Digest32,
    pub vocabulary_digest: Digest32,
    pub normalization_policy_digest: Digest32,
}

impl TokenizerIdentityV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for digest in [
            self.model_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.implementation_digest,
            self.version_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            if digest.is_zero() {
                return Err(ContextCompilerV2Error::TokenizerProfileMismatch);
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = TOKENIZER_IDENTITY_DOMAIN.to_vec();
        for digest in [
            self.model_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.implementation_digest,
            self.version_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Host capability that must invoke the real tokenizer identified by
/// [`TokenizerIdentityV2`] over the exact bytes supplied to it.
///
/// No registry token-cost lookup or estimate implements this contract.
pub trait ExactTokenCounterV2: Send + Sync {
    fn count_exact_tokens(
        &self,
        identity: &TokenizerIdentityV2,
        bytes: &[u8],
    ) -> Result<u64, ContextCompilerV2Error>;
}

pub struct QualifiedExactTokenizerV2<T> {
    identity: TokenizerIdentityV2,
    counter: T,
}

impl<T> QualifiedExactTokenizerV2<T> {
    pub fn new(
        identity: TokenizerIdentityV2,
        counter: T,
    ) -> Result<Self, ContextCompilerV2Error> {
        identity.validate()?;
        Ok(Self { identity, counter })
    }

    #[must_use]
    pub const fn identity(&self) -> &TokenizerIdentityV2 {
        &self.identity
    }
}

impl<T: ExactTokenCounterV2> ExactTokenizerV2 for QualifiedExactTokenizerV2<T> {
    fn tokenizer_digest(&self) -> Digest32 {
        self.identity.digest()
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.counter.count_exact_tokens(&self.identity, bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalSerializerIdentityV2 {
    pub model_digest: Digest32,
    pub provider_id_digest: Digest32,
    pub provider_model_digest: Digest32,
    pub implementation_digest: Digest32,
    pub version_digest: Digest32,
    pub framing_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
}

impl CanonicalSerializerIdentityV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for digest in [
            self.model_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.implementation_digest,
            self.version_digest,
            self.framing_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            if digest.is_zero() {
                return Err(ContextCompilerV2Error::SerializerProfileMismatch);
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = SERIALIZER_IDENTITY_DOMAIN.to_vec();
        for digest in [
            self.model_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.implementation_digest,
            self.version_digest,
            self.framing_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalContextSegmentKindV2 {
    Header,
    ItemMetadata,
    ItemContent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSegmentV2 {
    pub kind: CanonicalContextSegmentKindV2,
    pub item_id: Option<StableId>,
    pub start_offset: u64,
    pub end_offset: u64,
    pub segment_digest: Digest32,
}

#[derive(Clone, Eq, PartialEq)]
pub struct CanonicalSerializedPayloadV2 {
    bytes: Vec<u8>,
    segments: Vec<CanonicalContextSegmentV2>,
    payload_digest: Digest32,
}

impl fmt::Debug for CanonicalSerializedPayloadV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CanonicalSerializedPayloadV2")
            .field("payload_bytes", &self.bytes.len())
            .field("segment_count", &self.segments.len())
            .field("payload_digest", &self.payload_digest)
            .finish()
    }
}

impl CanonicalSerializedPayloadV2 {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn segments(&self) -> &[CanonicalContextSegmentV2] {
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
pub struct CanonicalContextSerializerV2 {
    identity: CanonicalSerializerIdentityV2,
}

impl CanonicalContextSerializerV2 {
    pub fn new(
        identity: CanonicalSerializerIdentityV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        identity.validate()?;
        Ok(Self { identity })
    }

    #[must_use]
    pub const fn identity(&self) -> &CanonicalSerializerIdentityV2 {
        &self.identity
    }

    pub fn serialize_with_segments(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<CanonicalSerializedPayloadV2, ContextCompilerV2Error> {
        if items.len() > MAX_CONTEXT_CANDIDATES_V2 {
            return Err(ContextCompilerV2Error::CandidateLimitExceeded);
        }
        let mut seen = BTreeSet::new();
        for item in items {
            if !seen.insert(item.item_id.clone()) {
                return Err(ContextCompilerV2Error::DuplicateRealization(
                    item.item_id.to_string(),
                ));
            }
        }

        let mut bytes = CANONICAL_PAYLOAD_DOMAIN.to_vec();
        bytes.extend_from_slice(&2_u32.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(items.len())
                .map_err(|_| ContextCompilerV2Error::Arithmetic)?
                .to_be_bytes(),
        );
        let header_end = bytes.len();
        let mut segments = vec![segment(
            CanonicalContextSegmentKindV2::Header,
            None,
            0,
            header_end,
            &bytes,
        )?];

        for item in items {
            let metadata_start = bytes.len();
            bytes.push(role_code(item.role));
            push_id(&mut bytes, &item.item_id)?;
            bytes.extend_from_slice(
                &u64::try_from(item.content.len())
                    .map_err(|_| ContextCompilerV2Error::Arithmetic)?
                    .to_be_bytes(),
            );
            let metadata_end = bytes.len();
            segments.push(segment(
                CanonicalContextSegmentKindV2::ItemMetadata,
                Some(item.item_id.clone()),
                metadata_start,
                metadata_end,
                &bytes,
            )?);

            let content_start = bytes.len();
            bytes.extend_from_slice(&item.content);
            let content_end = bytes.len();
            segments.push(segment(
                CanonicalContextSegmentKindV2::ItemContent,
                Some(item.item_id.clone()),
                content_start,
                content_end,
                &bytes,
            )?);
        }

        Ok(CanonicalSerializedPayloadV2 {
            payload_digest: Digest32::of_bytes(&bytes),
            bytes,
            segments,
        })
    }
}

impl ContextSerializerV2 for CanonicalContextSerializerV2 {
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
            .map(CanonicalSerializedPayloadV2::into_bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedContextProfileV2 {
    profile: ContextModelProfileV2,
    tokenizer_identity: TokenizerIdentityV2,
    serializer_identity: CanonicalSerializerIdentityV2,
}

impl QualifiedContextProfileV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        model_digest: Digest32,
        provider_id_digest: Digest32,
        provider_model_digest: Digest32,
        maximum_context_tokens: u64,
        tokenizer_identity: TokenizerIdentityV2,
        serializer_identity: CanonicalSerializerIdentityV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        tokenizer_identity.validate()?;
        serializer_identity.validate()?;
        if tokenizer_identity.model_digest != model_digest
            || tokenizer_identity.provider_id_digest != provider_id_digest
            || tokenizer_identity.provider_model_digest != provider_model_digest
            || serializer_identity.model_digest != model_digest
            || serializer_identity.provider_id_digest != provider_id_digest
            || serializer_identity.provider_model_digest != provider_model_digest
        {
            return Err(ContextCompilerV2Error::ModelProfileMismatch);
        }
        let profile = ContextModelProfileV2 {
            model_digest,
            provider_id_digest,
            provider_model_digest,
            tokenizer_digest: tokenizer_identity.digest(),
            serializer_digest: serializer_identity.digest(),
            template_digest: serializer_identity.template_digest,
            tool_schema_digest: serializer_identity.tool_schema_digest,
            maximum_context_tokens,
        };
        profile.validate()?;
        Ok(Self {
            profile,
            tokenizer_identity,
            serializer_identity,
        })
    }

    #[must_use]
    pub const fn profile(&self) -> &ContextModelProfileV2 {
        &self.profile
    }

    #[must_use]
    pub const fn tokenizer_identity(&self) -> &TokenizerIdentityV2 {
        &self.tokenizer_identity
    }

    #[must_use]
    pub const fn serializer_identity(&self) -> &CanonicalSerializerIdentityV2 {
        &self.serializer_identity
    }
}

fn segment(
    kind: CanonicalContextSegmentKindV2,
    item_id: Option<StableId>,
    start: usize,
    end: usize,
    bytes: &[u8],
) -> Result<CanonicalContextSegmentV2, ContextCompilerV2Error> {
    let slice = bytes
        .get(start..end)
        .ok_or(ContextCompilerV2Error::Arithmetic)?;
    Ok(CanonicalContextSegmentV2 {
        kind,
        item_id,
        start_offset: u64::try_from(start).map_err(|_| ContextCompilerV2Error::Arithmetic)?,
        end_offset: u64::try_from(end).map_err(|_| ContextCompilerV2Error::Arithmetic)?,
        segment_digest: Digest32::of_bytes(slice),
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ContextCompilerV2Error> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| ContextCompilerV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use crate::ContextRealizedItemV2;
    use crate::ContextRoleV2;
    use crate::ContextSerializerV2;
    use crate::ExactTokenizerV2;

    use super::CanonicalContextSerializerV2;
    use super::CanonicalSerializerIdentityV2;
    use super::ExactTokenCounterV2;
    use super::QualifiedContextProfileV2;
    use super::QualifiedExactTokenizerV2;
    use super::TokenizerIdentityV2;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|error| panic!("valid id: {error:?}"))
    }

    fn tokenizer_identity() -> TokenizerIdentityV2 {
        TokenizerIdentityV2 {
            model_digest: digest("model"),
            provider_id_digest: digest("provider"),
            provider_model_digest: digest("provider-model"),
            implementation_digest: digest("tokenizer-binary"),
            version_digest: digest("tokenizer-version"),
            vocabulary_digest: digest("vocabulary"),
            normalization_policy_digest: digest("normalization"),
        }
    }

    fn serializer_identity() -> CanonicalSerializerIdentityV2 {
        CanonicalSerializerIdentityV2 {
            model_digest: digest("model"),
            provider_id_digest: digest("provider"),
            provider_model_digest: digest("provider-model"),
            implementation_digest: digest("serializer-binary"),
            version_digest: digest("serializer-version"),
            framing_digest: digest("framing-v2"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        }
    }

    #[derive(Clone, Copy)]
    struct ByteCounter;

    impl ExactTokenCounterV2 for ByteCounter {
        fn count_exact_tokens(
            &self,
            _identity: &TokenizerIdentityV2,
            bytes: &[u8],
        ) -> Result<u64, crate::ContextCompilerV2Error> {
            u64::try_from(bytes.len()).map_err(|_| crate::ContextCompilerV2Error::Arithmetic)
        }
    }

    #[test]
    fn qualified_profile_binds_all_codec_revision_inputs() {
        let tokenizer = tokenizer_identity();
        let serializer = serializer_identity();
        let profile = QualifiedContextProfileV2::new(
            digest("model"),
            digest("provider"),
            digest("provider-model"),
            4096,
            tokenizer.clone(),
            serializer.clone(),
        )
        .unwrap_or_else(|error| panic!("profile: {error:?}"));
        assert_eq!(profile.profile().tokenizer_digest, tokenizer.digest());
        assert_eq!(profile.profile().serializer_digest, serializer.digest());
    }

    #[test]
    fn canonical_serializer_has_no_caller_supplied_payload() {
        let serializer = CanonicalContextSerializerV2::new(serializer_identity())
            .unwrap_or_else(|error| panic!("serializer: {error:?}"));
        let items = vec![
            ContextRealizedItemV2 {
                item_id: id("one"),
                role: ContextRoleV2::TrustedInstruction,
                content: b"alpha".to_vec(),
            },
            ContextRealizedItemV2 {
                item_id: id("two"),
                role: ContextRoleV2::UntrustedEvidence,
                content: b"beta".to_vec(),
            },
        ];
        let first = serializer
            .serialize_with_segments(&items)
            .unwrap_or_else(|error| panic!("serialize: {error:?}"));
        let second = ContextSerializerV2::serialize(&serializer, &items)
            .unwrap_or_else(|error| panic!("serialize: {error:?}"));
        assert_eq!(first.bytes(), second);
        assert_eq!(first.payload_digest(), Digest32::of_bytes(&second));
        assert_eq!(first.segments().len(), 5);
        assert!(!format!("{first:?}").contains("alpha"));
    }

    #[test]
    fn exact_tokenizer_invokes_counter_on_supplied_bytes() {
        let tokenizer = QualifiedExactTokenizerV2::new(tokenizer_identity(), ByteCounter)
            .unwrap_or_else(|error| panic!("tokenizer: {error:?}"));
        assert_eq!(
            ExactTokenizerV2::count_tokens(&tokenizer, b"exact-final-bytes")
                .unwrap_or_else(|error| panic!("count: {error:?}")),
            17
        );
    }
}
