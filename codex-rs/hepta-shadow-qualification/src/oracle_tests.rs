use super::oracle::FrozenOracle;
use crate::QualificationError;

const TRACKED: &[u8] = include_bytes!("../fixtures/live_product_oracle_v2_2f704.json");

#[test]
fn loads_the_embedded_frozen_oracle() -> Result<(), QualificationError> {
    let oracle = FrozenOracle::load_embedded()?;
    assert_eq!(oracle.corpus_sha256().len(), 64);
    assert_eq!(
        oracle.oracle_commit(),
        "2f704dc7c1172cefca908852456beccf4d02a5d1"
    );
    assert_eq!(
        oracle.oracle_tree(),
        "7be9a382b2610790838eef874cb4d381b5025490"
    );
    assert_eq!(oracle.expected_normalized_receipt().len(), 1_606);
    assert_eq!(oracle.expected_normalized_receipt_sha256().len(), 64);
    assert_eq!(oracle.payload_sha256().len(), 64);
    assert_eq!(oracle.sample_id_sha256().len(), 64);
    assert!(
        oracle
            .raw_function_arguments()
            .contains("hepta-shadow-probe")
    );
    Ok(())
}

#[test]
fn rejects_nonofficial_or_mutated_oracle_bytes() {
    assert!(FrozenOracle::load(TRACKED).is_err());
    let mut official = TRACKED[..TRACKED.len() - 1].to_vec();
    official[100] ^= 1;
    assert!(FrozenOracle::load(&official).is_err());
}
