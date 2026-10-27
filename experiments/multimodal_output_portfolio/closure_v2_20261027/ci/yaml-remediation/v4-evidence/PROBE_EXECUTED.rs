use codex_utils_yaml::scalar_mapping;
use legacy_yaml::Value;

fn previous(input: &str) -> Result<Option<Vec<(String, Option<String>)>>, ()> {
    let parsed: Value = legacy_yaml::from_str(input).map_err(|_| ())?;
    let Some(mapping) = parsed.as_mapping() else { return Ok(None) };
    Ok(Some(mapping.iter().filter_map(|(key, value)| {
        let key = key.as_str()?.to_string();
        let text = match value {
            Value::String(s) => Some(s.trim().to_string()),
            Value::Bool(b) => Some(b.to_string()),
            Value::Number(n) => Some(n.to_string()),
            Value::Null | Value::Sequence(_) | Value::Mapping(_) | Value::Tagged(_) => None,
        };
        Some((key, text))
    }).collect()))
}

#[test]
fn legacy_parser_v4_numeric_boundaries() {
    let cases = [
        ("boolean-key-alias", "true: a\nTrue: b\n"),
        ("null-key-alias", "null: a\n~: b\n"),
        ("float-key-alias", "1.0: a\n1.00: b\n"),
        ("nan-key-alias", ".NaN: a\n.nan: b\n"),
        ("signed-zero-key", "0: a\n-0: b\n"),
        ("integer-and-float-key", "1: a\n1.0: b\n"),
        ("mixed-case-bool", "description: TrUe\n"),
        ("mixed-case-null", "description: NuLl\n"),
        ("sequence-key-alias", "? [true, 1.0]\n: a\n? [True, 1.00]\n: b\n"),
        ("mapping-key-alias", "? {a: true, b: 1.0}\n: a\n? {b: 1.00, a: True}\n: b\n"),
        ("empty", ""),
        ("comments-only", "# comment\n"),
        ("empty-document", "---\n"),
        ("tagged-key", "!local description: hello\n"),
        ("different-tags", "!first description: first\n!second description: second\n"),
        ("standard-binary", "description: !!binary aGVsbG8=\n"),
        ("explicit-float", "description: !!float 1\n"),
        ("large-integer", "description: 18446744073709551616\n"),
        ("merge-key", "base: &b {description: hello}\n<<: *b\nname: example\n"),
        ("uppercase-hex-prefix", "description: 0X10\n"),
        ("uppercase-octal-prefix", "description: 0O10\n"),
        ("uppercase-binary-prefix", "description: 0B10\n"),
        ("hex-u64-overflow", "description: 0x10000000000000000\n"),
        ("octal-u64-overflow", "description: 0o2000000000000000000000\n"),
        ("binary-u64-overflow", "description: 0b10000000000000000000000000000000000000000000000000000000000000000\n"),
        ("negative-hex-i64-overflow", "description: -0x8000000000000001\n"),
        ("decimal-underscore", "description: 1_000\n"),
        ("hex-underscore", "description: 0x1_0\n"),
        ("float-overflow", "description: 1e999\n"),
        ("decimal-u128-overflow", "description: 340282366920938463463374607431768211456\n"),
        ("leading-zero-decimal", "description: 0123\n"),
        ("uppercase-prefix-key-distinct", "0X10: first\n16: second\n"),
        ("underscored-key-distinct", "1_0: first\n10: second\n"),
        ("u64-upper-bound", "description: 18446744073709551615\n"),
        ("i64-lower-bound", "description: -9223372036854775808\n"),
        ("quoted-overflow", "description: '0x10000000000000000'\n"),
        ("mixed-case-infinity", "description: .iNf\n"),
    ];
    let mut mismatches = Vec::new();
    for (name, input) in cases {
        let expected = previous(input);
        let actual = scalar_mapping(input).map_err(|_| ());
        println!("{name}: old={expected:?}; candidate={actual:?}");
        if expected != actual { mismatches.push(name); }
    }
    assert!(mismatches.is_empty(), "compatibility differences: {mismatches:?}");
}
