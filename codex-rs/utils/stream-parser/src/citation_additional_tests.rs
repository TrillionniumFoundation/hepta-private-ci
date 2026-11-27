use crate::CitationStreamParser;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use crate::strip_citations;
use pretty_assertions::assert_eq;

#[test]
fn empty_push_does_not_finish_and_finish_can_be_reused() {
    let mut parser = CitationStreamParser::new();
    assert_eq!(
        parser.push_str("<oai-mem-citation>"),
        StreamTextChunk::default()
    );
    assert_eq!(parser.push_str(""), StreamTextChunk::default());
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![String::new()],
        }
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
    assert_eq!(
        parser.push_str("v<oai-mem-citation>x</oai-mem-citation>w"),
        StreamTextChunk {
            visible_text: "vw".to_string(),
            extracted: vec!["x".to_string()],
        }
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
}

#[test]
fn public_push_keeps_visible_and_completed_citations_in_their_original_call() {
    let mut parser = CitationStreamParser::new();
    assert_eq!(
        parser.push_str("start<oai-mem-"),
        StreamTextChunk {
            visible_text: "start".to_string(),
            extracted: Vec::new(),
        }
    );
    assert_eq!(
        parser.push_str("citation>a</oai-mem-citation><oai-mem-citation></oai-mem-"),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec!["a".to_string()],
        }
    );
    assert_eq!(
        parser.push_str("citation>end<oai-"),
        StreamTextChunk {
            visible_text: "end".to_string(),
            extracted: vec![String::new()],
        }
    );
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: "<oai-".to_string(),
            extracted: Vec::new(),
        }
    );
    assert_eq!(
        parser.push_str("tail"),
        StreamTextChunk {
            visible_text: "tail".to_string(),
            extracted: Vec::new(),
        }
    );
}

#[test]
fn transport_chunks_can_split_utf8_without_splitting_public_results() {
    let mut parser = CitationStreamParser::new();
    let prefix = "v".repeat(/*n*/ 4095);
    let visible = format!("{prefix}🦀tail");
    assert_eq!(
        parser.push_str(&visible),
        StreamTextChunk {
            visible_text: visible.clone(),
            extracted: Vec::new(),
        }
    );
    // The 18-byte opener puts the emoji's first byte at offset 4095.
    let prefix = "b".repeat(/*n*/ 4077);
    let body = format!("{prefix}🦀");
    assert_eq!(
        parser.push_str(&format!("<oai-mem-citation>{body}</oai-mem-citation>end")),
        StreamTextChunk {
            visible_text: "end".to_string(),
            extracted: vec![body],
        }
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
}

#[test]
fn one_public_call_collects_citations_across_many_transport_frames() {
    let citations = "<oai-mem-citation>源</oai-mem-citation>".repeat(/*n*/ 513);
    assert_eq!(
        strip_citations(&format!("L{citations}R")),
        ("LR".to_string(), vec!["源".to_string(); 513])
    );
}

#[test]
fn visible_text_and_citation_body_can_each_exceed_one_mebibyte() {
    let visible = "v".repeat(/*n*/ 1_048_577);
    let body = "中".repeat(/*n*/ 349_527);
    assert_eq!(
        strip_citations(&format!(
            "{visible}<oai-mem-citation>{body}</oai-mem-citation>tail"
        )),
        (format!("{visible}tail"), vec![body])
    );
}

#[test]
fn false_prefixes_and_unfinished_closers_preserve_literal_text() {
    assert_eq!(
        strip_citations("a<<oai-mem-citation>x</oai-mem-citation>b"),
        ("a<b".to_string(), vec!["x".to_string()])
    );
    assert_eq!(
        strip_citations("</oai-mem-citation>"),
        ("</oai-mem-citation>".to_string(), Vec::new())
    );
    assert_eq!(
        strip_citations("x<oai-mem-citation>body</oai-mem-"),
        ("x".to_string(), vec!["body</oai-mem-".to_string()])
    );
}

#[test]
fn initial_debug_preserves_compact_and_alternate_structures() {
    let parser = CitationStreamParser::new();
    assert_eq!(
        format!("{parser:?}"),
        r#"CitationStreamParser { inner: InlineHiddenTagParser { specs: [InlineTagSpec { tag: Citation, open: "<oai-mem-citation>", close: "</oai-mem-citation>" }], pending: "", active: None } }"#
    );
    assert_eq!(
        format!("{parser:#?}"),
        r#"CitationStreamParser {
    inner: InlineHiddenTagParser {
        specs: [
            InlineTagSpec {
                tag: Citation,
                open: "<oai-mem-citation>",
                close: "</oai-mem-citation>",
            },
        ],
        pending: "",
        active: None,
    },
}"#
    );
}

#[test]
fn inspecting_a_partial_opener_does_not_change_continuation() {
    let mut parser = CitationStreamParser::new();
    assert_eq!(
        parser.push_str("a<oai-mem-"),
        StreamTextChunk {
            visible_text: "a".to_string(),
            extracted: Vec::new(),
        }
    );
    let expected = r#"CitationStreamParser { inner: InlineHiddenTagParser { specs: [InlineTagSpec { tag: Citation, open: "<oai-mem-citation>", close: "</oai-mem-citation>" }], pending: "<oai-mem-", active: None } }"#;
    assert_eq!(format!("{parser:?}"), expected);
    assert_eq!(format!("{parser:?}"), expected);
    assert_eq!(
        parser.push_str("citation>body</oai-mem-citation>z"),
        StreamTextChunk {
            visible_text: "z".to_string(),
            extracted: vec!["body".to_string()],
        }
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
}

#[test]
fn active_debug_keeps_pending_prefix_separate_from_escaped_body() {
    let mut parser = CitationStreamParser::new();
    assert_eq!(
        parser.push_str("<oai-mem-citation>a\"\\\n中</oai-mem-"),
        StreamTextChunk::default()
    );
    assert_eq!(
        format!("{parser:?}"),
        r#"CitationStreamParser { inner: InlineHiddenTagParser { specs: [InlineTagSpec { tag: Citation, open: "<oai-mem-citation>", close: "</oai-mem-citation>" }], pending: "</oai-mem-", active: Some(ActiveTag { tag: Citation, close: "</oai-mem-citation>", content: "a\"\\\n中" }) } }"#
    );
    assert_eq!(
        format!("{parser:#?}"),
        r#"CitationStreamParser {
    inner: InlineHiddenTagParser {
        specs: [
            InlineTagSpec {
                tag: Citation,
                open: "<oai-mem-citation>",
                close: "</oai-mem-citation>",
            },
        ],
        pending: "</oai-mem-",
        active: Some(
            ActiveTag {
                tag: Citation,
                close: "</oai-mem-citation>",
                content: "a\"\\\n中",
            },
        ),
    },
}"#
    );
    assert_eq!(
        parser.push_str("citation>ok"),
        StreamTextChunk {
            visible_text: "ok".to_string(),
            extracted: vec!["a\"\\\n中".to_string()],
        }
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
}

#[test]
fn finish_restores_debug_after_an_empty_active_body_and_reuse() {
    let mut parser = CitationStreamParser::new();
    let initial = format!("{parser:?}");
    assert_eq!(
        parser.push_str("<oai-mem-citation>"),
        StreamTextChunk::default()
    );
    assert_eq!(
        format!("{parser:?}"),
        r#"CitationStreamParser { inner: InlineHiddenTagParser { specs: [InlineTagSpec { tag: Citation, open: "<oai-mem-citation>", close: "</oai-mem-citation>" }], pending: "", active: Some(ActiveTag { tag: Citation, close: "</oai-mem-citation>", content: "" }) } }"#
    );
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![String::new()],
        }
    );
    assert_eq!(format!("{parser:?}"), initial);
    assert_eq!(parser.finish(), StreamTextChunk::default());
    assert_eq!(
        parser.push_str("<oai-mem-citation>x"),
        StreamTextChunk::default()
    );
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec!["x".to_string()],
        }
    );
    assert_eq!(format!("{parser:?}"), initial);
}
