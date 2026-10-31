//! Bounded research sessions around the unchanged original sparse_tick kernel.
//! Opaque integer handles own checkpoints, never production effects. DENY_ALL.

use std::collections::BTreeMap;
use std::panic::catch_unwind;
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use codex_hepta_neuron::{InhibitoryEdge, SparseCheckpoint, SparseConfig, SparseTick, sparse_tick};
use codex_hepta_types::{Digest32, Generation};

const Q: i64 = 1 << 24;
const WIDTH: usize = 20;
const FEATURES: usize = 8;
const MAX_SESSIONS: usize = 4096;
const MAX_TICKS: u64 = 6;

#[repr(C)]
pub struct OpenRequest {
    case: [u8; 256],
    case_len: u32,
}

#[repr(C)]
pub struct TickRequest {
    handle: u64,
    sequence: u64,
    logical_clock_micros: u64,
    readback: [u8; 32],
    features: [i64; FEATURES],
    feature_count: u32,
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
    logical_clock_micros: u64,
    bounded_bytes: u64,
    active_fraction_ppm: u32,
    projection_count: u32,
    requires_calibration: u32,
    grants_any: u32,
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

#[derive(Clone)]
struct Session {
    scope: Digest32,
    checkpoint: Option<SparseCheckpoint>,
    clock: u64,
}

struct Sessions {
    next_handle: u64,
    live: BTreeMap<u64, Session>,
}

fn sessions() -> &'static Mutex<Sessions> {
    static SESSIONS: OnceLock<Mutex<Sessions>> = OnceLock::new();
    SESSIONS.get_or_init(|| {
        Mutex::new(Sessions {
            next_handle: 1,
            live: BTreeMap::new(),
        })
    })
}

fn insert(table: &mut Sessions, session: Session) -> Result<u64, i32> {
    if table.live.len() >= MAX_SESSIONS {
        return Err(7);
    }
    let handle = table.next_handle;
    table.next_handle = handle.checked_add(1).ok_or(7)?;
    table.live.insert(handle, session);
    Ok(handle)
}

fn boundary(call: impl FnOnce() -> Result<(), i32>) -> i32 {
    match catch_unwind(std::panic::AssertUnwindSafe(call)) {
        Ok(Ok(())) => 0,
        Ok(Err(status)) => status,
        Err(_) => 5,
    }
}

fn valid<T>(pointer: *const T) -> bool {
    !pointer.is_null() && (pointer as usize).is_multiple_of(std::mem::align_of::<T>())
}

fn tick(request: &TickRequest) -> Result<TickOutput, i32> {
    let count = request.feature_count as usize;
    if !(1..=FEATURES).contains(&count)
        || request.features[..count]
            .iter()
            .any(|v| !(-Q..=Q).contains(v))
    {
        return Err(2);
    }
    let mut table = sessions().lock().map_err(|_| 5)?;
    let session = table.live.get_mut(&request.handle).ok_or(6)?;
    let sequence = session.checkpoint.as_ref().map_or(1, |c| c.sequence() + 1);
    if request.sequence != sequence
        || request.logical_clock_micros != session.clock + 1
        || request.logical_clock_micros > MAX_TICKS
    {
        return Err(8);
    }
    let mut drive = [0; WIDTH];
    for (index, value) in request.features[..count].iter().enumerate() {
        drive[2 * index] = (-value).max(0);
        drive[2 * index + 1] = (*value).max(0);
    }
    drive[2 * FEATURES] = Q / 4;
    let context = context();
    let input = SparseTick {
        scope_digest: session.scope,
        objective_digest: context.objective,
        ndu_digest: context.ndu,
        body_digest: context.body,
        input_digest: Digest32::of_parts(&[
            &request.readback,
            &(request.logical_clock_micros - 1).to_be_bytes(),
        ]),
        sequence,
        monotonic_micros: request.logical_clock_micros,
        drive_q24: drive.to_vec(),
        prediction_q24: vec![0; WIDTH],
    };
    let started = Instant::now();
    let (next, receipt) =
        sparse_tick(&context.config, &input, session.checkpoint.as_ref()).map_err(|_| 3)?;
    let native_ns = started.elapsed().as_nanos() as u64;
    if receipt.authority.grants_any() || !receipt.requires_calibration {
        return Err(4);
    }
    let mut output = TickOutput {
        drive,
        native_ns,
        sequence: next.sequence(),
        logical_clock_micros: request.logical_clock_micros,
        bounded_bytes: next.bounded_encoded_bytes() as u64,
        active_fraction_ppm: receipt.active_fraction_ppm,
        projection_count: receipt.projection_count,
        requires_calibration: u32::from(receipt.requires_calibration),
        grants_any: u32::from(receipt.authority.grants_any()),
        ..TickOutput::default()
    };
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
    // Publish only a fully validated next checkpoint; invalid requests are inert.
    session.checkpoint = Some(next);
    session.clock = request.logical_clock_micros;
    Ok(output)
}

#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_abi_version() -> u32 {
    3
}
#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_open_size() -> usize {
    std::mem::size_of::<OpenRequest>()
}
#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_request_size() -> usize {
    std::mem::size_of::<TickRequest>()
}
#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_response_size() -> usize {
    std::mem::size_of::<TickOutput>()
}
#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_live_sessions() -> usize {
    sessions()
        .lock()
        .map_or(usize::MAX, |table| table.live.len())
}

/// Caller buffers must be valid, aligned and nonoverlapping for the entire call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hepta_stream_open(input: *const OpenRequest, output: *mut u64) -> i32 {
    if !valid(input) || !valid(output) {
        return 1;
    }
    boundary(|| {
        let request = unsafe { &*input };
        let len = request.case_len as usize;
        if !(1..=256).contains(&len) || std::str::from_utf8(&request.case[..len]).is_err() {
            return Err(2);
        }
        let mut table = sessions().lock().map_err(|_| 5)?;
        let handle = insert(
            &mut table,
            Session {
                scope: Digest32::of_bytes(&request.case[..len]),
                checkpoint: None,
                clock: 0,
            },
        )?;
        unsafe {
            output.write(handle);
        }
        Ok(())
    })
}

/// Fork an exact complete checkpoint; scope and logical clock are preserved.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hepta_stream_fork(handle: u64, output: *mut u64) -> i32 {
    if !valid(output) {
        return 1;
    }
    boundary(|| {
        let mut table = sessions().lock().map_err(|_| 5)?;
        let session = table.live.get(&handle).ok_or(6)?.clone();
        let new_handle = insert(&mut table, session)?;
        unsafe {
            output.write(new_handle);
        }
        Ok(())
    })
}

/// Reset checkpoint state, retaining the bounded episode clock and scope.
#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_reset(handle: u64) -> i32 {
    boundary(|| {
        let mut table = sessions().lock().map_err(|_| 5)?;
        table.live.get_mut(&handle).ok_or(6)?.checkpoint = None;
        Ok(())
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn hepta_stream_close(handle: u64) -> i32 {
    boundary(|| {
        let mut table = sessions().lock().map_err(|_| 5)?;
        table.live.remove(&handle).ok_or(6)?;
        Ok(())
    })
}

/// Execute one tick. On failure neither checkpoint nor caller output is changed.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hepta_stream_tick(
    input: *const TickRequest,
    output: *mut TickOutput,
) -> i32 {
    if !valid(input) || !valid(output) {
        return 1;
    }
    boundary(|| {
        let result = tick(unsafe { &*input })?;
        unsafe {
            output.write(result);
        }
        Ok(())
    })
}
