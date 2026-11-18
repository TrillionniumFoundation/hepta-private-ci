//! Compare the complete public template API with the original production crate.

fn compare(source: &str) {
    let old = template_reference::Template::parse(source);
    let new = template_native::Template::parse(source);
    assert_eq!(format!("{new:?}"), format!("{old:?}"), "{source:?}");
    assert_eq!(format!("{new:#?}"), format!("{old:#?}"), "{source:?}");
    if let (Ok(old), Ok(new)) = (old, new) {
        assert_eq!(new, new.clone());
        assert_eq!(format!("{:?}", new.clone()), format!("{:?}", old.clone()));
        let mut old_names = old.placeholders();
        let mut new_names = new.placeholders();
        loop {
            assert_eq!(new_names.len(), old_names.len());
            assert_eq!(new_names.size_hint(), old_names.size_hint());
            let expected = old_names.next();
            assert_eq!(new_names.next(), expected);
            if expected.is_none() {
                assert_eq!(new_names.next(), old_names.next());
                assert_eq!(new_names.size_hint(), old_names.size_hint());
                break;
            }
        }
        // Independent iterators borrow the same canonical collection without
        // changing it, including after another iterator has been exhausted.
        assert_eq!(
            new.placeholders().collect::<Vec<_>>(),
            old.placeholders().collect::<Vec<_>>()
        );
    }
}

fn source(names: &[String]) -> String {
    names.iter().map(|name| format!("{{{{{name}}}}}")).collect()
}

#[test]
fn every_small_insertion_order_keeps_sorted_unique_names_and_debug() {
    fn visit(names: &mut [String], index: usize, count: &mut usize) {
        if index == names.len() {
            let text = source(names);
            compare(&text);
            compare(&(text.clone() + &text));
            *count += 2;
            return;
        }
        for next in index..names.len() {
            names.swap(index, next);
            visit(names, index + 1, count);
            names.swap(index, next);
        }
    }
    let mut names = ["a", "A", "é", "😀", "0", "\0"].map(str::to_owned);
    let mut cases = 0;
    visit(&mut names, 0, &mut cases);
    println!("placeholder_cases={cases}");
}

#[test]
fn scalar_boundaries_and_trimmed_duplicates_keep_byte_order() {
    let scalars = [
        '\0',
        '\u{7f}',
        '\u{80}',
        '\u{7ff}',
        '\u{800}',
        '\u{d7ff}',
        '\u{e000}',
        '\u{ffff}',
        '\u{10000}',
        '\u{10ffff}',
        'é',
        'e',
        '\u{301}',
        '\u{200b}',
        '\u{200c}',
        '\u{200d}',
        '\u{feff}',
        '\u{85}',
        '\u{a0}',
        '\u{200a}',
        '\u{3000}',
    ];
    let mut cases = 0;
    for first in scalars {
        for second in scalars {
            compare(&format!(
                "{{{{k{first}k}}}}{{{{k{second}k}}}}{{{{ \u{3000}k{first}k\u{85} }}}}"
            ));
            cases += 1;
        }
    }
    for text in ["", "literal", "{{}}", "é{{ }}", "😀{{a{{b}}", "{{a", "é}}"] {
        compare(text);
        cases += 1;
    }
    println!("placeholder_cases={cases}");
}

#[test]
fn canonical_collection_preserves_template_equality() {
    let sources = [
        "",
        "literal",
        "{{a}}",
        "{{ a }}",
        "{{\u{3000}a\u{85}}}",
        "{{a}}{{a}}",
        "{{a}}{{b}}",
        "{{b}}{{a}}",
        "{{{{",
        "{{{{{{a}}",
    ];
    let mut cases = 0;
    for left in sources {
        for right in sources {
            let old_left = template_reference::Template::parse(left);
            let old_right = template_reference::Template::parse(right);
            let new_left = template_native::Template::parse(left);
            let new_right = template_native::Template::parse(right);
            assert_eq!(
                new_left == new_right,
                old_left == old_right,
                "{left:?} {right:?}"
            );
            cases += 1;
        }
    }
    println!("placeholder_cases={cases}");
}

#[test]
fn long_common_prefixes_and_repeated_names_do_not_depend_on_frame_edges() {
    let mut cases = 0;
    for size in [0, 2047, 2048, 2049, 4095, 4096, 4097, 2 * 1024 * 1024] {
        let prefix = "x".repeat(size);
        let names = ["😀", "é", "a", "😀", "", "中"].map(|suffix| format!("k{prefix}{suffix}k"));
        compare(&source(&names));
        cases += 1;
    }
    println!("placeholder_cases={cases}");
}

#[test]
fn large_orderings_duplicates_and_repeated_iteration_match() {
    let mut cases = 0;
    for count in [1, 2, 15, 16, 17, 255, 256, 257, 4096, 16384] {
        let mut names: Vec<_> = (0..count).map(|index| format!("key{index:06}")).collect();
        compare(&source(&names));
        names.reverse();
        compare(&source(&names));
        let mut seed = 0x4d595df4d0f33173_u64;
        for index in (1..names.len()).rev() {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            names.swap(index, seed as usize % (index + 1));
        }
        names.extend(names.clone());
        compare(&source(&names));
        cases += 3;
    }
    println!("placeholder_cases={cases}");
}

#[test]
fn canonical_names_supply_the_actual_renderer_without_changing_its_errors() {
    let source = "{{z}}/{{a}}/{{é}}/{{a}}";
    let old = template_reference::Template::parse(source).unwrap();
    let new = template_native::Template::parse(source).unwrap();
    let values: Vec<_> = old
        .placeholders()
        .map(|name| (name.to_owned(), format!("[{name}]")))
        .collect();
    let mut extra = values.clone();
    extra.push(("0-extra".to_owned(), "unused".to_owned()));
    for input in [values.clone(), values[1..].to_vec(), extra] {
        assert_eq!(
            format!("{:?}", new.render(input.clone())),
            format!("{:?}", old.render(input))
        );
    }
    println!("placeholder_cases=3");
}
