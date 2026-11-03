#[test]
fn command_description_preserves_legacy_yaml_boundaries() {
    let cases = [
        ("plain", "description: hello"),
        ("quoted", "description: ' hello '"),
        ("boolean", "description: false"),
        ("integer", "description: 42"),
        ("yaml12-yes", "description: yes"),
        ("yaml12-no", "description: no"),
        ("upper-boolean", "description: TRUE"),
        ("zero-float", "description: -0.0"),
        ("exponent", "description: 1.2e-15"),
        ("float-integral", "description: 1.0"),
        ("float", "description: 1.25"),
        ("infinity", "description: .inf"),
        ("nan", "description: .nan"),
        ("null", "description: null"),
        ("sequence", "description: [one, two]"),
        ("mapping", "description: {a: b}"),
        ("multiline", "description: |\n  hello\n  world"),
        ("explicit-string", "description: !!str 42"),
        ("custom-tag", "description: !custom hello"),
        ("anchor", "description: &text hello\nother: *text"),
        ("alias", "other: &text hello\ndescription: *text"),
        ("merge-only", "defaults: &base {description: inherited}\n<<: *base"),
        ("merge-explicit", "defaults: &base {description: inherited}\n<<: *base\ndescription: explicit"),
        ("duplicate", "description: first\ndescription: second"),
        ("numeric-key", "42: other\ndescription: hello"),
        ("sequence-key", "? [one, two]\n: other\ndescription: hello"),
        ("key-whitespace", "' description ': first\ndescription: second"),
        ("bad-syntax", "description: ["),
        ("top-sequence", "- description: hello"),
        ("multiple-documents", "description: first\n---\ndescription: second"),
        ("empty", ""),
    ];
    let mut differences = Vec::new();
    for (label, source) in cases {
        let old = crate::baseline_command::parse_command_description(source);
        let new = crate::candidate_command::parse_command_description(source);
        println!("{label}: baseline={old:?}; candidate={new:?}");
        if old != new {
            differences.push((label, old, new));
        }
    }
    assert_eq!(differences, Vec::new());
}

#[test]
fn skill_frontmatter_preserves_legacy_yaml_boundaries() {
    let cases = [
        ("plain", "name: demo\ndescription: hello"),
        ("boolean", "name: demo\ndescription: false"),
        ("integer", "name: demo\ndescription: 42"),
        ("null-name", "name: null\ndescription: hello"),
        ("custom-tag", "name: demo\ndescription: !custom hello"),
        ("explicit-string", "name: demo\ndescription: !!str 42"),
        ("anchor", "name: demo\ndescription: &text hello\nother: *text"),
        ("alias", "name: demo\nother: &text hello\ndescription: *text"),
        ("merge-only", "defaults: &base {name: demo, description: inherited}\n<<: *base"),
        ("merge-explicit", "defaults: &base {name: ignored, description: inherited}\n<<: *base\nname: demo\ndescription: explicit"),
        ("duplicate", "name: demo\ndescription: first\ndescription: second"),
        ("numeric-key", "42: other\nname: demo\ndescription: hello"),
        ("sequence-key", "? [one, two]\n: other\nname: demo\ndescription: hello"),
        ("sequence-description", "name: demo\ndescription: [one, two]"),
        ("bad-syntax", "description: ["),
        ("repair", "name: demo\ndescription: Hello: world"),
        ("nested-metadata", "name: demo\ndescription: hello\nmetadata:\n  short-description: A short note"),
    ];
    let mut differences = Vec::new();
    for (label, body) in cases {
        let document = format!("---\n{body}\n---\nBody");
        let old = crate::baseline_parser::parse_skill_frontmatter_metadata(&document, || "fallback".to_owned())
            .map(|value| (value.name, value.description, value.short_description)).ok();
        let new = crate::candidate_parser::parse_skill_frontmatter_metadata(&document, || "fallback".to_owned())
            .map(|value| (value.name, value.description, value.short_description)).ok();
        println!("{label}: baseline={old:?}; candidate={new:?}");
        if old != new {
            differences.push((label, old, new));
        }
    }
    assert_eq!(differences, Vec::new());
}
