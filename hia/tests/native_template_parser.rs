//! Differential tests link the complete default and native production crates.

use std::error::Error;

fn compare_parse(source: &str) {
    let expected = template_reference::Template::parse(source);
    let actual = template_native::Template::parse(source);
    assert_eq!(format!("{actual:?}"), format!("{expected:?}"), "{source:?}");
    match (expected, actual) {
        (Ok(expected), Ok(actual)) => {
            assert_eq!(actual.placeholders().len(), expected.placeholders().len());
            assert_eq!(
                actual.placeholders().collect::<Vec<_>>(),
                expected.placeholders().collect::<Vec<_>>()
            );
            assert_eq!(actual, actual.clone());
        }
        (Err(expected), Err(actual)) => assert_eq!(actual.to_string(), expected.to_string()),
        _ => unreachable!("parse results already compared"),
    }
}

fn compare_render(source: &str, variables: &[(String, String)]) {
    let expected = template_reference::render(source, variables.iter().cloned());
    let actual = template_native::render(source, variables.iter().cloned());
    assert_eq!(format!("{actual:?}"), format!("{expected:?}"));
    if let (Err(expected), Err(actual)) = (expected, actual) {
        assert_eq!(actual.to_string(), expected.to_string());
        assert_eq!(
            actual.source().map(ToString::to_string),
            expected.source().map(ToString::to_string)
        );
    }
}

#[test]
fn all_unicode_scalars_follow_the_original_trim_contract() {
    let mut cases = 0;
    for value in 0..=0x10ffff {
        let Some(character) = char::from_u32(value) else {
            continue;
        };
        for name in [character.to_string(), format!("{character}name{character}")] {
            compare_parse(&format!("{{{{{name}}}}}"));
            cases += 1;
        }
    }
    println!("parse_cases={cases}");
}

#[test]
fn exhaustive_brace_sequences_preserve_error_precedence_and_escapes() {
    let mut cases = 0;
    for length in 0..=10 {
        for mut value in 0..3_usize.pow(length) {
            let mut source = String::new();
            for _ in 0..length {
                source.push(['{', '}', 'x'][value % 3]);
                value /= 3;
            }
            compare_parse(&source);
            cases += 1;
        }
    }
    println!("parse_cases={cases}");
}

#[test]
fn unicode_offsets_and_every_delimiter_position_across_windows() {
    let bodies = [
        "{{name}}",
        "{{{{",
        "}}}}",
        "{{{{{{name}}}}}}",
        "{{a{{b}}",
        "{{}}",
        "{{ \u{3000}\u{85} }}",
        "{{ x\u{200a} }}",
        "{{\u{200b}}}",
        "{{open",
        "}}",
        "{",
        "}",
        "{{x}y}}",
        "{{{x}}}",
        "{{ x }}{{ x }}",
        "{{😀𐀀}}",
    ];
    let mut cases = 0;
    for boundary in [4096_usize, 8192, 12288] {
        for offset in boundary - 8..=boundary + 8 {
            for body in bodies {
                let source = format!("é{}{}", "x".repeat(offset - 2), body);
                compare_parse(&source);
                cases += 1;
            }
            for scalar in ["é", "中", "😀", "\u{85}", "\u{3000}", "\u{10ffff}"] {
                for source in [
                    format!("{}{scalar}end", "x".repeat(offset)),
                    format!("{{{{{}{scalar} }}}}", " ".repeat(offset - 2)),
                    format!("{{{{{}{scalar} }}}}", "x".repeat(offset - 2)),
                ] {
                    compare_parse(&source);
                    cases += 1;
                }
            }
        }
    }
    println!("parse_cases={cases}");
}

#[test]
fn arbitrary_length_literals_names_and_escapes() {
    let large_name = format!("{}😀", "n".repeat(2 * 1024 * 1024));
    let cases = [
        "é😀x".repeat(400_000),
        format!("{{{{ \u{3000}{large_name}\u{200a} }}}}"),
        format!("{{{{{}", " ".repeat(2 * 1024 * 1024)),
        format!("{}{{{{ }}}}", "x".repeat(2 * 1024 * 1024)),
        "{{{{}}}}".repeat(270_000),
        format!("{{{{{large_name}}}}}{{{{{large_name}}}}}"),
    ];
    for source in &cases {
        compare_parse(source);
    }
    let source = format!("start{{{{{large_name}}}}}end");
    compare_render(&source, &[(large_name, "{{not reparsed}}😀".into())]);
    println!("parse_cases={} render_cases=1", cases.len());
}

#[test]
fn duplicate_missing_extra_sorting_and_verbatim_values() {
    let sources = [
        "",
        "plain",
        "{{z}}{{ a }}{{z}}",
        "{{é}}{{e\u{301}}}",
        "{{ x y }}",
        "{{\0}}",
        "{{{{x}}}}",
        "{{x}}-{{x}}",
        "{{bad",
    ];
    let mut cases = 0;
    for source in sources {
        let names = template_reference::Template::parse(source)
            .map(|value| value.placeholders().map(str::to_owned).collect::<Vec<_>>())
            .unwrap_or_default();
        let complete: Vec<_> = names
            .iter()
            .map(|name| (name.clone(), "{{value}}\0😀".into()))
            .collect();
        for values in [
            Vec::new(),
            complete.clone(),
            complete.iter().cloned().rev().collect(),
            vec![("z".into(), "1".into()), ("z".into(), "2".into())],
            vec![("b".into(), "1".into()), ("a".into(), "2".into())],
            vec![(" a ".into(), "value".into())],
            complete
                .iter()
                .cloned()
                .chain([("extra".into(), "v".into())])
                .collect(),
            complete
                .iter()
                .cloned()
                .chain(complete.iter().cloned())
                .collect(),
        ] {
            compare_render(source, &values);
            cases += 1;
        }
    }
    println!("render_cases={cases}");
}

#[test]
fn malformed_parse_and_duplicate_input_preserve_iterator_effects() {
    use std::cell::Cell;
    for source in ["{{bad", "{{x{{y}}", "{{ }}", "}}", "{{x}}"] {
        let old_count = Cell::new(0);
        let new_count = Cell::new(0);
        let pairs = [("x", "one"), ("x", "two"), ("never", "three")];
        let old = template_reference::render(
            source,
            pairs
                .into_iter()
                .inspect(|_| old_count.set(old_count.get() + 1)),
        );
        let new = template_native::render(
            source,
            pairs
                .into_iter()
                .inspect(|_| new_count.set(new_count.get() + 1)),
        );
        assert_eq!(format!("{new:?}"), format!("{old:?}"));
        assert_eq!(new_count.get(), old_count.get());
    }
    println!("render_cases=5");
}

#[test]
fn seeded_mixed_syntax_and_unicode() {
    let parts = [
        "{", "}", "{{", "}}", "{{{{", "}}}}", "x", " ", "\n", "\0", "é", "中", "😀", "\u{3000}",
        "\u{200b}",
    ];
    let mut seed = 0xa90d_4421_79fa_7e03_u64;
    for _ in 0..20_000 {
        let mut source = String::new();
        for _ in 0..32 {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            source.push_str(parts[seed as usize % parts.len()]);
        }
        compare_parse(&source);
    }
    println!("parse_cases=20000");
}
