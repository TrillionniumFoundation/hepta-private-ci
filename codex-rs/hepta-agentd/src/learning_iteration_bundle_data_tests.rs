use pretty_assertions::assert_eq;

use super::codec::MAX_BYTES;
use super::codec::decode_original_bundle_data;
use super::codec::encode_original_bundle_data;
use super::test_support as support;

#[test]
fn original_bundle_data_roundtrips_existing_checkpoint_shapes() -> anyhow::Result<()> {
    for snapshot in support::snapshots(support::Decision::Update)? {
        let coordinator =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                snapshot.clone(),
            )?;
        for bundle in
            std::iter::once(&snapshot.request.selected_bundle).chain(coordinator.candidate())
        {
            let bytes = encode_original_bundle_data(bundle)?;
            assert_eq!(decode_original_bundle_data(&bytes)?, *bundle);
            assert_eq!(
                encode_original_bundle_data(&decode_original_bundle_data(&bytes)?)?,
                bytes
            );
        }
    }
    Ok(())
}

#[test]
fn original_bundle_data_rejects_wrong_framing_truncation_and_invalid_bundle() -> anyhow::Result<()>
{
    let snapshots = support::snapshots(support::Decision::Update)?;
    let bundle = &snapshots[0].request.selected_bundle;
    let original = encode_original_bundle_data(bundle)?;
    for end in [0, 8, original.len() - 1] {
        assert!(decode_original_bundle_data(&original[..end]).is_err());
    }
    let mut wrong = original.clone();
    wrong[0] ^= 1;
    assert!(decode_original_bundle_data(&wrong).is_err());
    let mut trailing = original;
    trailing.push(0);
    assert!(decode_original_bundle_data(&trailing).is_err());
    let mut invalid = bundle.clone();
    invalid.components.heads = codex_hepta_types::Digest32::ZERO;
    assert!(encode_original_bundle_data(&invalid).is_err());
    assert!(decode_original_bundle_data(&vec![0; MAX_BYTES + 1]).is_err());
    Ok(())
}
