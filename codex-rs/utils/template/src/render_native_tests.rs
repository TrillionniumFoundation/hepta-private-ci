use super::Template;
use super::TemplateRenderError;
use pretty_assertions::assert_eq;

#[test]
fn comparison_windows_preserve_long_common_prefixes_and_unicode_order() {
    for size in [2046, 2047, 2048, 2049, 4095, 4096] {
        let prefix = "x".repeat(size);
        let first = format!("{prefix}é");
        let second = format!("{prefix}😀");
        let parsed =
            Template::parse(&format!("{{{{{first}}}}}/{{{{{second}}}}}/{{{{{first}}}}}")).unwrap();
        assert_eq!(
            parsed.render([(second.as_str(), "{{literal}}"), (first.as_str(), "é")]),
            Ok("é/{{literal}}/é".into())
        );
    }
}

#[test]
fn earlier_extra_variables_cannot_preempt_the_smallest_missing_name() {
    let parsed = Template::parse("{{z}}{{b}}{{a}}").unwrap();
    assert_eq!(
        parsed.render([("0", "extra"), ("a", "A")]),
        Err(TemplateRenderError::MissingValue { name: "b".into() })
    );
    assert_eq!(
        parsed.render([
            ("0", "extra"),
            ("a", "A"),
            ("z", "Z"),
            ("b", "B"),
            ("00", "extra")
        ]),
        Err(TemplateRenderError::ExtraValue { name: "0".into() })
    );
}

#[test]
fn duplicate_value_is_evaluated_before_stopping_the_input_iterator() {
    use std::cell::RefCell;
    use std::rc::Rc;
    struct Observed {
        text: &'static str,
        label: &'static str,
        log: Rc<RefCell<Vec<&'static str>>>,
    }
    impl AsRef<str> for Observed {
        fn as_ref(&self) -> &str {
            self.log.borrow_mut().push(self.label);
            self.text
        }
    }
    let log = Rc::new(RefCell::new(Vec::new()));
    let observed = |text, label| Observed {
        text,
        label,
        log: log.clone(),
    };
    let input = [
        (observed("z", "key0"), observed("one", "value0")),
        (observed("z", "key1"), observed("two", "value1")),
        (observed("never", "key2"), observed("three", "value2")),
    ];
    let parsed = Template::parse("{{missing}}").unwrap();
    assert_eq!(
        parsed.render(input),
        Err(TemplateRenderError::DuplicateValue { name: "z".into() })
    );
    assert_eq!(*log.borrow(), vec!["key0", "value0", "key1", "value1"]);
}

#[test]
fn large_reverse_variable_order_renders_in_template_order() {
    let source: String = (0..1024)
        .map(|index| format!("{{{{key{index:04}}}}},"))
        .collect();
    let parsed = Template::parse(&source).unwrap();
    let variables = (0..1024)
        .rev()
        .map(|index| (format!("key{index:04}"), format!("value{index}")));
    let expected: String = (0..1024).map(|index| format!("value{index},")).collect();
    assert_eq!(parsed.render(variables), Ok(expected));
}
