use super::from_slice;
use super::from_str;
use super::scalar_mapping;
use super::validate;
use pretty_assertions::assert_eq;
use serde::Deserialize;

#[test]
fn arbitrary_mapping_keys_do_not_hide_string_fields() {
    let actual = scalar_mapping(
        "? [one, two]\n: ignored\n? {nested: key}\n: ignored\n7: ignored\ntrue: ignored\nnull: ignored\nname: demo\ndescription: ' a document '\n",
    )
    .unwrap();
    assert_eq!(
        actual,
        Some(vec![
            ("name".to_string(), Some("demo".to_string())),
            ("description".to_string(), Some("a document".to_string())),
        ])
    );
}

#[test]
fn scalar_resolution_keeps_yaml12_and_number_rendering() {
    let actual = scalar_mapping(
        "a: yes\nb: OFF\nc: True\nd: FALSE\ne: 0x10\nf: 1.0\ng: .NaN\nh: -.Inf\ni: null\nj: ' null '\nk: !!str 0x10\nl: -0.0\n",
    )
    .unwrap()
    .unwrap();
    let expected = [
        ("a", Some("yes")),
        ("b", Some("OFF")),
        ("c", Some("true")),
        ("d", Some("false")),
        ("e", Some("16")),
        ("f", Some("1.0")),
        ("g", Some(".nan")),
        ("h", Some("-.inf")),
        ("i", None),
        ("j", Some("null")),
        ("k", Some("0x10")),
        ("l", Some("-0.0")),
    ]
    .map(|(key, value)| (key.to_string(), value.map(str::to_string)))
    .to_vec();
    assert_eq!(actual, expected);
}

#[test]
fn application_tags_survive_until_scalar_selection() {
    let actual = scalar_mapping(
        "!root\n!key name: demo\ndescription: !secret hidden\narray: !items [a, b]\nmap: !entry {a: b}\nordinary: !!str visible\n",
    )
    .unwrap();
    assert_eq!(
        actual,
        Some(vec![
            ("name".to_string(), Some("demo".to_string())),
            ("description".to_string(), None),
            ("array".to_string(), None),
            ("map".to_string(), None),
            ("ordinary".to_string(), Some("visible".to_string())),
        ])
    );
}

#[test]
fn anchors_work_without_implicitly_expanding_merge_keys() {
    assert_eq!(
        scalar_mapping("defaults: &defaults {description: inherited}\n<<: *defaults\nname: &name demo\ncopy: *name\n").unwrap(),
        Some(vec![
            ("defaults".to_string(), None),
            ("<<".to_string(), None),
            ("name".to_string(), Some("demo".to_string())),
            ("copy".to_string(), Some("demo".to_string())),
        ])
    );
}

#[test]
fn malformed_and_duplicate_nested_values_fail_the_whole_document() {
    for input in [
        "name: demo\nname: other\n",
        "ignored: [{a: 1, a: 2}]\nname: demo\n",
        "name: demo\n---\nname: second\n",
        "ignored: [unterminated\n",
        "ignored: *undefined\n",
    ] {
        assert!(validate(input).is_err(), "accepted invalid input: {input}");
        assert!(
            scalar_mapping(input).is_err(),
            "accepted invalid input: {input}"
        );
    }
    assert_eq!(scalar_mapping("[one, two]").unwrap(), None);
    assert_eq!(scalar_mapping("null").unwrap(), None);
}

#[derive(Debug, Deserialize, PartialEq)]
struct Manifest {
    name: String,
    description: String,
}

#[test]
fn typed_manifests_and_utf8_slices_share_the_same_parser() {
    let input = "name: demo\ndescription: |\n  line one\n  line two\n";
    let expected = Manifest {
        name: "demo".to_string(),
        description: "line one\nline two\n".to_string(),
    };
    assert_eq!(from_str::<Manifest>(input).unwrap(), expected);
    assert_eq!(from_slice::<Manifest>(input.as_bytes()).unwrap(), expected);
    assert!(from_slice::<Manifest>(&[0xff, 0xfe]).is_err());
    assert!(from_str::<Manifest>("name: demo\ndescription: [wrong]").is_err());
}
