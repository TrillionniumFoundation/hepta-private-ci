//! Compare the complete renderer against the original production crate.
use std::cell::RefCell;
use std::error::Error;
use std::rc::Rc;

fn compare(source: &str, values: &[(String, String)]) {
    let old = template_reference::render(source, values.iter().cloned());
    let new = template_native::render(source, values.iter().cloned());
    assert_eq!(
        format!("{new:?}"),
        format!("{old:?}"),
        "source={source:?} values={values:?}"
    );
    if let (Err(old), Err(new)) = (old, new) {
        assert_eq!(new.to_string(), old.to_string());
        assert_eq!(
            new.source().map(ToString::to_string),
            old.source().map(ToString::to_string)
        );
    }
}

#[test]
fn exhaustive_orders_preserve_duplicates_missing_and_extra_priority() {
    let names = ["a", "z", "é", "0", "😀"];
    let inputs = ["a", "z", "é", "", " a ", "0"];
    let mut cases = 0;
    for mask in 0..32 {
        let source: String = names
            .iter()
            .enumerate()
            .filter(|(index, _)| mask & (1 << index) != 0)
            .map(|(_, name)| format!("{{{{{name}}}}}|{{{{{name}}}}}"))
            .collect();
        for length in 0..=4 {
            for mut digits in 0..inputs.len().pow(length) {
                let mut values = Vec::new();
                for index in 0..length {
                    values.push((
                        inputs[digits % inputs.len()].into(),
                        format!("{index}:{{{{value}}}}\0😀"),
                    ));
                    digits /= inputs.len();
                }
                compare(&source, &values);
                cases += 1;
            }
        }
    }
    println!("render_cases={cases}");
}

#[test]
fn all_scalar_pairs_preserve_byte_order_and_lookup() {
    let mut cases = 0;
    for value in 0..=0x10ffff {
        let Some(character) = char::from_u32(value) else {
            continue;
        };
        if character == '{' || character == '}' {
            continue;
        }
        let key = format!("k{character}k");
        let source = format!("{{{{{key}}}}}-{{{{kzk}}}}-{{{{k😀k}}}}-{{{{{key}}}}}");
        let values = [
            ("k😀k".into(), "supplementary".into()),
            (key, "chosen".into()),
            ("kzk".into(), "ascii".into()),
        ];
        compare(&source, &values);
        cases += 1;
    }
    println!("render_cases={cases}");
}

#[test]
fn long_common_prefixes_and_values_cross_comparison_window_edges() {
    let mut cases = 0;
    for size in [
        0,
        2045,
        2046,
        2047,
        2048,
        2049,
        4095,
        4096,
        4097,
        2 * 1024 * 1024,
    ] {
        let prefix = "x".repeat(size);
        let names = [
            format!("{prefix}é"),
            format!("{prefix}中"),
            format!("{prefix}😀"),
            prefix.clone() + "a",
        ];
        let source: String = names
            .iter()
            .map(|name| format!("[{name}]={{{{{name}}}}};"))
            .collect();
        let values: Vec<_> = names
            .iter()
            .rev()
            .map(|name| (name.clone(), "{{literal}}\0😀".repeat(100)))
            .collect();
        compare(&source, &values);
        compare(&source, &values[..3]);
        let mut extra = values.clone();
        extra.push((prefix, "extra".into()));
        compare(&source, &extra);
        let mut duplicate = values.clone();
        duplicate.push(values[0].clone());
        compare(&source, &duplicate);
        cases += 4;
    }
    compare("{{x}}/{{x}}", &[("x".into(), "😀".repeat(600_000))]);
    println!("render_cases={}", cases + 1);
}

type Log = Rc<RefCell<Vec<String>>>;
struct Observed {
    text: String,
    id: String,
    panic_on_ref: bool,
    log: Log,
}
impl AsRef<str> for Observed {
    fn as_ref(&self) -> &str {
        self.log.borrow_mut().push(format!("as_ref:{}", self.id));
        assert!(!self.panic_on_ref, "controlled AsRef panic");
        &self.text
    }
}
impl Drop for Observed {
    fn drop(&mut self) {
        self.log.borrow_mut().push(format!("drop:{}", self.id));
    }
}
struct ObservedInput {
    pairs: Vec<(Observed, Observed)>,
    log: Log,
}
struct ObservedIterator {
    pairs: std::vec::IntoIter<(Observed, Observed)>,
    log: Log,
}
impl IntoIterator for ObservedInput {
    type Item = (Observed, Observed);
    type IntoIter = ObservedIterator;
    fn into_iter(self) -> Self::IntoIter {
        self.log.borrow_mut().push("into_iter".into());
        ObservedIterator {
            pairs: self.pairs.into_iter(),
            log: self.log,
        }
    }
}
impl Iterator for ObservedIterator {
    type Item = (Observed, Observed);
    fn next(&mut self) -> Option<Self::Item> {
        self.log.borrow_mut().push("next".into());
        self.pairs.next()
    }
}
impl Drop for ObservedIterator {
    fn drop(&mut self) {
        self.log.borrow_mut().push("drop:iterator".into());
    }
}
enum Variant {
    Original,
    Native,
}
fn traced(
    variant: Variant,
    source: &str,
    keys: &[&str],
    panic_at: Option<usize>,
) -> (String, Vec<String>) {
    let log = Log::default();
    let pairs = keys
        .iter()
        .enumerate()
        .map(|(index, key)| {
            (
                Observed {
                    text: (*key).into(),
                    id: format!("key{index}"),
                    panic_on_ref: panic_at == Some(2 * index),
                    log: log.clone(),
                },
                Observed {
                    text: format!("value{index}"),
                    id: format!("value{index}"),
                    panic_on_ref: panic_at == Some(2 * index + 1),
                    log: log.clone(),
                },
            )
        })
        .collect();
    let input = ObservedInput {
        pairs,
        log: log.clone(),
    };
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| match variant {
        Variant::Original => format!("{:?}", template_reference::render(source, input)),
        Variant::Native => format!("{:?}", template_native::render(source, input)),
    }));
    let outcome = result.unwrap_or_else(|_| "panic".into());
    let trace = log.borrow().clone();
    (outcome, trace)
}

#[test]
fn iterator_as_ref_drop_and_unwind_effects_match() {
    let mut cases = 0;
    for source in ["", "{{a}}", "{{a}}{{z}}", "{{bad"] {
        for keys in [
            vec![],
            vec!["a"],
            vec!["z", "a"],
            vec!["z", "z", "a"],
            vec!["b", "a", "b", "never"],
        ] {
            for panic_at in [None, Some(0), Some(1), Some(2), Some(3), Some(7)] {
                let old = traced(Variant::Original, source, &keys, panic_at);
                let new = traced(Variant::Native, source, &keys, panic_at);
                assert_eq!(
                    new, old,
                    "source={source:?} keys={keys:?} panic_at={panic_at:?}"
                );
                cases += 1;
            }
        }
    }
    println!("render_cases={cases}");
}

#[test]
fn repeated_rendering_with_many_variables() {
    let source: String = (0..4096)
        .map(|index| format!("{{{{key{index:04}}}}}\n"))
        .collect();
    let old = template_reference::Template::parse(&source).unwrap();
    let new = template_native::Template::parse(&source).unwrap();
    let descending: Vec<_> = (0..4096)
        .rev()
        .map(|index| (format!("key{index:04}"), format!("value{index}")))
        .collect();
    for values in [descending.clone(), descending.into_iter().rev().collect()] {
        assert_eq!(
            format!("{:?}", new.render(values.clone())),
            format!("{:?}", old.render(values))
        );
    }
    println!("render_cases=2");
}
