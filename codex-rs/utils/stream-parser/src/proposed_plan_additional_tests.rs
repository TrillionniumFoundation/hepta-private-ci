use crate::ProposedPlanParser;
use crate::ProposedPlanSegment;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use crate::extract_proposed_plan_text;
use crate::strip_proposed_plan_blocks;
use pretty_assertions::assert_eq;

fn chunk(
    visible_text: &str,
    extracted: Vec<ProposedPlanSegment>,
) -> StreamTextChunk<ProposedPlanSegment> {
    StreamTextChunk {
        visible_text: visible_text.to_owned(),
        extracted,
    }
}

#[test]
fn internal_frames_preserve_one_normal_segment_and_utf8() {
    let text = format!("{}🦀終", "x".repeat(/*n*/ 4095));
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        (parser.push_str(&text), parser.finish()),
        (
            chunk(&text, vec![ProposedPlanSegment::Normal(text.clone())]),
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn internal_frames_preserve_marker_and_delta_grouping() {
    let before = format!("{}\n", "n".repeat(/*n*/ 4093));
    let body = format!("{}\n", "b".repeat(/*n*/ 5000));
    let text = format!("{before}<proposed_plan>\n{body}</proposed_plan>\ntail");
    let visible = format!("{before}tail");
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        (parser.push_str(&text), parser.finish()),
        (
            chunk(
                &visible,
                vec![
                    ProposedPlanSegment::Normal(before),
                    ProposedPlanSegment::ProposedPlanStart,
                    ProposedPlanSegment::ProposedPlanDelta(body),
                    ProposedPlanSegment::ProposedPlanEnd,
                    ProposedPlanSegment::Normal("tail".to_owned()),
                ],
            ),
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn separate_public_calls_do_not_merge_normal_or_delta_segments() {
    let mut parser = ProposedPlanParser::new();
    let first = parser.push_str("left");
    let second = parser.push_str("right\n<proposed_plan>\n");
    let third = parser.push_str("one");
    let fourth = parser.push_str("two");
    let tail = parser.finish();
    assert_eq!(
        (first, second, third, fourth, tail),
        (
            chunk("left", vec![ProposedPlanSegment::Normal("left".to_owned())]),
            chunk(
                "right\n",
                vec![
                    ProposedPlanSegment::Normal("right\n".to_owned()),
                    ProposedPlanSegment::ProposedPlanStart,
                ],
            ),
            chunk(
                "",
                vec![ProposedPlanSegment::ProposedPlanDelta("one".to_owned())],
            ),
            chunk(
                "",
                vec![ProposedPlanSegment::ProposedPlanDelta("two".to_owned())],
            ),
            chunk("", vec![ProposedPlanSegment::ProposedPlanEnd]),
        )
    );
}

#[test]
fn empty_plan_barriers_keep_surrounding_normal_segments_separate() {
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        parser.push_str("before\n<proposed_plan>\n</proposed_plan>\nafter"),
        chunk(
            "before\nafter",
            vec![
                ProposedPlanSegment::Normal("before\n".to_owned()),
                ProposedPlanSegment::ProposedPlanStart,
                ProposedPlanSegment::ProposedPlanEnd,
                ProposedPlanSegment::Normal("after".to_owned()),
            ],
        )
    );
}

#[test]
fn all_pinned_unicode_whitespace_scalars_keep_original_line_rules() {
    let non_lf = [
        '\t', '\u{000b}', '\u{000c}', '\r', ' ', '\u{0085}', '\u{00a0}', '\u{1680}', '\u{2000}',
        '\u{2001}', '\u{2002}', '\u{2003}', '\u{2004}', '\u{2005}', '\u{2006}', '\u{2007}',
        '\u{2008}', '\u{2009}', '\u{200a}', '\u{2028}', '\u{2029}', '\u{202f}', '\u{205f}',
        '\u{3000}',
    ];
    for space in non_lf {
        let mut parser = ProposedPlanParser::new();
        let text = format!("{space}<proposed_plan>{space}\nbody\n</proposed_plan>\n");
        assert_eq!(
            (parser.push_str(&text), parser.finish()),
            (
                chunk(
                    "",
                    vec![
                        ProposedPlanSegment::ProposedPlanStart,
                        ProposedPlanSegment::ProposedPlanDelta("body\n".to_owned()),
                        ProposedPlanSegment::ProposedPlanEnd,
                    ],
                ),
                StreamTextChunk::default(),
            )
        );
    }
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        parser.push_str("\n<proposed_plan>\n\nbody\n</proposed_plan>\n"),
        chunk(
            "\n",
            vec![
                ProposedPlanSegment::Normal("\n".to_owned()),
                ProposedPlanSegment::ProposedPlanStart,
                ProposedPlanSegment::ProposedPlanDelta("\nbody\n".to_owned()),
                ProposedPlanSegment::ProposedPlanEnd,
            ],
        )
    );
}

#[test]
fn non_whitespace_prefixes_remain_literal_normal_text() {
    for prefix in ['\u{200b}', '\u{feff}', '\u{180e}', '\0'] {
        let text = format!("{prefix}<proposed_plan>\n");
        let mut parser = ProposedPlanParser::new();
        assert_eq!(
            (parser.push_str(&text), parser.finish()),
            (
                chunk(&text, vec![ProposedPlanSegment::Normal(text.clone())]),
                StreamTextChunk::default(),
            )
        );
    }
}

#[test]
fn whitespace_buffering_preserves_disproof_and_trailing_marker_recognition() {
    let mut parser = ProposedPlanParser::new();
    let leading = parser.push_str(" \t");
    let disproof = parser.push_str("x");
    let reset = parser.finish();
    let marker = parser.push_str("<proposed_plan>");
    let trailing = parser.push_str("\t \u{3000}");
    let line = parser.push_str("\nstep\n</proposed_plan>\n");
    assert_eq!(
        (
            leading,
            disproof,
            reset,
            marker,
            trailing,
            line,
            parser.finish()
        ),
        (
            StreamTextChunk::default(),
            chunk(" \tx", vec![ProposedPlanSegment::Normal(" \tx".to_owned())]),
            StreamTextChunk::default(),
            StreamTextChunk::default(),
            StreamTextChunk::default(),
            chunk(
                "",
                vec![
                    ProposedPlanSegment::ProposedPlanStart,
                    ProposedPlanSegment::ProposedPlanDelta("step\n".to_owned()),
                    ProposedPlanSegment::ProposedPlanEnd,
                ],
            ),
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn only_lf_ends_a_marker_line() {
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        parser.push_str("<proposed_plan>\rbody"),
        chunk(
            "<proposed_plan>\rbody",
            vec![ProposedPlanSegment::Normal(
                "<proposed_plan>\rbody".to_owned()
            )],
        )
    );
    assert_eq!(parser.finish(), StreamTextChunk::default());
    assert_eq!(
        parser.push_str("<proposed_plan>\r\nbody\r\n</proposed_plan>\r\n"),
        chunk(
            "",
            vec![
                ProposedPlanSegment::ProposedPlanStart,
                ProposedPlanSegment::ProposedPlanDelta("body\r\n".to_owned()),
                ProposedPlanSegment::ProposedPlanEnd,
            ],
        )
    );
}

#[test]
fn inactive_close_and_nested_open_wait_for_the_line_decision() {
    let mut parser = ProposedPlanParser::new();
    let close_prefix = parser.push_str("</proposed_plan>");
    let close_line = parser.push_str("\n");
    let start = parser.push_str("<proposed_plan>\n");
    let nested_prefix = parser.push_str("<proposed_plan>");
    let nested_line = parser.push_str("\nstep\n");
    let tail = parser.finish();
    assert_eq!(
        (
            close_prefix,
            close_line,
            start,
            nested_prefix,
            nested_line,
            tail
        ),
        (
            StreamTextChunk::default(),
            chunk(
                "</proposed_plan>\n",
                vec![ProposedPlanSegment::Normal("</proposed_plan>\n".to_owned())],
            ),
            chunk("", vec![ProposedPlanSegment::ProposedPlanStart]),
            StreamTextChunk::default(),
            chunk(
                "",
                vec![ProposedPlanSegment::ProposedPlanDelta(
                    "<proposed_plan>\nstep\n".to_owned(),
                )],
            ),
            chunk("", vec![ProposedPlanSegment::ProposedPlanEnd]),
        )
    );
}

#[test]
fn eof_recognizes_whitespace_wrapped_marker_and_resets_for_reuse() {
    let mut parser = ProposedPlanParser::new();
    let pending = parser.push_str(" \t<proposed_plan>\u{3000}");
    let eof = parser.finish();
    let second_eof = parser.finish();
    let reused = parser.push_str("again");
    assert_eq!(
        (pending, eof, second_eof, reused, parser.finish()),
        (
            StreamTextChunk::default(),
            chunk(
                "",
                vec![
                    ProposedPlanSegment::ProposedPlanStart,
                    ProposedPlanSegment::ProposedPlanEnd,
                ],
            ),
            StreamTextChunk::default(),
            chunk(
                "again",
                vec![ProposedPlanSegment::Normal("again".to_owned())]
            ),
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn empty_push_does_not_flush_an_unfinished_marker() {
    let mut parser = ProposedPlanParser::new();
    assert_eq!(
        (
            parser.push_str("<prop"),
            parser.push_str(""),
            parser.finish(),
            parser.finish(),
        ),
        (
            StreamTextChunk::default(),
            StreamTextChunk::default(),
            chunk(
                "<prop",
                vec![ProposedPlanSegment::Normal("<prop".to_owned())]
            ),
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn debug_preserves_nested_fields_and_does_not_consume_pending_input() {
    let mut parser = ProposedPlanParser::new();
    assert_eq!(parser.push_str("\t<prop"), StreamTextChunk::default());
    assert_eq!(
        format!("{parser:?}"),
        concat!(
            "ProposedPlanParser { parser: TaggedLineParser { specs: [TagSpec { ",
            "open: \"<proposed_plan>\", close: \"</proposed_plan>\", tag: ProposedPlan }], ",
            "active_tag: None, detect_tag: true, line_buffer: \"\\t<prop\" } }"
        )
    );
    assert_eq!(
        format!("{parser:#?}"),
        concat!(
            "ProposedPlanParser {\n",
            "    parser: TaggedLineParser {\n",
            "        specs: [\n",
            "            TagSpec {\n",
            "                open: \"<proposed_plan>\",\n",
            "                close: \"</proposed_plan>\",\n",
            "                tag: ProposedPlan,\n",
            "            },\n",
            "        ],\n",
            "        active_tag: None,\n",
            "        detect_tag: true,\n",
            "        line_buffer: \"\\t<prop\",\n",
            "    },\n",
            "}"
        )
    );
    assert_eq!(
        parser.push_str("osed_plan>\nbody"),
        chunk(
            "",
            vec![
                ProposedPlanSegment::ProposedPlanStart,
                ProposedPlanSegment::ProposedPlanDelta("body".to_owned()),
            ],
        )
    );
    assert_eq!(
        format!("{parser:?}"),
        concat!(
            "ProposedPlanParser { parser: TaggedLineParser { specs: [TagSpec { ",
            "open: \"<proposed_plan>\", close: \"</proposed_plan>\", tag: ProposedPlan }], ",
            "active_tag: Some(ProposedPlan), detect_tag: false, line_buffer: \"\" } }"
        )
    );
    assert_eq!(
        parser.finish(),
        chunk("", vec![ProposedPlanSegment::ProposedPlanEnd])
    );
}

#[test]
fn strip_and_extract_preserve_the_last_plan_and_literal_order() {
    let text = "before\n<proposed_plan>\nfirst\n</proposed_plan>\nmiddle\n<proposed_plan>\nlast";
    assert_eq!(
        (
            strip_proposed_plan_blocks(text),
            extract_proposed_plan_text(text)
        ),
        ("before\nmiddle\n".to_owned(), Some("last".to_owned()))
    );
}
