use super::*;
use codex_hepta_neuron::CellEvidenceV1;
use codex_hepta_neuron::NeuronResourceReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn id(raw: &str) -> StableId {
    match StableId::new(raw) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture id: {error:?}"),
    }
}

fn digest(raw: &str) -> Digest32 {
    Digest32::of_bytes(raw.as_bytes())
}

fn evidence() -> CellEvidenceV1 {
    CellEvidenceV1 {
        cell_id: id("cell:adapter"),
        generation: Generation::new(4).unwrap_or_else(|error| panic!("{error:?}")),
        encoder_digest: digest("encoder"),
        head_digest: digest("head"),
        action_digest: digest("action"),
        value_q24: -3,
        uncertainty_q24: 5,
        runtime_receipt_digest: digest("receipt"),
        model_runtime_binding_digest: digest("binding"),
        confidence_ppm: 900_000,
        ood_ppm: 100_000,
        abstain: false,
        resource_receipt: NeuronResourceReceiptV1 {
            execution_micros: 21,
            transient_allocation_bytes: 0,
            checkpoint_bytes: 0,
            journal_bytes_written: 0,
            write_amplification_ppm: 0,
            saturation_count: 0,
            queue_age_micros: 8,
        },
        evidence_digest: digest("evidence"),
    }
}

#[test]
fn converts_q24_evidence_and_resource_cost_to_group_observation() {
    let observation = match group_cell_observation_from_evidence_v1(&evidence()) {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    };
    assert_eq!(observation.cell_id, "cell:adapter");
    assert_eq!(observation.value_q32, -768);
    assert_eq!(observation.uncertainty_q32, 1_280);
    assert_eq!(observation.cost_micros, 29);
    assert!(!observation.abstain);
}

#[test]
fn rejects_invalid_evidence_before_group_use() {
    let mut invalid = evidence();
    invalid.evidence_digest = Digest32::ZERO;
    assert_eq!(
        group_cell_observation_from_evidence_v1(&invalid),
        Err(GroupSystem2Error::ZeroDigest("cell evidence"))
    );

    let mut invalid = evidence();
    invalid.uncertainty_q24 = i64::MAX;
    assert_eq!(
        group_cell_observation_from_evidence_v1(&invalid),
        Err(GroupSystem2Error::ArithmeticOverflow)
    );
}
