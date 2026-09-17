//! CI performance gate for the authenticated intuition-policy fast path.
//!
//! The global allocator below is benchmark-only instrumentation. The library
//! remains `#![forbid(unsafe_code)]`; unsafe calls are confined to transparent
//! delegation to `System` so the gate can report allocation counts/bytes for
//! the measured decision call.

#![allow(unsafe_code)]

use std::alloc::{GlobalAlloc, Layout, System};
use std::error::Error;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::AuthenticatedCalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CalibrationQualificationPayloadV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CompletenessQualificationPayloadV1;
use codex_hepta_intuition::LearnedScorerDescriptorV1;
use codex_hepta_intuition::LearnedScorerOutputBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::OodQualificationPayloadV1;
use codex_hepta_intuition::QualificationArtifactKindV1;
use codex_hepta_intuition::QualificationArtifactVerifierV1;
use codex_hepta_intuition::QualificationSignatureV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::SignedCalibrationQualificationV1;
use codex_hepta_intuition::SignedCompletenessQualificationV1;
use codex_hepta_intuition::SignedOodQualificationV1;
use codex_hepta_intuition::SignedPolicyProfileV1;
use codex_hepta_intuition::canonical_calibration_qualification_digest_v1;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_qualification_digest_v1;
use codex_hepta_intuition::canonical_learned_scorer_descriptor_digest_v1;
use codex_hepta_intuition::canonical_ood_qualification_digest_v1;
use codex_hepta_intuition::canonical_policy_profile_artifact_digest_v1;
use codex_hepta_intuition::canonical_scorer_predictions_digest_v1;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_intuition::qualification_signature_message_v1;
use codex_hepta_types::{Digest32, FixedQ32, ProbabilityQ32, StableId};
use ed25519_dalek::{Signer as _, SigningKey};

struct CountingAllocator;
static ALLOCATION_COUNT: AtomicU64 = AtomicU64::new(0);
static ALLOCATION_BYTES: AtomicU64 = AtomicU64::new(0);

// SAFETY: every allocation method delegates the exact pointer/layout contract to System.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(
            u64::try_from(layout.size()).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
        // SAFETY: this allocator transparently delegates the exact layout to System.
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(
            u64::try_from(layout.size()).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
        // SAFETY: this allocator transparently delegates the exact layout to System.
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(
            u64::try_from(new_size).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
        // SAFETY: ptr/layout originate from System and new_size is forwarded unchanged.
        unsafe { System.realloc(ptr, layout, new_size) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: ptr/layout originate from the delegated System allocator.
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

const SIGNER_EPOCH: u64 = 7;
const WARMUP_ITERATIONS: usize = 25;
const MEASURED_ITERATIONS: usize = 250;
const P50_MAX_US: u128 = 10_000;
const P95_MAX_US: u128 = 15_000;
const P99_MAX_US: u128 = 25_000;
const MIN_THROUGHPUT_PER_SECOND: u128 = 40;
const P99_ALLOCATION_BYTES_MAX: u64 = 1_048_576;
const P99_ALLOCATION_COUNT_MAX: u64 = 4_096;

fn main() -> Result<(), Box<dyn Error>> {
    for count in [1usize, 16, 64, 128] {
        run_gate(count)?;
    }
    Ok(())
}

fn run_gate(candidate_count: usize) -> Result<(), Box<dyn Error>> {
    let (request, verifier) = authenticated_fixture(candidate_count)?;
    for _ in 0..WARMUP_ITERATIONS {
        let _ = decide_calibrated_v3(request.clone(), &verifier)?;
    }

    let mut latency_ns = Vec::with_capacity(MEASURED_ITERATIONS);
    let mut allocation_counts = Vec::with_capacity(MEASURED_ITERATIONS);
    let mut allocation_bytes = Vec::with_capacity(MEASURED_ITERATIONS);
    for _ in 0..MEASURED_ITERATIONS {
        let owned_request = request.clone();
        reset_allocations();
        let started = Instant::now();
        let receipt = decide_calibrated_v3(owned_request, &verifier)?;
        let elapsed = started.elapsed();
        let (count, bytes) = allocation_snapshot();
        if receipt.decision.propensities.len() != candidate_count {
            return Err("benchmark receipt candidate count drift".into());
        }
        latency_ns.push(elapsed.as_nanos());
        allocation_counts.push(count);
        allocation_bytes.push(bytes);
    }
    let total_measured_ns = latency_ns.iter().copied().sum::<u128>().max(1);

    latency_ns.sort_unstable();
    allocation_counts.sort_unstable();
    allocation_bytes.sort_unstable();
    let p50_us = percentile_u128(&latency_ns, 50) / 1_000;
    let p95_us = percentile_u128(&latency_ns, 95) / 1_000;
    let p99_us = percentile_u128(&latency_ns, 99) / 1_000;
    let p99_allocations = percentile_u64(&allocation_counts, 99);
    let p99_allocation_bytes = percentile_u64(&allocation_bytes, 99);
    let iterations = u128::try_from(MEASURED_ITERATIONS)?;
    let throughput = (iterations * 1_000_000_000) / total_measured_ns;

    println!(
        "intuition_fast_gate candidates={candidate_count} p50_us={p50_us} p95_us={p95_us} \
         p99_us={p99_us} throughput_per_s={throughput} allocations_p99={p99_allocations} \
         allocation_bytes_p99={p99_allocation_bytes}"
    );

    if p50_us > P50_MAX_US
        || p95_us > P95_MAX_US
        || p99_us > P99_MAX_US
        || throughput < MIN_THROUGHPUT_PER_SECOND
        || p99_allocations > P99_ALLOCATION_COUNT_MAX
        || p99_allocation_bytes > P99_ALLOCATION_BYTES_MAX
    {
        return Err(format!(
            "intuition fast gate failed for {candidate_count} candidates: \
             p50={p50_us}us p95={p95_us}us p99={p99_us}us throughput={throughput}/s \
             allocs_p99={p99_allocations} bytes_p99={p99_allocation_bytes}"
        )
        .into());
    }
    Ok(())
}

fn reset_allocations() {
    ALLOCATION_COUNT.store(0, Ordering::Relaxed);
    ALLOCATION_BYTES.store(0, Ordering::Relaxed);
}

fn allocation_snapshot() -> (u64, u64) {
    (
        ALLOCATION_COUNT.load(Ordering::Relaxed),
        ALLOCATION_BYTES.load(Ordering::Relaxed),
    )
}

fn percentile_u128(values: &[u128], percentile: usize) -> u128 {
    values[(values.len() - 1) * percentile / 100]
}

fn percentile_u64(values: &[u64], percentile: usize) -> u64 {
    values[(values.len() - 1) * percentile / 100]
}

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

fn digest(value: impl AsRef<[u8]>) -> Digest32 {
    Digest32::of_bytes(value.as_ref())
}

fn probability_ppm(ppm: u32) -> Result<ProbabilityQ32, Box<dyn Error>> {
    let one = u128::from(ProbabilityQ32::ONE.raw());
    let raw = (u128::from(ppm) * one + 500_000) / 1_000_000;
    Ok(ProbabilityQ32::from_raw(u64::try_from(raw)?)?)
}

fn sign(
    signing_key: &SigningKey,
    kind: QualificationArtifactKindV1,
    artifact_digest: Digest32,
) -> Result<QualificationSignatureV1, Box<dyn Error>> {
    let signer_id = id("qualification:intuition-fast-gate")?;
    let message = qualification_signature_message_v1(
        kind,
        artifact_digest,
        &signer_id,
        SIGNER_EPOCH,
    )?;
    Ok(QualificationSignatureV1 {
        signer_id,
        signer_epoch: SIGNER_EPOCH,
        signature: signing_key.sign(&message).to_bytes().to_vec(),
    })
}

include!("intuition-fast-gate-fixture.rs");
