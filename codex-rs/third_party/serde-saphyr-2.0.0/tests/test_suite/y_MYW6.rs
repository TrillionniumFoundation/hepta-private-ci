// MYW6: Block Scalar Strip (|-)
#[test]
fn yaml_myw6_block_scalar_strip() {
    let y = concat!(
        r#"|-
 ab
"#,
        "\x20\n",
        "\x20\n",
        r#"...
"#,
    );
    let s: String = serde_saphyr::from_str(y).expect("failed to parse MYW6");
    assert_eq!(s.as_str(), "ab");
}
