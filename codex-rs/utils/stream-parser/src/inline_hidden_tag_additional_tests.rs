use super::ExtractedInlineTag;
use super::InlineHiddenTagParser;
use super::InlineTagSpec;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::rc::Rc;

#[test]
fn longest_opener_and_first_spec_break_only_equal_position_ties() {
    let mut parser = InlineHiddenTagParser::new(vec![
        InlineTagSpec {
            tag: 1,
            open: "ab",
            close: "x",
        },
        InlineTagSpec {
            tag: 2,
            open: "a",
            close: "y",
        },
        InlineTagSpec {
            tag: 3,
            open: "ab",
            close: "z",
        },
    ]);
    assert_eq!(
        parser.push_str("qabvxy"),
        StreamTextChunk {
            visible_text: "qy".to_owned(),
            extracted: vec![ExtractedInlineTag {
                tag: 1,
                content: "v".to_owned()
            }],
        }
    );
    let mut parser = InlineHiddenTagParser::new(vec![
        InlineTagSpec {
            tag: 1,
            open: "long",
            close: "!",
        },
        InlineTagSpec {
            tag: 2,
            open: "a",
            close: "?",
        },
    ]);
    assert_eq!(
        parser.push_str("0aXlong!?tail"),
        StreamTextChunk {
            visible_text: "0t".to_owned(),
            extracted: vec![ExtractedInlineTag {
                tag: 2,
                content: "Xlong!".to_owned()
            }],
        }
    );
    // The final "a" opens another tag under the original parser's rules.
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![ExtractedInlineTag {
                tag: 2,
                content: "il".to_owned(),
            }],
        }
    );
}

#[test]
fn every_scalar_split_keeps_literal_non_nested_and_eof_results() {
    let text = "a<é>中<é>literal</é>b<ab>z</ab>tail<";
    let expected = StreamTextChunk {
        visible_text: "abtail<".to_owned(),
        extracted: vec![
            ExtractedInlineTag {
                tag: 1,
                content: "中<é>literal".to_owned(),
            },
            ExtractedInlineTag {
                tag: 3,
                content: "z".to_owned(),
            },
        ],
    };
    for split in 0..=text.len() {
        if !text.is_char_boundary(split) {
            continue;
        }
        let mut parser = InlineHiddenTagParser::new(vec![
            InlineTagSpec {
                tag: 1,
                open: "<é>",
                close: "</é>",
            },
            InlineTagSpec {
                tag: 2,
                open: "<a>",
                close: "</a>",
            },
            InlineTagSpec {
                tag: 3,
                open: "<ab>",
                close: "</ab>",
            },
        ]);
        let mut actual = StreamTextChunk::default();
        for chunk in [&text[..split], &text[split..]] {
            let next = parser.push_str(chunk);
            actual.visible_text.push_str(&next.visible_text);
            actual.extracted.extend(next.extracted);
        }
        let tail = parser.finish();
        actual.visible_text.push_str(&tail.visible_text);
        actual.extracted.extend(tail.extracted);
        assert_eq!(actual, expected, "split {split}");
    }
}

#[test]
fn public_calls_keep_pending_and_active_debug_fields_exact() {
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: 7,
        open: "aba",
        close: "xyé",
    }]);
    assert_eq!(
        parser.push_str("vab"),
        StreamTextChunk {
            visible_text: "v".to_owned(),
            extracted: Vec::new(),
        }
    );
    assert_eq!(
        format!("{parser:?}"),
        "InlineHiddenTagParser { specs: [InlineTagSpec { tag: 7, open: \"aba\", close: \"xyé\" }], pending: \"ab\", active: None }"
    );
    assert!(parser.push_str("aBODYx").is_empty());
    assert_eq!(
        format!("{parser:?}"),
        "InlineHiddenTagParser { specs: [InlineTagSpec { tag: 7, open: \"aba\", close: \"xyé\" }], pending: \"x\", active: Some(ActiveTag { tag: 7, close: \"xyé\", content: \"BODY\" }) }"
    );
    assert!(parser.push_str("").is_empty());
    assert_eq!(
        parser.push_str("yéz"),
        StreamTextChunk {
            visible_text: "z".to_owned(),
            extracted: vec![ExtractedInlineTag {
                tag: 7,
                content: "BODY".to_owned()
            }],
        }
    );
    assert!(parser.finish().is_empty());
}

#[test]
fn eof_flushes_partial_close_and_partial_open_and_allows_reuse() {
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: 1,
        open: "<a>",
        close: "</a>",
    }]);
    assert!(parser.push_str("<a>body</").is_empty());
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![ExtractedInlineTag {
                tag: 1,
                content: "body</".to_owned()
            }],
        }
    );
    assert!(parser.finish().is_empty());
    assert_eq!(parser.push_str("pref<a").visible_text, "pref");
    assert_eq!(
        parser.finish(),
        StreamTextChunk {
            visible_text: "<a".to_owned(),
            extracted: Vec::new(),
        }
    );
    assert_eq!(parser.push_str("plain").visible_text, "plain");
}

#[test]
fn adjacent_empty_tags_and_distinct_calls_keep_every_extraction() {
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: 1,
        open: "[",
        close: "]",
    }]);
    assert_eq!(
        parser.push_str("x[]y[]z"),
        StreamTextChunk {
            visible_text: "xyz".to_owned(),
            extracted: vec![
                ExtractedInlineTag {
                    tag: 1,
                    content: String::new()
                };
                2
            ],
        }
    );
    for _ in 0..2 {
        assert_eq!(
            parser.push_str("[]"),
            StreamTextChunk {
                visible_text: String::new(),
                extracted: vec![ExtractedInlineTag {
                    tag: 1,
                    content: String::new()
                }],
            }
        );
    }
}

#[test]
fn delimiter_and_pending_prefix_can_each_exceed_one_mebibyte() {
    let prefix = "x".repeat(/*n*/ 1_048_577);
    let delimiter: &'static str = Box::leak(format!("{prefix}$").into_boxed_str());
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: 1,
        open: delimiter,
        close: "!",
    }]);
    assert!(parser.push_str(&prefix).is_empty());
    assert_eq!(parser.pending, prefix);
    assert_eq!(
        parser.push_str("$body!tail"),
        StreamTextChunk {
            visible_text: "tail".to_owned(),
            extracted: vec![ExtractedInlineTag {
                tag: 1,
                content: "body".to_owned()
            }],
        }
    );
}

#[test]
fn visible_and_extracted_text_have_no_new_aggregate_limit() {
    let text = "é".repeat(/*n*/ 524_289);
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: 1,
        open: "<a>",
        close: "</a>",
    }]);
    assert_eq!(parser.push_str(&text).visible_text, text);
    assert!(parser.push_str("<a>").is_empty());
    assert!(parser.push_str(&text).is_empty());
    assert_eq!(
        parser.push_str("</a>"),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![ExtractedInlineTag {
                tag: 1,
                content: text
            }],
        }
    );
}

#[test]
fn thousands_of_specs_keep_the_original_first_index_tie_break() {
    let mut parser = InlineHiddenTagParser::new(
        (0..4_097)
            .map(|tag| InlineTagSpec {
                tag,
                open: "[",
                close: "]",
            })
            .collect(),
    );
    assert_eq!(
        parser.push_str("[body]"),
        StreamTextChunk {
            visible_text: String::new(),
            extracted: vec![ExtractedInlineTag {
                tag: 0,
                content: "body".to_owned()
            }],
        }
    );
}

#[derive(Debug)]
struct ObservedTag {
    clones: Rc<Cell<usize>>,
    comparisons: Rc<Cell<usize>>,
}

impl Clone for ObservedTag {
    fn clone(&self) -> Self {
        self.clones.set(self.clones.get() + 1);
        Self {
            clones: Rc::clone(&self.clones),
            comparisons: Rc::clone(&self.comparisons),
        }
    }
}

impl PartialEq for ObservedTag {
    fn eq(&self, _other: &Self) -> bool {
        self.comparisons.set(self.comparisons.get() + 1);
        true
    }
}

impl Eq for ObservedTag {}

#[test]
fn user_tag_clone_and_equality_effects_remain_at_original_boundaries() {
    let clones = Rc::new(Cell::new(/*value*/ 0));
    let comparisons = Rc::new(Cell::new(/*value*/ 0));
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: ObservedTag {
            clones: Rc::clone(&clones),
            comparisons: Rc::clone(&comparisons),
        },
        open: "[",
        close: "]",
    }]);
    assert!(parser.push_str("").is_empty());
    assert_eq!(clones.get(), 0);
    assert_eq!(parser.push_str("[x]").extracted[0].content, "x");
    assert!(parser.push_str("[y").is_empty());
    assert_eq!(parser.finish().extracted[0].content, "y");
    assert_eq!((clones.get(), comparisons.get()), (2, 0));
}

#[derive(Debug, PartialEq, Eq)]
struct PanickingClone;

impl Clone for PanickingClone {
    fn clone(&self) -> Self {
        panic!("observed tag clone");
    }
}

#[test]
fn clone_panic_occurs_after_pending_drain_and_before_active_assignment() {
    let mut parser = InlineHiddenTagParser::new(vec![InlineTagSpec {
        tag: PanickingClone,
        open: "<a>",
        close: "</a>",
    }]);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        parser.push_str("prefix<a>body");
    }));
    assert!(result.is_err());
    assert_eq!(parser.pending, "body");
    assert_eq!(parser.active, None);
    assert_eq!(parser.push_str("tail").visible_text, "bodytail");
}

#[test]
#[should_panic(expected = "at least one tag spec")]
fn constructor_keeps_its_empty_spec_assertion() {
    let _ = InlineHiddenTagParser::<u8>::new(Vec::new());
}
