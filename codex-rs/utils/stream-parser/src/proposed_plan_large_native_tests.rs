//! These large public API witnesses are native-only. Corresponding small literal
//! cases run in both feature selections; they do not claim large default coverage.

use crate::ProposedPlanParser;
use crate::ProposedPlanSegment;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use pretty_assertions::assert_eq;

#[test]
fn native_retains_more_than_one_mib_of_leading_whitespace_until_disproof() {
    let leading = " ".repeat(/*n*/ 1_048_577);
    let expected = format!("{leading}x");
    let mut parser = ProposedPlanParser::new();
    let buffered = parser.push_str(&leading);
    let released = parser.push_str("x");
    assert_eq!(
        (buffered, released, parser.finish()),
        (
            StreamTextChunk::default(),
            StreamTextChunk {
                visible_text: expected.clone(),
                extracted: vec![ProposedPlanSegment::Normal(expected)],
            },
            StreamTextChunk::default(),
        )
    );
}

#[test]
fn native_recognizes_a_marker_after_more_than_one_mib_of_trailing_whitespace() {
    let trailing = "\t".repeat(/*n*/ 1_048_577);
    let mut parser = ProposedPlanParser::new();
    let marker = parser.push_str("<proposed_plan>");
    let buffered = parser.push_str(&trailing);
    let released = parser.push_str("\nstep\n</proposed_plan>\n");
    assert_eq!(
        (marker, buffered, released, parser.finish()),
        (
            StreamTextChunk::default(),
            StreamTextChunk::default(),
            StreamTextChunk {
                visible_text: String::new(),
                extracted: vec![
                    ProposedPlanSegment::ProposedPlanStart,
                    ProposedPlanSegment::ProposedPlanDelta("step\n".to_owned()),
                    ProposedPlanSegment::ProposedPlanEnd,
                ],
            },
            StreamTextChunk::default(),
        )
    );
}
