//! Bounded research C ABI for the unchanged pinned Hepta sparse_tick kernel.
//! Callers own valid, aligned input/output buffers. No pointers are retained.
//! Authority remains DENY_ALL. This is not a production effect-owner interface.

use std::panic::catch_unwind;
use std::sync::OnceLock;
use std::time::Instant;

use codex_hepta_neuron::{InhibitoryEdge, SparseConfig, SparseTick, sparse_tick};
use codex_hepta_types::{Digest32, Generation};

const Q: i64 = 1 << 24;
const WIDTH: usize = 20;
const FEATURES: usize = 8;

#[repr(C)]
pub struct Request {
    case: [u8; 256],
    readback: [u8; 32],
    first: [i64; FEATURES],
    second: [i64; FEATURES],
    case_len: u32,
    feature_count: u32,
    next_present: u32,
    reset: u32,
}

#[derive(Clone, Copy, Default)]
#[repr(C)]
pub struct TickOutput {
    drive: [i64; WIDTH],
    activation: [i64; WIDTH],
    eligibility: [i64; WIDTH],
    threshold: [i64; WIDTH],
    // before, after, temporal, activation, eligibility, config, input
    digests: [[u8; 32]; 7],
    native_ns: u64,
    sequence: u64,
    bounded_bytes: u64,
    active_fraction_ppm: u32,
    projection_count: u32,
    requires_calibration: u32,
    grants_any: u32,
}

#[derive(Default)]
#[repr(C)]
pub struct Response {
    ticks: [TickOutput; 2],
    ffi_run_ns: u64,
}

struct Context {
    config: SparseConfig,
    objective: Digest32,
    ndu: Digest32,
    body: Digest32,
}

fn context() -> &'static Context {
    static CONTEXT: OnceLock<Context> = OnceLock::new();
    CONTEXT.get_or_init(|| Context {
        config: SparseConfig {
            model_digest: Digest32::of_bytes(
                b"hepta.parameter-field-bridge.signed-eight-channel.v1",
            ),
            normalization_digest: Digest32::of_bytes(b"q24.public-observations.unit-interval.v1"),
            generation: Generation::new(1).expect("one is a valid generation"),
            width: WIDTH,
            top_k: 4,
            temporal_decay_q24: 3 * Q / 4,
            inhibition_gain_q24: Q / 4,
            inhibition: (0..FEATURES)
                .flat_map(|index| {
                    [
                        InhibitoryEdge {
                            source: 2 * index,
                            target: 2 * index + 1,
                            weight_q24: Q / 2,
                        },
                        InhibitoryEdge {
                            source: 2 * index + 1,
                            target: 2 * index,
                            weight_q24: Q / 2,
                        },
                    ]
                })
                .collect(),
            activity_decay_q24: 3 * Q / 4,
            target_activity_q24: Q / 5,
            threshold_rate_q24: Q / 64,
            threshold_min_q24: 0,
            threshold_max_q24: Q / 2,
            eligibility_decay_q24: Q / 2,
        },
        objective: Digest32::of_bytes(b"hepta.parameter-field-bridge.fixed-observed-outcome.v1"),
        ndu: Digest32::of_bytes(b"target-free-research-features-not-full-NDU.v1"),
        body: Digest32::of_bytes(b"original-sparse-kernel.fixed-research-profile.v1"),
    })
}

fn run(request: &Request) -> Result<Response, i32> {
    let started = Instant::now();
    let count = request.feature_count as usize;
    let case_len = request.case_len as usize;
    if !(1..=FEATURES).contains(&count)
        || !(1..=256).contains(&case_len)
        || request.next_present > 1
        || request.reset > 1
        || std::str::from_utf8(&request.case[..case_len]).is_err()
        || request.first[..count].iter().any(|v| !(-Q..=Q).contains(v))
        || (request.next_present == 1
            && request.second[..count]
                .iter()
                .any(|v| !(-Q..=Q).contains(v)))
    {
        return Err(2);
    }
    let context = context();
    let scope = Digest32::of_bytes(&request.case[..case_len]);
    let mut state = None;
    let mut response = Response::default();
    for stage in 0..2 {
        if stage == 1 && request.reset == 1 {
            state = None;
        }
        let features = match stage {
            0 => Some(&request.first),
            1 if request.next_present == 1 => Some(&request.second),
            _ => None,
        };
        let mut drive = [0; WIDTH];
        if let Some(features) = features {
            for (index, value) in features[..count].iter().enumerate() {
                drive[2 * index] = (-value).max(0);
                drive[2 * index + 1] = (*value).max(0);
            }
            drive[2 * FEATURES] = Q / 4;
        }
        let sequence = if stage == 0 || request.reset == 1 {
            1
        } else {
            2
        };
        let input = SparseTick {
            scope_digest: scope,
            objective_digest: context.objective,
            ndu_digest: context.ndu,
            body_digest: context.body,
            input_digest: Digest32::of_parts(&[&request.readback, &(stage as u64).to_be_bytes()]),
            sequence,
            monotonic_micros: stage as u64 + 1,
            drive_q24: drive.to_vec(),
            prediction_q24: vec![0; WIDTH],
        };
        let tick_started = Instant::now();
        let (next, receipt) =
            sparse_tick(&context.config, &input, state.as_ref()).map_err(|_| 3)?;
        let native_ns = tick_started.elapsed().as_nanos() as u64;
        if receipt.authority.grants_any() || !receipt.requires_calibration {
            return Err(4);
        }
        let output = &mut response.ticks[stage];
        output.drive = drive;
        output.activation.copy_from_slice(&receipt.activation_q24);
        output.eligibility.copy_from_slice(next.eligibility_q24());
        output.threshold.copy_from_slice(next.thresholds_q24());
        output.digests = [
            receipt.checkpoint_before.into_array(),
            receipt.checkpoint_after.into_array(),
            next.temporal_state_digest().into_array(),
            next.activation_digest().into_array(),
            next.eligibility_digest().into_array(),
            receipt.config_digest.into_array(),
            receipt.input_digest.into_array(),
        ];
        output.native_ns = native_ns;
        output.sequence = next.sequence();
        output.bounded_bytes = next.bounded_encoded_bytes() as u64;
        output.active_fraction_ppm = receipt.active_fraction_ppm;
        output.projection_count = receipt.projection_count;
        output.requires_calibration = u32::from(receipt.requires_calibration);
        output.grants_any = u32::from(receipt.authority.grants_any());
        state = Some(next);
    }
    response.ffi_run_ns = started.elapsed().as_nanos() as u64;
    Ok(response)
}

#[unsafe(no_mangle)]
pub extern "C" fn hepta_field_abi_version() -> u32 {
    2
}

#[unsafe(no_mangle)]
pub extern "C" fn hepta_field_request_size() -> usize {
    std::mem::size_of::<Request>()
}

#[unsafe(no_mangle)]
pub extern "C" fn hepta_field_response_size() -> usize {
    std::mem::size_of::<Response>()
}

/// Execute two events atomically; on failure the caller's output is unchanged.
///
/// # Safety
/// Non-null pointers must refer to aligned, initialized Request and writable
/// Response buffers for the entire call. Buffers must not overlap. This bounded
/// research API rejects malformed values, but cannot validate arbitrary memory.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hepta_field_tick_pair(
    input: *const Request,
    output: *mut Response,
) -> i32 {
    if input.is_null()
        || output.is_null()
        || !(input as usize).is_multiple_of(std::mem::align_of::<Request>())
        || !(output as usize).is_multiple_of(std::mem::align_of::<Response>())
    {
        return 1;
    }
    let result = catch_unwind(|| run(unsafe { &*input }));
    match result {
        Ok(Ok(response)) => {
            unsafe {
                output.write(response);
            }
            0
        }
        Ok(Err(status)) => status,
        Err(_) => 5,
    }
}
