use super::*;
use pretty_assertions::assert_eq;

#[test]
fn mapping_is_explicit_versioned_and_digest_bound() {
    let mapping = ResourceMappingV1 {
        cpu_millis_per_concurrent_turn: 750,
        accelerator_millis_per_concurrent_turn: 0,
        retain_logical_axes: true,
    };
    let demand = LogicalResourceDemandV1 {
        concurrent_turns: 2,
        memory_mib: 64,
        tool_processes: 3,
        turn_queue_slots: 8,
    };
    assert_eq!(
        mapping.map(demand),
        Ok(ResourceVectorV1 {
            cpu_millis: 1_500,
            memory_bytes: 64 * MEMORY_MIB_BYTES,
            accelerator_millis: 0,
            concurrent_turns: 2,
            tool_processes: 3,
            turn_queue_slots: 8,
        })
    );
    let mut changed = mapping;
    changed.cpu_millis_per_concurrent_turn += 1;
    assert_ne!(mapping.semantic_digest(), changed.semantic_digest());
}

#[test]
fn optional_axis_compatibility_fails_closed() {
    let requested = ResourceVectorV1::physical(1_000, 4_096, 500);
    let capacity = ResourceVectorV1::physical(2_000, 8_192, 0);
    assert_eq!(
        requested.compatible_with(capacity),
        Err(ResourceVectorError::UnsupportedAxis(
            ResourceAxisV1::AcceleratorMillis
        ))
    );
}

#[test]
fn checked_arithmetic_preserves_entire_vector() {
    let left = ResourceVectorV1 {
        cpu_millis: 10,
        memory_bytes: 20,
        accelerator_millis: 30,
        concurrent_turns: 40,
        tool_processes: 50,
        turn_queue_slots: 60,
    };
    let right = ResourceVectorV1 {
        cpu_millis: 1,
        memory_bytes: 2,
        accelerator_millis: 3,
        concurrent_turns: 4,
        tool_processes: 5,
        turn_queue_slots: 6,
    };
    let sum = ResourceVectorV1 {
        cpu_millis: 11,
        memory_bytes: 22,
        accelerator_millis: 33,
        concurrent_turns: 44,
        tool_processes: 55,
        turn_queue_slots: 66,
    };
    assert_eq!(left.checked_add(right), Ok(sum));
    assert_eq!(sum.checked_sub(right), Ok(left));
}
