use super::CompactCheckpointV1;

#[test]
fn public_checkpoint_contract_is_canonical_lane_c_type() {
    fn accepts_canonical(_: Option<CompactCheckpointV1>) {}
    accepts_canonical(None);
}
