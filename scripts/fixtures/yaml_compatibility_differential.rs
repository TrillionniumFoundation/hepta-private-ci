use pretty_assertions::assert_eq;
use serde::Deserialize;

#[derive(Debug, Deserialize, PartialEq)]
struct Shape {
    name: String,
    description: String,
}

#[test]
fn old_and_replacement_typed_yaml_agree_on_corpus() {
    for source in [
        "name: demo\ndescription: text\n",
        "name: demo\ndescription: '部署 café 漢字'\n",
        "name: demo\ndescription: |-\n  a: b\n  c\n",
        "name: demo\ndescription: >-\n  a\n  b\n",
        "name: &n demo\ndescription: *n\n",
        "name: '0012'\ndescription: 'true'\n",
        "name: demo\ndescription: \"escaped\\nline\"\n",
        "name: demo\ndescription: text # comment\n",
        "name: demo\ndescription: text\nignored: [one, two]\n",
        "name: first\nname: second\ndescription: text\n",
        "name: demo\ndescription: [one, two]\n",
        "name: demo\ndescription: 'unterminated\n",
        "---\nname: demo\ndescription: text\n---\nname: next\ndescription: value\n",
    ] {
        let old = serde_yaml_old::from_str::<Shape>(source);
        let new = serde_yaml::from_str::<Shape>(source);
        match (old, new) {
            (Ok(old), Ok(new)) => assert_eq!(old, new, "{source:?}"),
            (Err(_), Err(_)) => (),
            (old, new) => panic!("acceptance mismatch for {source:?}: {old:?}, {new:?}"),
        }
    }
}
