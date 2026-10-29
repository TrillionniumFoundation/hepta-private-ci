use super::parse_migration_frontmatter;
use pretty_assertions::assert_eq;

#[test]
fn preserves_yaml_scalars_aliases_and_source_order() -> Result<(), String> {
    let fields = parse_migration_frontmatter(
        "name: &name '  on  '\nalias: *name\nboolean: FALSE\ncount: 0x10\nfloat: 1.0\nlegacy: yes\ndescription: >-\n  Deploy safely\n  after review\n",
    )?;
    assert_eq!(
        fields,
        vec![
            ("name".to_string(), Some("on".to_string())),
            ("alias".to_string(), Some("on".to_string())),
            ("boolean".to_string(), Some("false".to_string())),
            ("count".to_string(), Some("16".to_string())),
            ("float".to_string(), Some("1.0".to_string())),
            ("legacy".to_string(), Some("yes".to_string())),
            (
                "description".to_string(),
                Some("Deploy safely after review".to_string())
            ),
        ]
    );
    Ok(())
}

#[test]
fn ignores_non_string_keys_and_keeps_unsupported_fields() -> Result<(), String> {
    let fields = parse_migration_frontmatter(
        "42: ignored\ntrue: ignored\n? [a, b]\n: ignored\nname: review\nnull_field: null\nlist: [a, b]\nnested: {key: value}\ntagged: !application text\nexplicit: !!str yes\ndescription: Review changes\n",
    )?;
    assert_eq!(
        fields,
        vec![
            ("name".to_string(), Some("review".to_string())),
            ("null_field".to_string(), None),
            ("list".to_string(), None),
            ("nested".to_string(), None),
            ("tagged".to_string(), None),
            ("explicit".to_string(), Some("yes".to_string())),
            (
                "description".to_string(),
                Some("Review changes".to_string())
            ),
        ]
    );
    Ok(())
}

#[test]
fn does_not_expand_merge_fields_or_collapse_trimmed_keys() -> Result<(), String> {
    let fields = parse_migration_frontmatter(
        "defaults: &defaults {description: inherited}\n<<: *defaults\n' description ': first\ndescription: second\n",
    )?;
    assert_eq!(
        fields,
        vec![
            ("defaults".to_string(), None),
            ("<<".to_string(), None),
            ("description".to_string(), Some("first".to_string())),
            ("description".to_string(), Some("second".to_string())),
        ]
    );
    Ok(())
}

#[test]
fn preserves_non_finite_scalars_without_json_null_conversion() -> Result<(), String> {
    assert_eq!(
        parse_migration_frontmatter("nan: .NaN\npositive: .Inf\nnegative: -.Inf\n")?,
        vec![
            ("nan".to_string(), Some(".nan".to_string())),
            ("positive".to_string(), Some(".inf".to_string())),
            ("negative".to_string(), Some("-.inf".to_string())),
        ]
    );
    Ok(())
}

#[test]
fn rejects_duplicate_keys_non_mappings_and_multiple_documents() {
    for document in [
        "description: first\ndescription: second\n",
        "[a, b]",
        "null",
        "description: first\n---\ndescription: second\n",
        "description: [unterminated",
    ] {
        assert!(parse_migration_frontmatter(document).is_err(), "{document}");
    }
}

#[test]
fn unwraps_mapping_and_key_tags_but_keeps_tagged_values_unsupported() -> Result<(), String> {
    assert_eq!(
        parse_migration_frontmatter(
            "!application {name: demo, !key description: content, plain: ! text, value: !application hidden}"
        )?,
        vec![
            ("name".to_string(), Some("demo".to_string())),
            ("description".to_string(), Some("content".to_string())),
            ("plain".to_string(), None),
            ("value".to_string(), None),
        ]
    );
    Ok(())
}

#[test]
fn preserves_legacy_numeric_spelling_and_alias_definitions() -> Result<(), String> {
    assert_eq!(
        parse_migration_frontmatter(
            "name: &name 01\nalias: *name\n01: numeric-looking key\nscientific: 1e20\nunderscore: 1_000\noverflow: 1e999\n",
        )?,
        vec![
            ("name".to_string(), Some("01".to_string())),
            ("alias".to_string(), Some("01".to_string())),
            ("01".to_string(), Some("numeric-looking key".to_string())),
            ("scientific".to_string(), Some("1e20".to_string())),
            ("underscore".to_string(), Some("1_000".to_string())),
            ("overflow".to_string(), Some("1e999".to_string())),
        ]
    );
    for source in [
        "description: 18446744073709551616",
        "description: -9223372036854775809",
        "description: 0x10000000000000000",
    ] {
        assert!(parse_migration_frontmatter(source).is_err(), "{source}");
    }
    Ok(())
}
