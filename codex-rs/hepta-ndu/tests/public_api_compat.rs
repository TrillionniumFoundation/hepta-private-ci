use codex_hepta_ndu::{
    NduIterationReceiptV1, ZQ24ConversionReceiptV1,
};

fn consume_iteration_v1(receipt: NduIterationReceiptV1) {
    let NduIterationReceiptV1 {
        subject_id,
        subject_class,
        objective_digest,
        generation,
        event_digest,
        coefficient_digest,
        iteration,
        predecessor_revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
        solve_input_digest,
        receipt_digest,
        authority,
    } = receipt;
    let _ = (
        subject_id,
        subject_class,
        objective_digest,
        generation,
        event_digest,
        coefficient_digest,
        iteration,
        predecessor_revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
        solve_input_digest,
        receipt_digest,
        authority,
    );
}

fn consume_z_v1(receipt: ZQ24ConversionReceiptV1) {
    let ZQ24ConversionReceiptV1 {
        original_z,
        q24_raw,
        maximum_absolute_quantization_error,
        profile_digest,
        source_digest,
        receipt_digest,
        authority,
    } = receipt;
    let _ = (
        original_z,
        q24_raw,
        maximum_absolute_quantization_error,
        profile_digest,
        source_digest,
        receipt_digest,
        authority,
    );
}

#[test]
fn v1_public_source_surface_remains_compatible() {
    let iteration_reader: fn(NduIterationReceiptV1) = consume_iteration_v1;
    let z_reader: fn(ZQ24ConversionReceiptV1) = consume_z_v1;
    let _ = (iteration_reader, z_reader);
}
