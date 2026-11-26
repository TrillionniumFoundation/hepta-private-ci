//! Private bounded archive codec. This is not an authority deserializer.
//!
//! Integers are fixed-width big endian; strings and vectors have u32 lengths;
//! optional values and booleans have exactly the tags 0 and 1. Authority fields
//! are never encoded. Candidates and proofs are reconstructed by verification,
//! never deserialized. Semantic payload bytes live in their separately hashed
//! immutable blob, not in the metadata archive.

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::CompactionQualificationV2;
use crate::CompactionSemanticPayloadV2;
use crate::CompactionTrustRoleV1;
use crate::SignedCompactionEvaluationReceiptV1;
use crate::SignedRetentionSelectionReceiptV1;
use crate::SignedSemanticGenerationReceiptV1;
use crate::TokenizationReceiptV1;
use crate::TrustEnrollmentV1;

pub(crate) const MAX_ARCHIVE_BYTES: usize = 64 * 1024 * 1024;
const MAX_COLLECTION_ITEMS: usize = 65_536;
const MAX_STRING_BYTES: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct WireError(pub(crate) &'static str);

pub(crate) struct Encoder {
    bytes: Vec<u8>,
}

impl Encoder {
    pub(crate) fn new(domain: &[u8]) -> Result<Self, WireError> {
        let mut result = Self { bytes: Vec::new() };
        result.put(domain)?;
        Ok(result)
    }

    pub(crate) fn put(&mut self, bytes: &[u8]) -> Result<(), WireError> {
        if self.bytes.len().checked_add(bytes.len()).is_none_or(|n| n > MAX_ARCHIVE_BYTES) {
            return Err(WireError("archive byte limit"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }

    pub(crate) fn finish(self) -> Vec<u8> {
        self.bytes
    }
}

pub(crate) struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Decoder<'a> {
    pub(crate) fn new(bytes: &'a [u8], domain: &[u8]) -> Result<Self, WireError> {
        if bytes.len() > MAX_ARCHIVE_BYTES || !bytes.starts_with(domain) {
            return Err(WireError("archive domain or length"));
        }
        Ok(Self { bytes, offset: domain.len() })
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], WireError> {
        let end = self.offset.checked_add(length).ok_or(WireError("archive length overflow"))?;
        let result = self.bytes.get(self.offset..end).ok_or(WireError("truncated archive"))?;
        self.offset = end;
        Ok(result)
    }

    pub(crate) fn finish(self) -> Result<(), WireError> {
        if self.offset != self.bytes.len() {
            return Err(WireError("trailing archive bytes"));
        }
        Ok(())
    }
}

pub(crate) trait Wire: Sized {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError>;
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError>;
}

macro_rules! integer {
    ($kind:ty, $size:literal) => {
        impl Wire for $kind {
            fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
                output.put(&self.to_be_bytes())
            }
            fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
                let bytes: [u8; $size] = input.take($size)?.try_into().map_err(|_| WireError("integer width"))?;
                Ok(Self::from_be_bytes(bytes))
            }
        }
    };
}
integer!(u8, 1);
integer!(u32, 4);
integer!(u64, 8);

impl<const N: usize> Wire for [u8; N] {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        output.put(self)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        input.take(N)?.try_into().map_err(|_| WireError("array width"))
    }
}

impl Wire for bool {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        u8::from(*self).write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        match u8::read(input)? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(WireError("invalid boolean tag")),
        }
    }
}

impl<T: Wire> Wire for Option<T> {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        self.is_some().write(output)?;
        if let Some(value) = self { value.write(output)?; }
        Ok(())
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        if bool::read(input)? { Ok(Some(T::read(input)?)) } else { Ok(None) }
    }
}

impl<T: Wire> Wire for Vec<T> {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        if self.len() > MAX_COLLECTION_ITEMS { return Err(WireError("collection item limit")); }
        u32::try_from(self.len()).map_err(|_| WireError("collection length"))?.write(output)?;
        for item in self { item.write(output)?; }
        Ok(())
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        let length = usize::try_from(u32::read(input)?).map_err(|_| WireError("collection length"))?;
        if length > MAX_COLLECTION_ITEMS || length > input.bytes.len() - input.offset {
            return Err(WireError("collection item limit"));
        }
        // Do not reserve an attacker-provided capacity before decoding items.
        let mut values = Vec::new();
        for _ in 0..length { values.push(T::read(input)?); }
        Ok(values)
    }
}

impl Wire for StableId {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        let bytes = self.as_str().as_bytes();
        if bytes.len() > MAX_STRING_BYTES { return Err(WireError("identifier length")); }
        u32::try_from(bytes.len()).map_err(|_| WireError("identifier length"))?.write(output)?;
        output.put(bytes)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        let length = usize::try_from(u32::read(input)?).map_err(|_| WireError("identifier length"))?;
        if length > MAX_STRING_BYTES { return Err(WireError("identifier length")); }
        let text = std::str::from_utf8(input.take(length)?).map_err(|_| WireError("identifier UTF-8"))?;
        Self::new(text).map_err(|_| WireError("invalid identifier"))
    }
}

impl Wire for Digest32 {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> { self.as_array().write(output) }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> { Ok(Self::from_array(<[u8; 32]>::read(input)?)) }
}

macro_rules! counter {
    ($kind:ty) => {
        impl Wire for $kind {
            fn write(&self, output: &mut Encoder) -> Result<(), WireError> { self.get().write(output) }
            fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
                Self::new(u64::read(input)?).map_err(|_| WireError("invalid generation or revision"))
            }
        }
    };
}
counter!(Generation);
counter!(Revision);

macro_rules! wire_struct {
    ($kind:ident { $($field:ident: $ty:ty),+ $(,)? }) => {
        impl Wire for $kind {
            fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
                $(self.$field.write(output)?;)+
                Ok(())
            }
            fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
                Ok(Self { $($field: <$ty>::read(input)?,)+ })
            }
        }
    };
}
pub(crate) use wire_struct;

impl Wire for MemoryKind {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        let tag: u8 = match self { Self::Episode => 0, Self::Fact => 1, Self::Preference => 2, Self::Procedure => 3 };
        tag.write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        match u8::read(input)? { 0 => Ok(Self::Episode), 1 => Ok(Self::Fact), 2 => Ok(Self::Preference), 3 => Ok(Self::Procedure), _ => Err(WireError("memory kind")) }
    }
}

impl Wire for RecordState {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> { matches!(self, Self::Tombstone).write(output) }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> { Ok(if bool::read(input)? { Self::Tombstone } else { Self::Live }) }
}

impl Wire for CompactionTrustRoleV1 {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        let tag: u8 = match self { Self::RetentionSelector => 0, Self::SemanticGenerator => 1, Self::Tokenizer => 2, Self::Evaluator => 3 };
        tag.write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        match u8::read(input)? { 0 => Ok(Self::RetentionSelector), 1 => Ok(Self::SemanticGenerator), 2 => Ok(Self::Tokenizer), 3 => Ok(Self::Evaluator), _ => Err(WireError("trust role")) }
    }
}

wire_struct!(Citation { source_id: StableId, source_digest: Digest32 });
wire_struct!(MemoryRecord {
    record_id: StableId, revision: Revision, kind: MemoryKind, content_digest: Digest32,
    predecessor_digest: Option<Digest32>, citations: Vec<Citation>, state: RecordState
});

impl Wire for CognitiveSnapshot {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        self.validate_integrity().map_err(|_| WireError("snapshot integrity"))?;
        self.generation.write(output)?;
        self.records.write(output)?;
        self.snapshot_digest.write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        let value = Self { generation: Generation::read(input)?, records: Vec::read(input)?, snapshot_digest: Digest32::read(input)?, authority: AuthorityPosture::DENY_ALL };
        value.validate_integrity().map_err(|_| WireError("snapshot integrity"))?;
        Ok(value)
    }
}

wire_struct!(LaneCGenerationVectorV1 {
    scope_id: StableId, purpose_id: StableId, memory_ledger_frontier: u64,
    knowledge_fact_frontier: u64, tombstone_frontier: u64, source_ledger_frontier: u64,
    knowledge_graph_generation: Generation, compact_checkpoint_generation: Generation,
    prompt_registry_revision: Revision, retrieval_profile_digest: Digest32,
    encoder_preprocessor_digest: Digest32, authority_epoch: u64, model_digest: Digest32,
    tokenizer_digest: Digest32, template_digest: Digest32, tool_schema_digest: Digest32
});

impl Wire for CognitiveSnapshotKeyV1 {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        self.validate().map_err(|_| WireError("snapshot key"))?;
        self.vector.write(output)?;
        self.vector_digest.write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        let value = Self::new(LaneCGenerationVectorV1::read(input)?).map_err(|_| WireError("snapshot key"))?;
        if value.vector_digest != Digest32::read(input)? { return Err(WireError("snapshot key digest")); }
        Ok(value)
    }
}

wire_struct!(TrustEnrollmentV1 {
    schema_version: u32, role: CompactionTrustRoleV1, key_id: StableId, trust_epoch: u64,
    valid_from_unix_seconds: u64, valid_until_unix_seconds: u64,
    revoked_at_unix_seconds: Option<u64>, predecessor_key_digest: Option<Digest32>,
    implementation_digest: Digest32, attestation_digest: Digest32, verifying_key: [u8; 32]
});
wire_struct!(CompactionPolicyV2 {
    policy_id: StableId, algorithm_digest: Digest32, compatibility_digest: Digest32,
    tokenizer_digest: Digest32, tokenizer_implementation_digest: Digest32,
    maximum_retained_records: u32, maximum_retained_bytes: u64, maximum_retained_tokens: u64,
    maximum_payload_bytes: u64, maximum_payload_tokens: u64, protected_record_ids: Vec<StableId>
});
wire_struct!(TokenizationReceiptV1 {
    subject_digest: Digest32, tokenizer_digest: Digest32, tokenizer_implementation_digest: Digest32,
    encoded_bytes: u64, token_count: u64, signature: [u8; 64]
});
wire_struct!(CompactionInputRecordV2 {
    record: MemoryRecord, retention_priority: u32, retention_reason_digest: Digest32,
    encoded_bytes: u64, token_count: u64, tokenization_receipt: TokenizationReceiptV1
});

impl Wire for CompactionSemanticPayloadV2 {
    fn write(&self, output: &mut Encoder) -> Result<(), WireError> {
        self.source_snapshot_digest.write(output)?;
        self.source_memory_snapshot_digest.write(output)?;
        self.payload_digest.write(output)?;
        self.generator_implementation_digest.write(output)?;
        self.generator_receipt_digest.write(output)?;
        self.tokenizer_digest.write(output)?;
        self.encoded_bytes.write(output)?;
        self.token_count.write(output)?;
        self.tokenization_receipt.write(output)
    }
    fn read(input: &mut Decoder<'_>) -> Result<Self, WireError> {
        Ok(Self { source_snapshot_digest: Digest32::read(input)?, source_memory_snapshot_digest: Digest32::read(input)?, payload_digest: Digest32::read(input)?, payload: Vec::new(), generator_implementation_digest: Digest32::read(input)?, generator_receipt_digest: Digest32::read(input)?, tokenizer_digest: Digest32::read(input)?, encoded_bytes: u64::read(input)?, token_count: u64::read(input)?, tokenization_receipt: TokenizationReceiptV1::read(input)? })
    }
}

wire_struct!(SignedRetentionSelectionReceiptV1 {
    schema_version: u32, key_id: StableId, trust_epoch: u64, issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64, nonce: Digest32, source_snapshot_digest: Digest32,
    source_memory_snapshot_digest: Digest32, policy_digest: Digest32, input_manifest_digest: Digest32,
    tokenizer_key_id: StableId, tokenizer_trust_epoch: u64, tokenizer_key_digest: Digest32, signature: [u8; 64]
});
wire_struct!(SignedSemanticGenerationReceiptV1 {
    schema_version: u32, key_id: StableId, trust_epoch: u64, issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64, nonce: Digest32, source_snapshot_digest: Digest32,
    source_memory_snapshot_digest: Digest32, policy_digest: Digest32, selection_receipt_digest: Digest32,
    payload_digest: Digest32, tokenizer_key_id: StableId, tokenizer_trust_epoch: u64,
    tokenizer_key_digest: Digest32, tokenization_receipt_digest: Digest32, signature: [u8; 64]
});
wire_struct!(SignedCompactionEvaluationReceiptV1 {
    schema_version: u32, key_id: StableId, trust_epoch: u64, issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64, nonce: Digest32, candidate_digest: Digest32,
    qualification_digest: Digest32, signature: [u8; 64]
});
wire_struct!(CompactionQualificationV2 {
    tokenizer_implementation_digest: Digest32, tokenizer_attestation_digest: Digest32,
    tokenizer_key_digest: Digest32, evaluator_id: StableId, evaluator_implementation_digest: Digest32,
    evaluation_artifact_digest: Digest32, attestation_digest: Digest32, retained_query_suite_digest: Digest32,
    reconstruction_obligation_digest: Digest32, contradiction_holdout_digest: Digest32,
    retained_queries_passed: bool, reconstruction_passed: bool, contradictions_preserved: bool,
    deletion_non_resurrection_passed: bool, signature: [u8; 64]
});

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codec_rejects_truncation_tags_trailing_bytes_and_hostile_lengths() {
        assert!(bool::read(&mut Decoder::new(&[2], &[]).expect("decoder")).is_err());
        assert!(u64::read(&mut Decoder::new(&[0; 7], &[]).expect("decoder")).is_err());
        assert!(Vec::<u64>::read(&mut Decoder::new(&u32::MAX.to_be_bytes(), &[]).expect("decoder")).is_err());
        assert!(Decoder::new(&[1], &[]).expect("decoder").finish().is_err());
        assert!(Decoder::new(b"wrong", b"archive-v1").is_err());
    }

    #[test]
    fn codec_round_trip_is_byte_exact() {
        let value = vec![Some(0_u64), None, Some(u64::MAX)];
        let mut output = Encoder::new(b"test-v1").expect("encoder");
        value.write(&mut output).expect("encode");
        let bytes = output.finish();
        let mut input = Decoder::new(&bytes, b"test-v1").expect("decoder");
        assert_eq!(Vec::<Option<u64>>::read(&mut input).expect("decode"), value);
        input.finish().expect("exact end");
        for end in 0..bytes.len() {
            let rejected = Decoder::new(&bytes[..end], b"test-v1").and_then(|mut input| Vec::<Option<u64>>::read(&mut input).and_then(|_| input.finish()));
            assert!(rejected.is_err());
        }
    }
}
