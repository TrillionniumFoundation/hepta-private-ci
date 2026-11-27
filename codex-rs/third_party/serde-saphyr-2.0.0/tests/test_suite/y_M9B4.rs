// M9B4: Literal Scalar — expect "literal\n\ttext\n"

#[test]
fn yaml_m9b4_literal_scalar() {
    let y = "|\n literal\n \ttext\n\n\n";
    let s: String = serde_saphyr::from_str(y).expect("failed to parse M9B4");
    assert_eq!(s, "literal\n\ttext\n");
}
