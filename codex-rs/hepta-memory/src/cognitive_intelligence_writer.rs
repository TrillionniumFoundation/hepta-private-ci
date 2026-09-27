// Keep the existing immutable KG writer, transaction boundaries and tests.
include!("cognitive_intelligence_writer_core.rs");

pub(crate) const ASSERTION_CONTRACT: &str = "structured_cognitive_propositions_v2";
pub(crate) const ASSERTED_PREDICATE_PREFIX: &str = "hepta_asserted_v2:";
pub(crate) const DENIED_PREDICATE_PREFIX: &str = "hepta_denied_v2:";

#[path = "cognitive_proposition_writer.rs"]
mod proposition_writer;
