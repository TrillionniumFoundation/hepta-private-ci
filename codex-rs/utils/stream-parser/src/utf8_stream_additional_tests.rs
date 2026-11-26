use super::Utf8StreamParser;
use super::Utf8StreamParserError;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use pretty_assertions::assert_eq;

#[derive(Debug, Default, PartialEq, Eq)]
struct ObservedParser {
    calls: Vec<String>,
    finishes: usize,
}

impl StreamTextParser for ObservedParser {
    type Extracted = String;

    fn push_str(&mut self, chunk: &str) -> StreamTextChunk<Self::Extracted> {
        self.calls.push(chunk.to_owned());
        StreamTextChunk {
            visible_text: chunk.to_owned(),
            extracted: vec![format!("push:{chunk}")],
        }
    }

    fn finish(&mut self) -> StreamTextChunk<Self::Extracted> {
        self.finishes += 1;
        StreamTextChunk {
            visible_text: "tail".to_owned(),
            extracted: vec!["finish".to_owned()],
        }
    }
}

#[test]
fn invalid_suffix_rolls_back_completed_pending_scalar_and_all_inner_effects() {
    let mut parser = Utf8StreamParser::new(ObservedParser::default());
    assert!(parser.push_bytes(&[0xc3]).unwrap().is_empty());
    assert_eq!(
        parser.push_bytes(&[0xa9, b'a', 0xff]),
        Err(Utf8StreamParserError::InvalidUtf8 {
            valid_up_to: 3,
            error_len: 1,
        })
    );
    assert_eq!(parser.pending_utf8, [0xc3]);
    assert_eq!(parser.inner, ObservedParser::default());
    assert_eq!(
        parser.push_bytes(&[0xa9, b'b']).unwrap(),
        StreamTextChunk {
            visible_text: "éb".to_owned(),
            extracted: vec!["push:éb".to_owned()],
        }
    );
    assert_eq!(parser.into_inner().unwrap().calls, ["éb"]);
}

#[test]
fn partial_eof_preserves_state_and_prevents_inner_finish_until_recovery() {
    let mut parser = Utf8StreamParser::new(ObservedParser::default());
    assert_eq!(parser.push_bytes(b"ok\xf0\x9f").unwrap().visible_text, "ok");
    assert_eq!(parser.pending_utf8, [0xf0, 0x9f]);
    assert_eq!(
        parser.finish(),
        Err(Utf8StreamParserError::IncompleteUtf8AtEof)
    );
    assert_eq!(parser.inner.calls, ["ok"]);
    assert_eq!(parser.inner.finishes, 0);
    assert_eq!(parser.pending_utf8, [0xf0, 0x9f]);
    assert_eq!(parser.push_bytes(&[0xa6, 0x80]).unwrap().visible_text, "🦀");
    assert_eq!(
        parser.finish().unwrap(),
        StreamTextChunk {
            visible_text: "tail".to_owned(),
            extracted: vec!["finish".to_owned()],
        }
    );
    assert_eq!(
        parser.into_inner().unwrap(),
        ObservedParser {
            calls: vec!["ok".to_owned(), "🦀".to_owned()],
            finishes: 1,
        }
    );
}

#[test]
fn empty_push_and_whole_public_chunk_keep_original_inner_call_boundaries() {
    let mut parser = Utf8StreamParser::new(ObservedParser::default());
    assert_eq!(parser.push_bytes(&[]).unwrap().extracted, ["push:"]);
    let text = "aé中🦀".repeat(/*n*/ 131_073);
    assert!(text.len() > 1_048_576);
    assert_eq!(
        parser.push_bytes(text.as_bytes()).unwrap().visible_text,
        text
    );
    assert_eq!(parser.inner.calls, [String::new(), text]);
}

#[test]
fn every_split_of_scalar_boundary_examples_preserves_text_and_eof_effects() {
    for text in [
        "\0",
        "é",
        "\u{800}",
        "\u{d7ff}",
        "\u{e000}",
        "\u{10000}",
        "\u{10ffff}",
        "aé中🦀z",
    ] {
        for split in 0..=text.len() {
            let mut parser = Utf8StreamParser::new(ObservedParser::default());
            let first = parser.push_bytes(&text.as_bytes()[..split]).unwrap();
            let second = parser.push_bytes(&text.as_bytes()[split..]).unwrap();
            assert_eq!(
                format!("{}{}", first.visible_text, second.visible_text),
                text
            );
            assert!(parser.pending_utf8.is_empty());
            assert_eq!(parser.finish().unwrap().visible_text, "tail");
            assert_eq!(parser.inner.finishes, 1);
        }
    }
}
