use codex_hepta_neuron::CellEvolutionBindingV2;
use codex_hepta_neuron::CellLearningBindingV2;
use pretty_assertions::assert_eq;

use super::*;

fn publication() -> io::Result<OriginalRootBPublicationDataV2> {
    let manifest = CellBackendManifestV2 {
        profile: "publication-data-fixture".into(),
        source_digest: [1; 32],
        bundle_digest: [2; 32],
        encoder: Some([3; 32]),
        head: Some([4; 32]),
        memory: None,
        world_model: None,
        decoder: None,
        runtime_digest: [5; 32],
        device_digest: [6; 32],
        input_schema: [7; 32],
        state_schema: [8; 32],
        output_schema: [9; 32],
        learning: CellLearningBindingV2::Frozen { weights: [10; 32] },
        evolution: CellEvolutionBindingV2 {
            structure: [11; 32],
            lineage: [12; 32],
            source_dependencies: [13; 32],
            adoption_receipt: [14; 32],
        },
        max_input_bytes: 64,
        max_state_bytes: 128,
        max_delta_bytes: 64,
        max_prefix_bytes: 128,
        max_step_cost_entries: 4,
        max_ack_cost_entries: 4,
    };
    Ok(OriginalRootBPublicationDataV2 {
        schema: 2,
        purpose: PURPOSE.into(),
        execution: [21; 32],
        authentication: [22; 32],
        trust: [23; 32],
        evidence: [24; 32],
        manifest_digest: manifest.digest().map_err(io::Error::other)?,
        manifest,
    })
}

#[test]
fn publication_data_preserves_complete_manifest_and_rejects_changed_native_material()
-> io::Result<()> {
    let original = publication()?;
    let bytes = serde_json::to_vec(&original)?;
    assert_eq!(OriginalRootBPublicationDataV2::decode(&bytes)?, original);
    for changed in ["source", "runtime", "bounds"] {
        let mut next = original.clone();
        match changed {
            "source" => next.manifest.source_digest = [31; 32],
            "runtime" => next.manifest.runtime_digest = [32; 32],
            "bounds" => next.manifest.max_step_cost_entries += 1,
            _ => unreachable!(),
        }
        assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&next)?).is_err());
    }
    Ok(())
}

#[test]
fn publication_data_refuses_noncanonical_unknown_and_incomplete_images() -> io::Result<()> {
    let original = publication()?;
    let mut trailing = serde_json::to_vec(&original)?;
    trailing.push(b'\n');
    assert!(OriginalRootBPublicationDataV2::decode(&trailing).is_err());
    let mut unknown = serde_json::to_value(&original)?;
    unknown["caller_claimed_authority"] = serde_json::json!(true);
    assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&unknown)?).is_err());
    let mut missing = serde_json::to_value(&original)?;
    missing.as_object_mut().unwrap().remove("manifest");
    assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&missing)?).is_err());
    assert!(OriginalRootBPublicationDataV2::decode(&[]).is_err());
    assert!(
        OriginalRootBPublicationDataV2::decode(&vec![
            b' ';
            MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 + 1
        ])
        .is_err()
    );
    Ok(())
}

#[test]
fn publication_data_refuses_legacy_or_wrong_purpose_without_reconstruction() -> io::Result<()> {
    let legacy = [
        b"hepta.root.independent-b.qualification-publication.v1\0".as_slice(),
        &[21; 32],
        &[22; 32],
        &[23; 32],
        &[24; 32],
    ]
    .concat();
    assert!(OriginalRootBPublicationDataV2::decode(&legacy).is_err());
    let mut next = publication()?;
    next.schema = 1;
    assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&next)?).is_err());
    next = publication()?;
    next.purpose = "runtime.learning.caller-manifest.v2".into();
    assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&next)?).is_err());
    next = publication()?;
    next.authentication = [0; 32];
    assert!(OriginalRootBPublicationDataV2::decode(&serde_json::to_vec(&next)?).is_err());
    Ok(())
}
