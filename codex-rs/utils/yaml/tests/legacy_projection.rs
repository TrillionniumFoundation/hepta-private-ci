//! Golden compatibility cases obtained from the archived old/new parser run.
//! The legacy parser is deliberately absent from this crate's dependency graph.
use codex_utils_yaml::from_str;
use codex_utils_yaml::scalar_mapping;
use pretty_assertions::assert_eq;
use serde::Deserialize;

#[derive(Debug, Deserialize, PartialEq)]
struct Manifest {
    name: String,
    description: String,
}

#[test]
fn rejects_semantically_duplicate_scalar_and_composite_keys() {
    for input in [
        "true: a\nTrue: b\n",
        "null: a\n~: b\n",
        "1.0: a\n1.00: b\n",
        ".NaN: a\n.nan: b\n",
        "0: a\n-0: b\n",
        "0.0: a\n-0.0: b\n",
        "? [true, 1.0]\n: a\n? [True, 1.00]\n: b\n",
        "? {a: true, b: 1.0}\n: a\n? {b: 1.00, a: True}\n: b\n",
    ] {
        assert!(scalar_mapping(input).is_err(), "accepted duplicate keys: {input}");
    }
    assert_eq!(scalar_mapping("1: a\n1.0: b\n").unwrap(), Some(vec![]));
}

#[test]
fn preserves_scalar_spellings_verified_against_the_previous_parser() {
    for (input, expected) in [
        ("description: TrUe\n", "TrUe"),
        ("description: NuLl\n", "NuLl"),
        ("description: !!binary aGVsbG8=\n", "aGVsbG8="),
        ("description: !!float 1\n", "1.0"),
    ] {
        assert_eq!(
            scalar_mapping(input).unwrap(),
            Some(vec![("description".to_string(), Some(expected.to_string()))])
        );
    }
    for input in ["", "# comment\n", "---\n"] {
        assert_eq!(scalar_mapping(input).unwrap(), None);
    }
    assert!(scalar_mapping("description: 18446744073709551616\n").is_err());
    assert_eq!(
        from_str::<Manifest>("name: demo\ndescription: !!binary aGVsbG8=\n").unwrap(),
        Manifest { name: "demo".to_string(), description: "aGVsbG8=".to_string() }
    );
}

// Fixed outcomes from the archived 37-case old/new differential run.
enum Expected {
    Invalid,
    NonMapping,
    Mapping(&'static [(&'static str, Option<&'static str>)]),
}

#[test]
fn frozen_legacy_numeric_projection_boundaries() {
    let cases = [
        ("boolean-key-alias", "true: a\nTrue: b\n", Expected::Invalid),
        ("null-key-alias", "null: a\n~: b\n", Expected::Invalid),
        ("float-key-alias", "1.0: a\n1.00: b\n", Expected::Invalid),
        ("nan-key-alias", ".NaN: a\n.nan: b\n", Expected::Invalid),
        ("signed-zero-key", "0: a\n-0: b\n", Expected::Invalid),
        ("integer-and-float-key", "1: a\n1.0: b\n", Expected::Mapping(&[])),
        ("mixed-case-bool", "description: TrUe\n", Expected::Mapping(&[("description", Some("TrUe"))])),
        ("mixed-case-null", "description: NuLl\n", Expected::Mapping(&[("description", Some("NuLl"))])),
        ("sequence-key-alias", "? [true, 1.0]\n: a\n? [True, 1.00]\n: b\n", Expected::Invalid),
        ("mapping-key-alias", "? {a: true, b: 1.0}\n: a\n? {b: 1.00, a: True}\n: b\n", Expected::Invalid),
        ("empty", "", Expected::NonMapping),
        ("comments-only", "# comment\n", Expected::NonMapping),
        ("empty-document", "---\n", Expected::NonMapping),
        ("tagged-key", "!local description: hello\n", Expected::Mapping(&[("description", Some("hello"))])),
        ("different-tags", "!first description: first\n!second description: second\n", Expected::Mapping(&[("description", Some("first")), ("description", Some("second"))])),
        ("standard-binary", "description: !!binary aGVsbG8=\n", Expected::Mapping(&[("description", Some("aGVsbG8="))])),
        ("explicit-float", "description: !!float 1\n", Expected::Mapping(&[("description", Some("1.0"))])),
        ("large-integer", "description: 18446744073709551616\n", Expected::Invalid),
        ("merge-key", "base: &b {description: hello}\n<<: *b\nname: example\n", Expected::Mapping(&[("base", None), ("<<", None), ("name", Some("example"))])),
        ("uppercase-hex-prefix", "description: 0X10\n", Expected::Mapping(&[("description", Some("0X10"))])),
        ("uppercase-octal-prefix", "description: 0O10\n", Expected::Mapping(&[("description", Some("0O10"))])),
        ("uppercase-binary-prefix", "description: 0B10\n", Expected::Mapping(&[("description", Some("0B10"))])),
        ("hex-u64-overflow", "description: 0x10000000000000000\n", Expected::Invalid),
        ("octal-u64-overflow", "description: 0o2000000000000000000000\n", Expected::Invalid),
        ("binary-u64-overflow", "description: 0b10000000000000000000000000000000000000000000000000000000000000000\n", Expected::Invalid),
        ("negative-hex-i64-overflow", "description: -0x8000000000000001\n", Expected::Invalid),
        ("decimal-underscore", "description: 1_000\n", Expected::Mapping(&[("description", Some("1_000"))])),
        ("hex-underscore", "description: 0x1_0\n", Expected::Mapping(&[("description", Some("0x1_0"))])),
        ("float-overflow", "description: 1e999\n", Expected::Mapping(&[("description", Some("1e999"))])),
        ("decimal-u128-overflow", "description: 340282366920938463463374607431768211456\n", Expected::Mapping(&[("description", Some("3.402823669209385e38"))])),
        ("leading-zero-decimal", "description: 0123\n", Expected::Mapping(&[("description", Some("0123"))])),
        ("uppercase-prefix-key-distinct", "0X10: first\n16: second\n", Expected::Mapping(&[("0X10", Some("first"))])),
        ("underscored-key-distinct", "1_0: first\n10: second\n", Expected::Mapping(&[("1_0", Some("first"))])),
        ("u64-upper-bound", "description: 18446744073709551615\n", Expected::Mapping(&[("description", Some("18446744073709551615"))])),
        ("i64-lower-bound", "description: -9223372036854775808\n", Expected::Mapping(&[("description", Some("-9223372036854775808"))])),
        ("quoted-overflow", "description: '0x10000000000000000'\n", Expected::Mapping(&[("description", Some("0x10000000000000000"))])),
        ("mixed-case-infinity", "description: .iNf\n", Expected::Mapping(&[("description", Some(".iNf"))])),
    ];
    for (name, input, expected) in cases {
        let actual = scalar_mapping(input);
        match expected {
            Expected::Invalid => assert!(actual.is_err(), "accepted {name}: {actual:?}"),
            Expected::NonMapping => assert_eq!(actual.unwrap(), None, "case {name}"),
            Expected::Mapping(fields) => {
                let expected: Vec<_> = fields.iter().map(|(key, value)| {
                    (key.to_string(), value.map(str::to_string))
                }).collect();
                assert_eq!(actual.unwrap(), Some(expected), "case {name}");
            }
        }
    }
}
