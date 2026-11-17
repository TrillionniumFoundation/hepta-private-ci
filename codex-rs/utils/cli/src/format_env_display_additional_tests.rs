use crate::format_env_display;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::collections::HashMap;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;

#[test]
fn empty_names_and_duplicate_variables_are_not_removed() {
    let env = HashMap::from([
        (String::new(), "hidden-empty-value".to_string()),
        ("A".to_string(), "hidden-a-value".to_string()),
    ]);
    assert_eq!(
        format_env_display(Some(&env), &["", "A", "A"]),
        "=*****, A=*****, =*****, A=*****, A=*****"
    );
}

#[test]
fn keys_use_utf8_byte_order_without_normalizing_or_escaping() {
    let env = HashMap::from([
        ("🦀".to_string(), "crab".to_string()),
        ("é".to_string(), "composed".to_string()),
        ("e\u{301}".to_string(), "decomposed".to_string()),
        ("中".to_string(), "ideograph".to_string()),
        ("a".to_string(), "lower".to_string()),
        ("A".to_string(), "upper".to_string()),
        ("\0".to_string(), "nul".to_string()),
    ]);
    assert_eq!(
        format_env_display(Some(&env), &["x,=\n", ""]),
        "\0=*****, A=*****, a=*****, e\u{301}=*****, é=*****, 中=*****, 🦀=*****, x,=\n=*****, =*****"
    );
}

#[test]
fn map_insertion_order_does_not_change_the_complete_display() {
    for entries in [
        [("b", "one"), ("aa", "two"), ("a", "three")],
        [("a", "four"), ("b", "five"), ("aa", "six")],
    ] {
        let env: HashMap<String, String> = entries
            .into_iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect();
        assert_eq!(
            format_env_display(Some(&env), &["z", "b"]),
            "a=*****, aa=*****, b=*****, z=*****, b=*****"
        );
    }
}

#[test]
fn comparisons_and_utf8_output_cross_the_fragment_boundary() {
    let prefix = "x".repeat(/*n*/ 4095);
    let lower = format!("{prefix}éA");
    let higher = format!("{prefix}éB");
    let env = HashMap::from([
        (higher.clone(), "hidden-high".to_string()),
        (lower.clone(), "hidden-low".to_string()),
    ]);
    assert_eq!(
        format_env_display(Some(&env), &["中"]),
        format!("{lower}=*****, {higher}=*****, 中=*****")
    );
}

#[test]
fn a_single_key_larger_than_one_borrowed_frame_is_complete() {
    let key = "é".repeat(/*n*/ 524_289);
    assert!(key.len() > 1_048_576);
    let env = HashMap::from([(key.clone(), "hidden-value".to_string())]);
    assert_eq!(
        format_env_display(Some(&env), &[] as &[String]),
        format!("{key}=*****")
    );
}

#[test]
fn sorting_long_keys_reads_the_entire_shared_prefix() {
    let prefix = "x".repeat(/*n*/ 1_048_577);
    assert!(prefix.len() > 1_048_576);
    let lower = format!("{prefix}A");
    let higher = format!("{prefix}B");
    let env = HashMap::from([
        (higher.clone(), "hidden-high".to_string()),
        (lower.clone(), "hidden-low".to_string()),
    ]);
    assert_eq!(
        format_env_display(Some(&env), &[] as &[String]),
        format!("{lower}=*****, {higher}=*****")
    );
}

#[test]
fn complete_joined_output_is_not_limited_to_one_borrowed_frame() {
    let first = "x".repeat(/*n*/ 524_288);
    let second = "y".repeat(/*n*/ 524_288);
    let expected = format!("{first}=*****, {second}=*****");
    assert!(expected.len() > 1_048_576);
    assert_eq!(format_env_display(/*env*/ None, &[first, second]), expected);
}

struct Observed<'a> {
    name: &'a str,
    value: &'a str,
    calls: &'a RefCell<Vec<&'a str>>,
    stop: bool,
}

impl AsRef<str> for Observed<'_> {
    fn as_ref(&self) -> &str {
        self.calls.borrow_mut().push(self.name);
        assert!(!self.stop, "controlled AsRef stop");
        self.value
    }
}

#[test]
fn variables_call_as_ref_once_each_in_original_slice_order() {
    let calls = RefCell::new(Vec::new());
    let variables = [
        Observed {
            name: "first",
            value: "A",
            calls: &calls,
            stop: false,
        },
        Observed {
            name: "second",
            value: "A",
            calls: &calls,
            stop: false,
        },
        Observed {
            name: "third",
            value: "",
            calls: &calls,
            stop: false,
        },
    ];
    let env = HashMap::from([("B".to_string(), "hidden".to_string())]);
    assert_eq!(
        format_env_display(Some(&env), &variables),
        "B=*****, A=*****, A=*****, =*****"
    );
    assert_eq!(*calls.borrow(), vec!["first", "second", "third"]);
}

#[test]
fn an_as_ref_panic_preserves_the_observed_callback_prefix() {
    let calls = RefCell::new(Vec::new());
    let variables = [
        Observed {
            name: "first",
            value: "A",
            calls: &calls,
            stop: false,
        },
        Observed {
            name: "stop",
            value: "B",
            calls: &calls,
            stop: true,
        },
        Observed {
            name: "unreachable",
            value: "C",
            calls: &calls,
            stop: false,
        },
    ];
    let env = HashMap::from([("map".to_string(), "hidden".to_string())]);
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        format_env_display(Some(&env), &variables)
    }));
    assert!(outcome.is_err());
    assert_eq!(*calls.borrow(), vec!["first", "stop"]);
}
