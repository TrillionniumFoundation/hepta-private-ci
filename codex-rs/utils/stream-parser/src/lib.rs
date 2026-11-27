mod assistant_text;
mod citation;
#[cfg(feature = "hia-native")]
mod hia_native_citation_stream_parser;
#[cfg(feature = "hia-native")]
mod hia_native_citation_stream_parser_wire;
#[cfg(feature = "hia-native")]
mod hia_native_utf8_stream;
mod inline_hidden_tag;
mod proposed_plan;
mod stream_text;
mod tagged_line_parser;
mod utf8_stream;
mod utf8_validation;

#[cfg(test)]
#[path = "citation_additional_tests.rs"]
mod citation_additional_tests;

pub use assistant_text::AssistantTextChunk;
pub use assistant_text::AssistantTextStreamParser;
pub use citation::CitationStreamParser;
pub use citation::strip_citations;
pub use inline_hidden_tag::ExtractedInlineTag;
pub use inline_hidden_tag::InlineHiddenTagParser;
pub use inline_hidden_tag::InlineTagSpec;
pub use proposed_plan::ProposedPlanParser;
pub use proposed_plan::ProposedPlanSegment;
pub use proposed_plan::extract_proposed_plan_text;
pub use proposed_plan::strip_proposed_plan_blocks;
pub use stream_text::StreamTextChunk;
pub use stream_text::StreamTextParser;
pub use utf8_stream::Utf8StreamParser;
pub use utf8_stream::Utf8StreamParserError;
pub use utf8_validation::Utf8ValidationError;
pub use utf8_validation::validate_utf8;
