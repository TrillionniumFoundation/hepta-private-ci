fn validate_archive(
    native: &SparseConfig,
    scope: JournalScope,
    config: &NeuronRuntimeConfigV1,
    archive: &[NeuronLegacyOperationRecordV1],
) -> Result<Vec<PreparedNeuronOperationV1>, NeuronLegacyOperationMigrationError> {
    let mut checkpoint: Option<SparseCheckpoint> = None;
    let mut frontier = None;
    let mut prepared = Vec::with_capacity(archive.len());
    for record in archive {
        if record.expected_anchor != frontier
            || record.sparse_tick.scope_digest != scope.scope_digest
            || record.sparse_tick.objective_digest != scope.objective_digest
        {
            return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
        }
        let value = PreparedNeuronOperationV1::new(
            record.input_digest,
            record.tick_id.clone(),
            record.expected_anchor,
            record.next_anchor,
            record.sparse_tick.clone(),
            record.output.clone(),
        )?;
        let (next, receipt) = sparse_tick(native, &record.sparse_tick, checkpoint.as_ref())
            .map_err(JournalError::Mechanism)?;
        validate_replayed_result(config, &value, &next, &receipt)?;
        frontier = Some(value.next_anchor);
        checkpoint = Some(next);
        prepared.push(value);
    }
    Ok(prepared)
}

fn replay_receipt(
    native: &SparseConfig,
    archive: &[NeuronLegacyOperationRecordV1],
) -> Result<Option<SparseSignalReceipt>, NeuronLegacyOperationMigrationError> {
    let mut checkpoint = None;
    let mut last = None;
    for record in archive {
        let (next, receipt) = sparse_tick(native, &record.sparse_tick, checkpoint.as_ref())
            .map_err(JournalError::Mechanism)?;
        checkpoint = Some(next);
        last = Some(receipt);
    }
    Ok(last)
}

fn validate_replayed_result(
    config: &NeuronRuntimeConfigV1,
    value: &PreparedNeuronOperationV1,
    checkpoint: &SparseCheckpoint,
    receipt: &SparseSignalReceipt,
) -> Result<(), NeuronLegacyOperationMigrationError> {
    let expected_before = value
        .expected_anchor
        .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
    if checkpoint.digest() != value.next_anchor.checkpoint_digest
        || checkpoint.predecessor_digest() != expected_before
        || value.output.tick.checkpoint_before != expected_before
        || value.output.tick.checkpoint_after != checkpoint.digest()
        || value.output.tick.activation_digest != checkpoint.activation_digest()
        || value.output.tick.threshold_digest != checkpoint.threshold_digest()
        || value.output.tick.eligibility_digest != checkpoint.eligibility_digest()
        || value.output.tick.active_indices != committed_active_indices(checkpoint)?
        || value.output.signal.temporal_state_digest != checkpoint.temporal_state_digest()
        || value.output.signal.signals_q24 != checkpoint.activation_q24()
        || value.output.signal.authority.grants_any()
        || receipt.checkpoint_before != expected_before
        || receipt.checkpoint_after != checkpoint.digest()
        || receipt.prediction_error_q24 != value.output.tick.prediction_error_q24
        || receipt.projection_count != value.output.tick.resource_receipt.saturation_count
        || receipt.active_fraction_ppm != value.output.tick.sparsity_ppm
        || receipt.activation_q24 != value.output.signal.signals_q24
    {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }

    let model_output = NeuronModelOutputV1 {
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        output_digest: canonical_model_output_digest_v1(
            &value.sparse_tick.drive_q24,
            &value.sparse_tick.prediction_q24,
            &value.output.model_runtime,
        )?,
        drive_q24: value.sparse_tick.drive_q24.clone(),
        prediction_q24: value.sparse_tick.prediction_q24.clone(),
        queue_age_micros: value.output.tick.resource_receipt.queue_age_micros,
        transient_allocation_bytes: value
            .output
            .tick
            .resource_receipt
            .transient_allocation_bytes,
        runtime_receipt: value.output.model_runtime.clone(),
    };
    validate_model_output(config, &model_output)?;
    if value.output.signal.model_runtime_digest != digest_model_binding(&model_output)? {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }

    let (confidence, ood, calibration_abstain) =
        calibrate(&config.calibration, receipt, checkpoint.sequence())?;
    let resource = &value.output.tick.resource_receipt;
    let resource_abstain = resource.execution_micros > config.resource_envelope.p99_latency_micros
        || resource.transient_allocation_bytes
            > config.resource_envelope.transient_allocation_bytes
        || resource.checkpoint_bytes > config.resource_envelope.checkpoint_bytes
        || resource.write_amplification_ppm > config.resource_envelope.write_amplification_ppm;
    let journal_bytes = u64::try_from(304_usize + 16 * config.state_width)
        .map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)?;
    if value.output.tick.confidence_ppm != confidence
        || value.output.tick.ood_ppm != ood
        || value.output.signal.ood_ppm != ood
        || value.output.tick.abstain != (calibration_abstain || resource_abstain)
        || value.output.signal.abstain != value.output.tick.abstain
        || value.output.signal.activation_sparsity_ppm != value.output.tick.sparsity_ppm
        || resource.checkpoint_bytes
            != u64::try_from(checkpoint.bounded_encoded_bytes())
                .map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)?
        || resource.journal_bytes_written != journal_bytes
        || resource.write_amplification_ppm
            != write_amplification(resource.journal_bytes_written, resource.checkpoint_bytes)?
    {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }
    Ok(())
}

fn archive_digest(
    values: &[PreparedNeuronOperationV1],
) -> Result<Digest32, NeuronLegacyOperationMigrationError> {
    let mut bytes = b"hepta.neuron.legacy-operation-archive.v1".to_vec();
    let count = u64::try_from(values.len())
        .map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(value.operation_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn migration_receipt_digest(
    config_digest: Digest32,
    scope: JournalScope,
    imported_operations: u64,
    frontier: Option<JournalAnchor>,
    archive_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.legacy-operation-migration-receipt.v1".to_vec();
    bytes.extend_from_slice(config_digest.as_array());
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&imported_operations.to_be_bytes());
    let frontier = frontier.unwrap_or(JournalAnchor {
        sequence: 0,
        checkpoint_digest: Digest32::ZERO,
    });
    bytes.extend_from_slice(&frontier.sequence.to_be_bytes());
    bytes.extend_from_slice(frontier.checkpoint_digest.as_array());
    bytes.extend_from_slice(archive_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn committed_active_indices(
    checkpoint: &SparseCheckpoint,
) -> Result<Vec<u32>, NeuronLegacyOperationMigrationError> {
    checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| {
            u32::try_from(index).map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)
        })
        .collect()
}

fn write_amplification(
    journal_bytes_written: u64,
    checkpoint_bytes: u64,
) -> Result<u32, NeuronLegacyOperationMigrationError> {
    if checkpoint_bytes == 0 {
        return Err(NeuronLegacyOperationMigrationError::Arithmetic);
    }
    let numerator = u128::from(journal_bytes_written)
        .checked_mul(1_000_000)
        .ok_or(NeuronLegacyOperationMigrationError::Arithmetic)?;
    let rounded_up = numerator
        .checked_add(u128::from(checkpoint_bytes.saturating_sub(1)))
        .ok_or(NeuronLegacyOperationMigrationError::Arithmetic)?
        / u128::from(checkpoint_bytes);
    u32::try_from(rounded_up).map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)
}
