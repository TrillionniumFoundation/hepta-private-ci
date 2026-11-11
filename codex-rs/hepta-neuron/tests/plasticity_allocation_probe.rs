//! Allocation regression probe for the public read-only Q24 comparator.
//!
//! Only this integration-test executable replaces its allocator. The library's
//! unsafe-code prohibition and production allocator remain unchanged. Inputs
//! are built before tracking starts; malformed payloads are only 32 or 64 KiB.

use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::cell::Cell;
use std::mem::size_of;

use codex_hepta_neuron::ParameterGroupMapV1;
use codex_hepta_neuron::PlasticityError;
use codex_hepta_neuron::PlasticityTrustRegionV1;
use codex_hepta_neuron::TemporalCreditArmV1;
use codex_hepta_neuron::TemporalCreditContractV1;
use codex_hepta_neuron::TemporalCreditError;
use codex_hepta_neuron::TemporalEligibilityActionV1;
use codex_hepta_neuron::TemporalFeedbackV1;
use codex_hepta_neuron::TemporalSplitV1;
use codex_hepta_neuron::accumulate_temporal_credit_q24;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
const REJECTION_ALLOCATION_LIMIT: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Default)]
struct AllocationStats {
    requested_bytes: usize,
    largest_request: usize,
}

thread_local! {
    static ALLOCATIONS: Cell<Option<AllocationStats>> = const { Cell::new(None) };
}

struct ProbeAllocator;

#[global_allocator]
static ALLOCATOR: ProbeAllocator = ProbeAllocator;

fn record_allocation(bytes: usize) {
    // Constant-initialized Cell access neither allocates nor unwinds. Ignore
    // other threads and calls made after this thread's TLS has been destroyed.
    let _ = ALLOCATIONS.try_with(|counter| {
        if let Some(mut stats) = counter.get() {
            stats.requested_bytes = stats.requested_bytes.saturating_add(bytes);
            stats.largest_request = stats.largest_request.max(bytes);
            counter.set(Some(stats));
        }
    });
}

// SAFETY: all allocation operations forward the original pointer/layout to
// System. The observational counter never alters allocation or deallocation.
unsafe impl GlobalAlloc for ProbeAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record_allocation(layout.size());
        // SAFETY: caller supplies the valid GlobalAlloc layout unchanged.
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record_allocation(layout.size());
        // SAFETY: caller supplies the valid GlobalAlloc layout unchanged.
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        record_allocation(new_size);
        // SAFETY: caller supplies System's allocation and valid new size.
        unsafe { System.realloc(ptr, layout, new_size) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: allocations above all originate from System.
        unsafe { System.dealloc(ptr, layout) }
    }
}

struct ResetCounter;

impl Drop for ResetCounter {
    fn drop(&mut self) {
        let _ = ALLOCATIONS.try_with(|counter| counter.set(None));
    }
}

fn measured<T>(operation: impl FnOnce() -> T) -> (T, AllocationStats) {
    assert!(ALLOCATIONS.with(|counter| counter.get()).is_none());
    let reset = ResetCounter;
    ALLOCATIONS.with(|counter| counter.set(Some(AllocationStats::default())));
    let result = operation();
    let stats = match ALLOCATIONS.with(Cell::take) {
        Some(stats) => stats,
        None => panic!("allocation measurement disappeared"),
    };
    drop(reset);
    (result, stats)
}

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(id) => id,
        Err(error) => panic!("invalid fixture ID: {error:?}"),
    }
}

struct Fixture {
    actions: Vec<TemporalEligibilityActionV1>,
    feedback: Vec<TemporalFeedbackV1>,
    groups: Vec<ParameterGroupMapV1>,
    contract: TemporalCreditContractV1,
}

fn fixture() -> Fixture {
    let scope = Digest32::of_bytes(b"allocation-probe-owner");
    let model = Digest32::of_bytes(b"allocation-probe-model");
    let source = Digest32::of_bytes(b"allocation-probe-source");
    let checkpoint = Digest32::of_bytes(b"allocation-probe-checkpoint");
    Fixture {
        actions: vec![TemporalEligibilityActionV1 {
            action_id: id("action:one"),
            owner_scope_digest: scope,
            model_digest: model,
            source_receipt_digest: source,
            action_checkpoint_digest: checkpoint,
            generation: 1,
            sequence: 1,
            split: TemporalSplitV1::Training,
            eligibility_q24: vec![Q],
        }],
        feedback: vec![TemporalFeedbackV1 {
            action_id: id("action:one"),
            owner_scope_digest: scope,
            model_digest: model,
            source_receipt_digest: source,
            action_checkpoint_digest: checkpoint,
            feedback_receipt_digest: Digest32::of_bytes(b"allocation-probe-feedback"),
            generation: 1,
            available_sequence: 2,
            split: TemporalSplitV1::Training,
            modulator_q24: vec![Q],
        }],
        groups: vec![ParameterGroupMapV1 {
            group_id: id("group:one"),
            eligibility_projection_q24: vec![Q],
            modulator_projection_q24: vec![Q],
        }],
        contract: TemporalCreditContractV1 {
            owner_scope_digest: scope,
            model_digest: model,
            generation: 1,
            cutoff_sequence: 2,
            maximum_feedback_lag: 8,
            decay_q24: Q / 2,
            trust_region: PlasticityTrustRegionV1 {
                learning_rate_q24: Q,
                maximum_group_delta_q24: Q,
                maximum_global_l1_q24: Q,
            },
        },
    }
}

fn check_bounded_refusal(
    fixture: &Fixture,
    expected: TemporalCreditError,
    case: &str,
    payload_bytes: usize,
) {
    let (actual, stats) = measured(|| {
        accumulate_temporal_credit_q24(
            &fixture.actions,
            &fixture.feedback,
            &fixture.groups,
            fixture.contract,
            TemporalCreditArmV1::Routed,
        )
    });
    let report = serde_json::json!({
        "schema": "hepta.plasticity.allocation-probe.v1",
        "case": case,
        "payload_bytes": payload_bytes,
        "requested_bytes": stats.requested_bytes,
        "largest_request": stats.largest_request,
        "limit_bytes": REJECTION_ALLOCATION_LIMIT,
        "refusal_matches": actual.as_ref().err() == Some(&expected),
        "within_budget": stats.requested_bytes < REJECTION_ALLOCATION_LIMIT,
    });
    println!("HEPTA_ALLOCATION_PROBE {report}");
    assert_eq!(actual, Err(expected));
    assert!(
        stats.requested_bytes < REJECTION_ALLOCATION_LIMIT,
        "rejecting a malformed payload allocated {stats:?}"
    );
}

#[test]
fn oversized_eligibility_projection_is_rejected_without_copying_payload() {
    for length in [4096, 8192] {
        let mut fixture = fixture();
        fixture.groups[0].eligibility_projection_q24 = vec![0; length];
        check_bounded_refusal(
            &fixture,
            TemporalCreditError::Projection(PlasticityError::ProjectionDimensionMismatch(
                "group:one".to_owned(),
            )),
            "eligibility_projection",
            length * size_of::<i64>(),
        );
    }
}

#[test]
fn oversized_modulator_projection_is_rejected_without_copying_payload() {
    for length in [4096, 8192] {
        let mut fixture = fixture();
        fixture.groups.push(ParameterGroupMapV1 {
            group_id: id("group:wide"),
            eligibility_projection_q24: vec![Q],
            modulator_projection_q24: vec![0; length],
        });
        check_bounded_refusal(
            &fixture,
            TemporalCreditError::Projection(PlasticityError::ProjectionDimensionMismatch(
                "group:wide".to_owned(),
            )),
            "modulator_projection",
            length * size_of::<i64>(),
        );
    }
}

#[test]
fn oversized_feedback_is_rejected_without_copying_payload() {
    for length in [4096, 8192] {
        let mut fixture = fixture();
        fixture.feedback[0].modulator_q24 = vec![0; length];
        check_bounded_refusal(
            &fixture,
            TemporalCreditError::InvalidFeedback,
            "feedback",
            length * size_of::<i64>(),
        );
    }
}
