//! Materialize HIA-selected values while preserving generic iterator effects.
//!
//! Key bytes live once in an append-only arena. HIA's shared AVL index owns
//! comparisons and ordering; HIA's render machine owns error precedence and
//! segment progression. Rust only stores strings/ranges and routes typed replies.

use super::Segment;
use super::Template;
use super::TemplateRenderError;
use super::hia_native_index::Index;
use super::hia_render_abi::Action;
use super::hia_render_abi::Control;
use super::hia_render_abi::ErrorKind;
use super::hia_render_abi::Machine;
use super::hia_render_abi::NativeError;
use std::ops::Range;

struct Variables {
    keys: Vec<u8>,
    ranges: Vec<Range<usize>>,
    values: Vec<String>,
}

impl Variables {
    fn name(&self, id: usize) -> &str {
        let range = indexed(&self.ranges, id);
        let Some(bytes) = self.keys.get(range.clone()) else {
            panic!("invalid HIA variable name range");
        };
        std::str::from_utf8(bytes).unwrap_or_else(|_| panic!("invalid HIA variable name encoding"))
    }
}

pub(super) fn render<I, K, V>(template: &Template, input: I) -> Result<String, TemplateRenderError>
where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<str>,
    V: AsRef<str>,
{
    let mut machine = Machine::new();
    let mut index = Index::new();
    let placeholders: Vec<_> = template.placeholders().collect();
    let mut variables = Variables {
        keys: Vec::new(),
        ranges: Vec::new(),
        values: Vec::new(),
    };
    for (name, value) in input {
        // Preserve K::as_ref before V::as_ref, including the duplicate item's
        // value, and finish this item before asking the iterator for its next.
        let name = name.as_ref().to_string();
        let value = value.as_ref().to_string();
        let begin = variables.keys.len();
        variables.keys.extend_from_slice(name.as_bytes());
        let end = variables.keys.len();
        let insertion = index.insert_range(&variables.keys, begin, end);
        let action = machine
            .control(Control::Variable(insertion))
            .map_err(|error| convert_error(error, &variables, &placeholders, template))?;
        let Action::Accepted { index } = action else {
            panic!("unexpected HIA renderer action during ingestion");
        };
        assert_eq!(index, variables.values.len(), "invalid HIA variable slot");
        variables.ranges.push(begin..end);
        variables.values.push(value);
    }
    let mut rendered = String::new();
    let mut action = machine.control(Control::Finish {
        placeholders: placeholders.len(),
        segments: template.segments.len(),
    });
    loop {
        action = match action
            .map_err(|error| convert_error(error, &variables, &placeholders, template))?
        {
            Action::Placeholder { index: placeholder } => {
                let found =
                    index.find_and_mark(&variables.keys, indexed(&placeholders, placeholder));
                machine.control(Control::Placeholder(found))
            }
            Action::Unused => machine.control(Control::Extra(index.first_unused())),
            Action::Segment { index: segment } => match indexed(&template.segments, segment) {
                Segment::Literal(_) => machine.control(Control::Literal),
                Segment::Placeholder(name) => {
                    let found = index.find(&variables.keys, name);
                    machine.control(Control::Value(found))
                }
            },
            Action::AppendLiteral { segment, following } => {
                let Segment::Literal(value) = indexed(&template.segments, segment) else {
                    panic!("invalid HIA literal request");
                };
                rendered.push_str(value);
                Ok(following.action())
            }
            Action::AppendValue {
                segment,
                variable,
                following,
            } => {
                assert!(matches!(
                    indexed(&template.segments, segment),
                    Segment::Placeholder(_)
                ));
                rendered.push_str(indexed(&variables.values, variable));
                Ok(following.action())
            }
            Action::Done => return Ok(rendered),
            Action::Accepted { .. } => panic!("unexpected HIA variable insertion during rendering"),
        };
    }
}

fn indexed<T>(values: &[T], index: usize) -> &T {
    let Some(value) = values.get(index) else {
        panic!("invalid HIA template result index");
    };
    value
}

fn convert_error(
    error: NativeError,
    variables: &Variables,
    placeholders: &[&str],
    template: &Template,
) -> TemplateRenderError {
    match error.kind {
        ErrorKind::Duplicate => TemplateRenderError::DuplicateValue {
            name: variables.name(error.index).to_string(),
        },
        ErrorKind::Missing => TemplateRenderError::MissingValue {
            name: indexed(placeholders, error.index).to_string(),
        },
        ErrorKind::Extra => TemplateRenderError::ExtraValue {
            name: variables.name(error.index).to_string(),
        },
        ErrorKind::MissingSegment => {
            let Segment::Placeholder(name) = indexed(&template.segments, error.index) else {
                panic!("invalid HIA template error index");
            };
            TemplateRenderError::MissingValue { name: name.clone() }
        }
    }
}
