//! Canonical checksum preimage matching the historical V1 checkpoint schema.
use super::super::RuntimeModuleLifecycleV1;
use super::super::RuntimeModuleRecordV1;
use super::super::RuntimeModuleStateClassV1;
use super::RuntimeModuleRegistryCheckpointV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
const CHECKPOINT_DOMAIN: &[u8] = b"hepta.runtime-module-registry-checkpoint.v1\0";
pub(super) fn encode(checkpoint: &RuntimeModuleRegistryCheckpointV1) -> Vec<u8> {
    let mut records = checkpoint.records.iter().collect::<Vec<_>>();
    records.sort_by(|left, right| {
        left.abi
            .module_id
            .cmp(&right.abi.module_id)
            .then_with(|| left.abi.generation.cmp(&right.abi.generation))
    });
    let mut active = checkpoint.active_reservations.iter().collect::<Vec<_>>();
    active.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then_with(|| left.generation.cmp(&right.generation))
    });
    let mut fences = checkpoint.generation_fences.iter().collect::<Vec<_>>();
    fences.sort_by(|left, right| left.module_id.cmp(&right.module_id));

    let mut bytes = CHECKPOINT_DOMAIN.to_vec();
    push_len(&mut bytes, records.len());
    for record in &records {
        push_record(&mut bytes, record);
    }
    push_len(&mut bytes, active.len());
    for reservation in &active {
        push_id(&mut bytes, &reservation.module_id);
        push_generation(&mut bytes, reservation.generation);
    }
    push_len(&mut bytes, fences.len());
    for fence in &fences {
        push_id(&mut bytes, &fence.module_id);
        push_generation(&mut bytes, fence.first_generation);
        push_generation(&mut bytes, fence.greatest_generation);
    }
    bytes
}
fn push_record(bytes: &mut Vec<u8>, record: &RuntimeModuleRecordV1) {
    push_abi(bytes, &record.abi);
    bytes.push(match record.lifecycle {
        RuntimeModuleLifecycleV1::Registered => 0,
        RuntimeModuleLifecycleV1::Shadow => 1,
        RuntimeModuleLifecycleV1::Canary => 2,
        RuntimeModuleLifecycleV1::Active => 3,
        RuntimeModuleLifecycleV1::Quiescing => 4,
        RuntimeModuleLifecycleV1::Retired => 5,
        RuntimeModuleLifecycleV1::Quarantined => 6,
    });
    push_optional_digest(bytes, record.selection_digest);
    push_optional_digest(bytes, record.canary_digest);
    push_optional_digest(bytes, record.handoff_digest);
}

fn push_abi(bytes: &mut Vec<u8>, abi: &super::super::RuntimeModuleAbiV1) {
    push_id(bytes, &abi.module_id);
    push_id(bytes, &abi.owner_id);
    push_generation(bytes, abi.generation);
    bytes.extend_from_slice(abi.implementation_digest.as_array());
    bytes.extend_from_slice(abi.candidate_artifact_digest.as_array());
    match abi.predecessor_generation {
        Some(generation) => {
            bytes.push(1);
            push_generation(bytes, generation);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(abi.rollback_predecessor_digest.as_array());
    bytes.push(match abi.state_class {
        RuntimeModuleStateClassV1::Stateless => 0,
        RuntimeModuleStateClassV1::Stateful => 1,
        RuntimeModuleStateClassV1::ExternalStateful => 2,
    });
    push_ids(bytes, &abi.dependencies);
    push_ids(bytes, &abi.input_ports);
    push_ids(bytes, &abi.output_ports);
    push_ids(
        bytes,
        &abi.authoritative_domains
            .iter()
            .cloned()
            .collect::<Vec<_>>(),
    );
    push_ids(bytes, &abi.effect_scope.iter().cloned().collect::<Vec<_>>());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_len(bytes, value.as_str().len());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
fn push_generation(bytes: &mut Vec<u8>, value: Generation) {
    bytes.extend_from_slice(&value.get().to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}
