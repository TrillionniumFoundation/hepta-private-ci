use super::Value;
use super::from_slice;
use super::from_str;
use super::options;
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Debug, Deserialize, PartialEq)]
struct Strings {
    description: Option<String>,
    path: String,
}

#[test]
fn metadata_strings_keep_scalar_text_and_explicit_tagged_null() {
    assert_eq!(
        from_str::<Strings>("description: !str null\npath: !!int hello").unwrap(),
        Strings {
            description: Some("null".to_owned()),
            path: "hello".to_owned(),
        }
    );
    assert_eq!(
        from_str::<Strings>("description: null\npath: 007").unwrap(),
        Strings {
            description: None,
            path: "007".to_owned(),
        }
    );
}

#[test]
fn port_and_manifest_version_retain_integer_style_and_range_rules() {
    for text in ["'7'", "\"7\"", "!!int '7'", "007", "1.0", "-1"] {
        assert!(from_str::<u16>(text).is_err(), "{text}");
        assert!(from_str::<u32>(text).is_err(), "{text}");
    }
    for text in ["7", "+7", "0x7", "0o7", "0b111", "!int 7"] {
        assert_eq!(from_str::<u16>(text).unwrap(), 7, "{text}");
        assert_eq!(from_str::<u32>(text).unwrap(), 7, "{text}");
    }
    assert_eq!(from_str::<u16>("65535").unwrap(), u16::MAX);
    assert!(from_str::<u16>("65536").is_err());
    assert_eq!(from_str::<u32>("4294967295").unwrap(), u32::MAX);
    assert!(from_str::<u32>("4294967296").is_err());
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
enum Product {
    #[serde(alias = "CODEX")]
    Codex,
    #[serde(alias = "CHATGPT")]
    Chatgpt,
}

#[test]
fn product_enum_preserves_scalar_and_tagged_unit_rules() {
    for text in ["codex", "CODEX", "!!int codex", "!codex null", "!CODEX ~"] {
        assert_eq!(from_str::<Product>(text).unwrap(), Product::Codex);
    }
    for text in [
        "{codex: null}",
        "! codex",
        "!codex true",
        "!codex ''",
        "!codex []",
    ] {
        assert!(from_str::<Product>(text).is_err(), "{text}");
    }
}

#[test]
fn dynamic_numbers_keep_legacy_categories_and_overflow_behavior() {
    assert_eq!(from_str::<Value>("007").unwrap().as_str(), Some("007"));
    assert_eq!(from_str::<Value>("1e999").unwrap().as_str(), Some("1e999"));
    assert!(from_str::<Value>("18446744073709551616").is_err());
    assert!(from_str::<Value>("!!float 1e999").is_err());
    assert!(matches!(
        from_str::<Value>(".nan").unwrap(),
        Value::Number(_)
    ));
}

#[test]
fn mappings_keep_key_equivalence_and_the_target_duplicate_policy() {
    for text in [
        ".nan: first\n.NaN: second",
        "0.0: first\n-0.0: second",
        "? {a: 1, b: 2}\n: first\n? {b: 2, a: 1}\n: second",
        "!custom 1: first\n!<!!custom> 1: second",
    ] {
        assert!(from_str::<Value>(text).is_err(), "{text}");
    }
    let map = from_str::<Value>("1: integer\n1.0: float").unwrap();
    assert_eq!(map.as_mapping().unwrap().len(), 2);
    assert_eq!(
        from_str::<BTreeMap<String, String>>("key: first\nkey: second").unwrap(),
        BTreeMap::from([("key".to_owned(), "second".to_owned())])
    );
}

#[test]
fn aliases_preserve_local_tags_and_values() {
    let value = from_str::<Value>("seed: &a !int '001'\ncopy: *a").unwrap();
    let map = value.as_mapping().unwrap();
    assert_eq!(
        map.get(&Value::String("seed".to_owned())),
        map.get(&Value::String("copy".to_owned()))
    );
    let seed = map.get(&Value::String("seed".to_owned())).unwrap();
    assert_eq!(seed.as_str(), Some("001"));
    assert!(matches!(seed, Value::Tagged(_)));
}

#[test]
fn empty_documents_and_tagged_empty_nodes_keep_their_distinction() {
    assert!(from_str::<String>("").is_err());
    assert_eq!(from_str::<String>("---").unwrap(), "");
    assert_eq!(from_str::<String>("~").unwrap(), "~");
    assert_eq!(from_str::<String>("--- !!str").unwrap(), "");
    assert!(from_str::<Vec<String>>("---").unwrap().is_empty());
    assert!(
        from_str::<BTreeMap<String, String>>("---")
            .unwrap()
            .is_empty()
    );
    assert!(matches!(
        from_str::<Value>("--- !local").unwrap(),
        Value::Tagged(_)
    ));
}

#[test]
fn depth_budget_returns_errors_before_stack_exhaustion() {
    std::thread::Builder::new()
        .stack_size(2 * 1024 * 1024)
        .spawn(|| {
            for (open, close) in [
                ("[", "]"),
                ("!local [", "]"),
                ("{x: ", "}"),
                ("!local {x: ", "}"),
            ] {
                let allowed = format!("{}x{}", open.repeat(64), close.repeat(64));
                let denied = format!("{}x{}", open.repeat(65), close.repeat(65));
                from_str::<Value>(&allowed).unwrap();
                let error = from_str::<Value>(&denied).unwrap_err();
                assert!(error.to_string().contains("depth"), "{error}");
            }
        })
        .unwrap()
        .join()
        .unwrap();
}

#[test]
fn compatibility_dispatch_keeps_event_scalar_and_alias_budgets() {
    let mut limited = options();
    limited.budget.as_mut().unwrap().max_events = 2;
    assert!(serde_saphyr::from_str_with_options::<Value>("[a,b,c]", limited).is_err());
    let mut limited = options();
    limited.budget.as_mut().unwrap().max_total_scalar_bytes = 0;
    assert!(serde_saphyr::from_str_with_options::<String>("---", limited).is_err());
    let mut limited = options();
    limited.alias_limits.max_total_replayed_events = 2;
    assert!(
        serde_saphyr::from_str_with_options::<Value>(
            "a: &a !local x\nb: *a\nc: *a\nd: *a",
            limited,
        )
        .is_err()
    );
    assert!(from_str::<Value>("a: &a [*a]").is_err());
    assert!(from_str::<Value>("a: *missing").is_err());
}

#[test]
fn malformed_encoding_and_multiple_documents_remain_errors() {
    assert!(from_slice::<Value>(&[0xff, 0xff, 0xff]).is_err());
    assert!(from_str::<Value>("a: 1\n---\nb: 2").is_err());
    assert!(from_str::<Value>("[").is_err());
}
