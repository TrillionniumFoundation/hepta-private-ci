use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::super::CanonicalContextSourceV3;
use super::*;
use crate::CanonicalSerializedContextV2;
use crate::ContextAdmissionBindingV2;
use crate::ContextAdmissionRecordV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextCandidateV2;
use crate::ContextCompilationRequestV2;
use crate::ContextCompilerV2Error;
use crate::ContextModelProfileV2;
use crate::ContextRealizedItemV2;
use crate::ExactTokenizerV2;
use crate::TokenizationReceiptV2;
use crate::compile_v2;
use crate::record_canonical_serialization_v2;
use crate::verify_admission_snapshot_v2;
use crate::verify_admission_v2;

// These are the same public compiler producers used by the existing V2 tests.
// This verifier/tokenizer is a test seam, not a provider qualification.
struct FixtureVerifier;
impl ContextAdmissionVerifierV2 for FixtureVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("verifier")
    }
    fn verify_record(&self, value: &ContextAdmissionRecordV2) -> bool {
        value.validate_shape().is_ok()
    }
    fn verify_snapshot(&self, value: &ContextAdmissionSnapshotV2) -> bool {
        value.validate_shape().is_ok()
    }
}

struct FixtureTokenizer;
impl ExactTokenizerV2 for FixtureTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("tokenizer")
    }
    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        u64::try_from(bytes.len()).map_err(|_| ContextCompilerV2Error::Arithmetic)
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture identity: {error}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Fixture {
    compiled: CompiledContextV2,
    canonical: CanonicalSerializedContextV2,
    profile: ContextModelProfileV2,
    realizations: Vec<ContextRealizedItemV2>,
}

impl Fixture {
    fn view(&self) -> Result<CanonicalContextSourceV3<'_>, Error> {
        CanonicalContextSourceV3::from_canonical_v2(&self.compiled, &self.canonical, &self.profile)
    }
}

fn fixture(evidence: &[u8]) -> Result<Fixture, Error> {
    let profile = ContextModelProfileV2 {
        model_digest: digest("model"),
        provider_id_digest: digest("provider"),
        provider_model_digest: digest("provider-model"),
        tokenizer_digest: digest("tokenizer"),
        serializer_digest: digest("serializer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("schema"),
        maximum_context_tokens: 16_384,
    };
    let snapshot = verify_admission_snapshot_v2(
        ContextAdmissionSnapshotV2::new(
            id("snapshot"),
            digest("scope"),
            digest("authority"),
            /*observed_unix_ms*/ 10,
            /*revocation_epoch*/ 1,
            Vec::new(),
            /*revocation_set_complete*/ true,
            /*predecessor_snapshot_digest*/ None,
        )?,
        &FixtureVerifier,
    )?;
    let mut candidates = Vec::new();
    let mut realizations = Vec::new();
    for (name, role, content) in [
        (
            "instruction",
            ContextRoleV2::TrustedInstruction,
            b"Preserve provenance".as_slice(),
        ),
        (
            "schema",
            ContextRoleV2::Schema,
            b"{\"answer\":\"string\"}".as_slice(),
        ),
        ("evidence", ContextRoleV2::UntrustedEvidence, evidence),
    ] {
        let item_id = id(name);
        let content_digest = Digest32::of_bytes(content);
        let source_digest = digest(&format!("source:{name}"));
        let admission = verify_admission_v2(
            ContextAdmissionRecordV2::new(
                id(&format!("admission:{name}")),
                ContextAdmissionBindingV2 {
                    item_id: item_id.clone(),
                    role,
                    content_digest,
                    source_digest,
                    generation_vector_digest: digest("generation"),
                    scope_digest: digest("scope"),
                    authority_domain_digest: digest("authority"),
                    contains_secret: false,
                },
                /*issued_unix_ms*/ 1,
                /*expires_unix_ms*/ 1000,
            )?,
            &snapshot,
            &FixtureVerifier,
        )?;
        candidates.push(ContextCandidateV2 {
            item_id: item_id.clone(),
            role,
            content_digest,
            source_digest,
            generation_vector_digest: digest("generation"),
            tokenization: TokenizationReceiptV2::from_exact_bytes(
                item_id.clone(),
                content,
                &FixtureTokenizer,
            )?,
            expected_value: FixedQ32::ONE,
            admission,
        });
        realizations.push(ContextRealizedItemV2 {
            item_id,
            role,
            content: content.to_vec(),
        });
    }
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: id("compiled"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation"),
        scope_digest: digest("scope"),
        authority_domain_digest: digest("authority"),
        admission_verifier_digest: FixtureVerifier.verifier_digest(),
        model_profile: profile.clone(),
        token_budget: 16_384,
        truncation_policy_digest: digest("truncation"),
        candidates,
        mandatory_groups: Vec::new(),
    })?;
    let canonical = record_canonical_serialization_v2(
        &compiled,
        &profile,
        id("serialized"),
        realizations.clone(),
        &FixtureTokenizer,
    )?;
    Ok(Fixture {
        compiled,
        canonical,
        profile,
        realizations,
    })
}

#[test]
fn source_view_preserves_v2_bytes_and_exhaustive_typed_fields() -> Result<(), Error> {
    let fixture = fixture("snowman: ☃\ncontrol:\u{0001}".as_bytes())?;
    let original = fixture.canonical.clone();
    let view = fixture.view()?;
    let payload = view.canonical_v2().serialized_context().payload();
    let mut expected = b"hepta.context-canonical-bundle.v2".to_vec();
    expected.extend_from_slice(&3_u64.to_be_bytes());
    for candidate in fixture.compiled.selected_candidates() {
        let source = fixture
            .realizations
            .iter()
            .find(|item| item.item_id == candidate.item_id)
            .ok_or(Error::SelectedSetMismatch)?;
        expected.extend_from_slice(
            &u64::try_from(source.item_id.as_str().len())
                .map_err(|_| Error::Arithmetic)?
                .to_be_bytes(),
        );
        expected.extend_from_slice(source.item_id.as_str().as_bytes());
        expected.push(match source.role {
            ContextRoleV2::TrustedInstruction => 0,
            ContextRoleV2::Schema => 1,
            ContextRoleV2::UntrustedEvidence => 2,
        });
        expected.extend_from_slice(
            &u64::try_from(source.content.len())
                .map_err(|_| Error::Arithmetic)?
                .to_be_bytes(),
        );
        expected.extend_from_slice(&source.content);
    }
    assert_eq!(payload, expected);
    let mut offset = 0;
    for segment in view.segments() {
        assert_eq!(segment.offset(), offset);
        let end = offset
            .checked_add(segment.length())
            .ok_or(Error::Arithmetic)?;
        let bytes = &payload[usize::try_from(offset).map_err(|_| Error::Arithmetic)?
            ..usize::try_from(end).map_err(|_| Error::Arithmetic)?];
        assert_eq!(segment.encoded_digest(), Digest32::of_bytes(bytes));
        offset = end;
    }
    assert_eq!(
        usize::try_from(offset).map_err(|_| Error::Arithmetic)?,
        payload.len()
    );
    let mut fields = vec![Field::Domain, Field::ItemCount];
    for (index, candidate) in fixture.compiled.selected_candidates().iter().enumerate() {
        let selected_index = u64::try_from(index).map_err(|_| Error::Arithmetic)?;
        fields.extend([
            Field::ItemIdLength { selected_index },
            Field::ItemId { selected_index },
            Field::Role {
                selected_index,
                role: candidate.role,
            },
            Field::ContentLength { selected_index },
            Field::Content { selected_index },
        ]);
    }
    assert_eq!(
        view.segments()
            .iter()
            .map(Segment::field)
            .collect::<Vec<_>>(),
        fields
    );
    assert_ne!(view.metadata_digest(), fixture.canonical.coverage_digest());
    assert_eq!(fixture.canonical, original);
    Ok(())
}

#[test]
fn canonical_producer_order_is_preserved_without_caller_maps() -> Result<(), Error> {
    let fixture = fixture(b"reference")?;
    let mut reversed = fixture.realizations.clone();
    reversed.reverse();
    let canonical = record_canonical_serialization_v2(
        &fixture.compiled,
        &fixture.profile,
        id("serialized"),
        reversed,
        &FixtureTokenizer,
    )?;
    let first = fixture.view()?;
    let second = CanonicalContextSourceV3::from_canonical_v2(
        &fixture.compiled,
        &canonical,
        &fixture.profile,
    )?;
    assert_eq!(first, second);
    Ok(())
}

#[test]
fn source_view_rejects_another_compilation_and_profile() -> Result<(), Error> {
    let fixture = fixture(b"reference")?;
    let other = self::fixture(b"other reference")?;
    assert_ne!(
        fixture.view()?.metadata_digest(),
        other.view()?.metadata_digest()
    );
    let expected = Err(Error::Context(
        ContextCompilerV2Error::SerializationMismatch,
    ));
    assert_eq!(
        CanonicalContextSourceV3::from_canonical_v2(
            &other.compiled,
            &fixture.canonical,
            &fixture.profile,
        ),
        expected
    );
    let mut changed = fixture.profile.clone();
    changed.model_digest = digest("another-model");
    assert_eq!(
        CanonicalContextSourceV3::from_canonical_v2(
            &fixture.compiled,
            &fixture.canonical,
            &changed,
        ),
        expected
    );
    Ok(())
}

#[test]
fn private_derivation_rejects_mutated_truncated_and_appended_bytes() -> Result<(), Error> {
    let fixture = fixture(b"reference")?;
    let original = fixture.canonical.serialized_context().payload();
    assert!(derive_segments(&fixture.compiled, original).is_ok());
    for index in 0..original.len() {
        let mut changed = original.to_vec();
        changed[index] ^= 1;
        assert!(
            derive_segments(&fixture.compiled, &changed).is_err(),
            "byte {index}"
        );
        assert!(
            derive_segments(&fixture.compiled, &original[..index]).is_err(),
            "prefix {index}"
        );
    }
    let mut appended = original.to_vec();
    appended.push(0);
    assert_eq!(
        derive_segments(&fixture.compiled, &appended),
        Err(Error::IncompleteSegmentCoverage)
    );
    // The incoming layout's extra digest is not another interpretation of V2.
    let fields = derive_segments(&fixture.compiled, original)?;
    let content = fields
        .iter()
        .find(|s| matches!(s.field, Field::Content { .. }))
        .ok_or(Error::InvalidSegment)?;
    let insert = usize::try_from(content.offset - 8).map_err(|_| Error::Arithmetic)?;
    let mut different_format = original.to_vec();
    different_format.splice(
        insert..insert,
        content.encoded_digest.as_array().iter().copied(),
    );
    assert!(derive_segments(&fixture.compiled, &different_format).is_err());
    Ok(())
}

#[test]
fn reordering_complete_item_records_cannot_change_selected_order() -> Result<(), Error> {
    let fixture = fixture(b"reference")?;
    let original = fixture.canonical.serialized_context().payload();
    let segments = derive_segments(&fixture.compiled, original)?;
    let starts = segments
        .iter()
        .filter(|segment| matches!(segment.field, Field::ItemIdLength { .. }))
        .map(|segment| usize::try_from(segment.offset).map_err(|_| Error::Arithmetic))
        .collect::<Result<Vec<_>, _>>()?;
    let [first, second, third] = starts.as_slice() else {
        return Err(Error::SelectedSetMismatch);
    };
    let mut reordered = original[..*first].to_vec();
    reordered.extend_from_slice(&original[*second..*third]);
    reordered.extend_from_slice(&original[*first..*second]);
    reordered.extend_from_slice(&original[*third..]);
    assert_eq!(reordered.len(), original.len());
    assert_eq!(
        derive_segments(&fixture.compiled, &reordered),
        Err(Error::SelectedSetMismatch)
    );
    Ok(())
}

#[test]
fn complete_control_content_is_required_even_with_consistent_shorter_framing() -> Result<(), Error>
{
    let content = "snowman: ☃\ncontrol:\u{0001}".as_bytes();
    let fixture = fixture(content)?;
    let segments = derive_segments(
        &fixture.compiled,
        fixture.canonical.serialized_context().payload(),
    )?;
    let selected_index = u64::try_from(
        fixture
            .compiled
            .selected_candidates()
            .iter()
            .position(|candidate| candidate.item_id == id("evidence"))
            .ok_or(Error::SelectedSetMismatch)?,
    )
    .map_err(|_| Error::Arithmetic)?;
    let body = segments
        .iter()
        .find(|s| s.field == Field::Content { selected_index })
        .ok_or(Error::InvalidSegment)?;
    let length = segments
        .iter()
        .find(|s| s.field == Field::ContentLength { selected_index })
        .ok_or(Error::InvalidSegment)?;
    let mut changed = fixture.canonical.serialized_context().payload().to_vec();
    let start = usize::try_from(body.offset).map_err(|_| Error::Arithmetic)?;
    let end = usize::try_from(body.offset + body.length).map_err(|_| Error::Arithmetic)?;
    assert_eq!(&changed[start..end], content);
    changed.drain(end - 10..end);
    let length_start = usize::try_from(length.offset).map_err(|_| Error::Arithmetic)?;
    changed[length_start..length_start + 8].copy_from_slice(&(body.length - 10).to_be_bytes());
    assert_eq!(
        derive_segments(&fixture.compiled, &changed),
        Err(Error::DigestMismatch("canonical_source_content"))
    );
    // This is a canonical-source negative, not a hand-written HTTP JSON positive.
    assert!(
        CanonicalContextSourceV3::from_canonical_v2(
            &fixture.compiled,
            &fixture.canonical,
            &fixture.profile,
        )
        .is_ok()
    );
    Ok(())
}

#[test]
fn declared_length_overflow_is_rejected_before_allocation() -> Result<(), Error> {
    let fixture = fixture(b"reference")?;
    let original = fixture.canonical.serialized_context().payload();
    for segment in derive_segments(&fixture.compiled, original)? {
        if !matches!(
            segment.field,
            Field::ItemCount | Field::ItemIdLength { .. } | Field::ContentLength { .. }
        ) {
            continue;
        }
        let mut changed = original.to_vec();
        let start = usize::try_from(segment.offset).map_err(|_| Error::Arithmetic)?;
        changed[start..start + 8].copy_from_slice(&u64::MAX.to_be_bytes());
        let expected = if segment.field == Field::ItemCount {
            Error::SelectedSetMismatch
        } else {
            Error::Arithmetic
        };
        assert_eq!(derive_segments(&fixture.compiled, &changed), Err(expected));
    }
    Ok(())
}

#[test]
fn source_view_debug_excludes_content_and_serialized_bytes() -> Result<(), Error> {
    let content = b"PRIVATE SOURCE CONTENT: preserve exactly, never put it in diagnostics";
    let fixture = fixture(content)?;
    let view = fixture.view()?;
    let display = format!("{view:?}");
    assert!(
        !display.contains(std::str::from_utf8(content).map_err(|_| Error::InvalidText("fixture"))?)
    );
    assert!(!display.contains(&format!(
        "{:?}",
        fixture.canonical.serialized_context().payload()
    )));
    assert_eq!(
        display,
        format!(
            "CanonicalContextSourceV3 {{ v2_receipt_digest: {:?}, segment_count: {}, metadata_digest: {:?} }}",
            fixture
                .canonical
                .serialized_context()
                .receipt()
                .receipt_digest(),
            view.segments().len(),
            view.metadata_digest(),
        )
    );
    Ok(())
}

#[test]
fn existing_binary_content_is_preserved_without_lossy_text_conversion() -> Result<(), Error> {
    let content = [0xff, 0, 0x80, b'\n'];
    let fixture = fixture(&content)?;
    let view = fixture.view()?;
    let source = view.canonical_v2().serialized_context().payload();
    assert!(source.windows(content.len()).any(|bytes| bytes == content));
    assert_eq!(view.canonical_v2(), &fixture.canonical);
    Ok(())
}
