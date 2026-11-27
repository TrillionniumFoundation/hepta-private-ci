use super::parse_frontmatter;
use pretty_assertions::assert_eq;

#[test]
fn subagent_frontmatter_preserves_key_and_scalar_semantics() {
    let (fields, error) = parse_frontmatter(
        "? [one, two]\n: ignored\n' name ': first\nname: second\ndescription: &description 1e999\ncopy: *description\nfloat: 1.0\nflag: true\ncustom: !custom value\n",
    );
    assert!(error.is_none());
    assert_eq!(
        fields
            .iter()
            .map(|(key, value)| (key.as_str(), value.as_scalar()))
            .collect::<Vec<_>>(),
        vec![
            ("copy", Some("1e999")),
            ("custom", None),
            ("description", Some("1e999")),
            ("flag", Some("true")),
            ("float", Some("1.0")),
            ("name", Some("second")),
        ]
    );
}

#[test]
fn subagent_frontmatter_rejects_duplicate_keys_and_multiple_documents() {
    for text in [
        "name: first\nname: second\n",
        "---\nname: first\n---\nname: second\n",
        "name: {nested: first, nested: second}\n",
    ] {
        let (fields, error) = parse_frontmatter(text);
        assert!(fields.is_empty());
        assert!(error.is_some());
    }
}
