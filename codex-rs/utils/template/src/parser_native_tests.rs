use super::Segment;
use super::Template;
use super::TemplateParseError;
use super::TemplateRenderError;
use pretty_assertions::assert_eq;

#[test]
fn escaped_and_borrowed_literal_chunks_merge_into_the_original_representation() {
    let prefix = "é".repeat(4097);
    let source = format!("{prefix}{{{{{{{{literal}}}}}}}}end");
    let parsed = Template::parse(&source).unwrap();
    assert_eq!(
        parsed.segments,
        vec![Segment::Literal(format!("{prefix}{{{{literal}}}}end"))]
    );
}

#[test]
fn long_names_and_repeated_placeholders_preserve_sorting_and_rendering() {
    let name = format!("{}😀", "n".repeat(2 * 1024 * 1024));
    let source = format!("{{{{z}}}}/{{{{\u{3000}{name}\u{200a}}}}}/{{{{{name}}}}}");
    let parsed = Template::parse(&source).unwrap();
    assert_eq!(
        parsed.placeholders().collect::<Vec<_>>(),
        vec![name.as_str(), "z"]
    );
    assert_eq!(
        parsed.render([("z", "last"), (name.as_str(), "{{verbatim}}😀")]),
        Ok("last/{{verbatim}}😀/{{verbatim}}😀".into())
    );
}

#[test]
fn delimiter_and_utf8_boundaries_keep_byte_offsets_and_error_precedence() {
    for offset in 4091..=4101 {
        let prefix = format!("é{}", "x".repeat(offset - 2));
        for (suffix, expected) in [
            (
                "{{ \u{3000} }}",
                TemplateParseError::EmptyPlaceholder { start: offset },
            ),
            (
                "{{😀{{nested}}",
                TemplateParseError::NestedPlaceholder { start: offset },
            ),
            (
                "{{😀",
                TemplateParseError::UnterminatedPlaceholder { start: offset },
            ),
            (
                "}}",
                TemplateParseError::UnmatchedClosingDelimiter { start: offset },
            ),
        ] {
            assert_eq!(Template::parse(&format!("{prefix}{suffix}")), Err(expected));
        }
    }
}

#[test]
fn parsing_uses_unicode_white_space_without_normalizing_names() {
    let parsed = Template::parse("{{\u{85}é\u{3000}}}{{e\u{301}}}{{\u{200b}}}{{\0}}").unwrap();
    assert_eq!(
        parsed.placeholders().collect::<Vec<_>>(),
        vec!["\0", "e\u{301}", "é", "\u{200b}"]
    );
}

#[test]
fn render_error_order_remains_duplicate_then_missing_then_extra() {
    let parsed = Template::parse("{{z}} {{a}} {{a}}").unwrap();
    assert_eq!(
        parsed.render([("extra", "x"), ("extra", "y")]),
        Err(TemplateRenderError::DuplicateValue {
            name: "extra".into()
        })
    );
    assert_eq!(
        parsed.render([("extra", "x")]),
        Err(TemplateRenderError::MissingValue { name: "a".into() })
    );
    assert_eq!(
        parsed.render([("z", "z"), ("a", "a"), ("y", "y"), ("b", "b")]),
        Err(TemplateRenderError::ExtraValue { name: "b".into() })
    );
}
