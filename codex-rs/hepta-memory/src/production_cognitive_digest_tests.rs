use std::cell::Cell;
use std::io::Write;

use serde::ser::SerializeSeq;

use super::*;
use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::SourceDraft;

#[test]
fn streamed_digest_preserves_legacy_json_identity() -> Result<(), Box<dyn std::error::Error>> {
    for text in ["plain", "quoted \" text", "control\n\t\u{0}", "共享経験🧠"] {
        let value = ("remember", vec![0_u8, 127, 255], text, Some(42_u64));
        assert_eq!(
            input_digest(&value)?,
            Sha256Digest::for_bytes(&serde_json::to_vec(&value)?),
        );
    }
    Ok(())
}

#[test]
fn maximum_source_byte_expansion_fits_without_changing_identity()
-> Result<(), Box<dyn std::error::Error>> {
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "maximum-source".into(),
        content: vec![255; crate::cognitive_model::MAX_SOURCE_BYTES],
        observed_at_unix_seconds: 1,
    };
    let text = "\u{0}".repeat(crate::cognitive_model::MAX_MEMORY_BYTES);
    let input = ("remember", source, text);
    assert_eq!(
        input_digest(&input)?,
        Sha256Digest::for_bytes(&serde_json::to_vec(&input)?),
    );
    Ok(())
}

struct ManyChunks<'a> {
    visited: &'a Cell<usize>,
}

impl Serialize for ManyChunks<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let chunk = "x".repeat(4096);
        let mut sequence = serializer.serialize_seq(Some(100_000))?;
        for _ in 0..100_000 {
            self.visited.set(self.visited.get() + 1);
            sequence.serialize_element(&chunk)?;
        }
        sequence.end()
    }
}

#[test]
fn oversize_serialization_stops_without_traversing_the_remaining_input() {
    let visited = Cell::new(0);
    let error = input_digest(&ManyChunks { visited: &visited });
    assert!(matches!(error, Err(ProductionWriterError::Invalid(_))));
    assert!(visited.get() <= MAX_ENCODED_INPUT_BYTES / 4096 + 1);
}

#[test]
fn overflowing_write_never_admits_a_shorter_followup() -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = InputDigestWriter {
        hasher: Sha256::new(),
        remaining: 3,
        exhausted: false,
    };
    writer.write_all(b"abc")?;
    assert!(writer.write_all(b"d").is_err());
    assert!(writer.write(b"").is_err());
    assert_eq!(writer.remaining, 0);
    assert_eq!(
        Sha256Digest::from_sha256_output(writer.hasher.finalize()),
        Sha256Digest::for_bytes(b"abc"),
    );
    Ok(())
}

#[test]
fn owner_source_limit_is_checked_before_serializing_other_fields() {
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "oversize-source".into(),
        content: vec![1; crate::cognitive_model::MAX_SOURCE_BYTES + 1],
        observed_at_unix_seconds: 1,
    };
    let visited = Cell::new(0);
    let result = super::super::production_cognitive_input_digest(
        "remember",
        &source,
        &ManyChunks { visited: &visited },
    );
    assert!(matches!(result, Err(ProductionWriterError::Invalid(_))));
    assert_eq!(visited.get(), 0);
}
