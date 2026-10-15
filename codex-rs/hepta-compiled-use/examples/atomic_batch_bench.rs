//! Actual Rust CPU microbenchmark of fixed-frame verification and bounded queue.
//! NO OS effects, native code emission, GPU launch, MCP comparison, or permissions.
use std::hint::black_box;
use std::time::Instant;

use codex_hepta_compiled_use::{
    ActionArgumentsV1, ActionFrameV1, ActionVerifierV1, CapabilityGrantV1, SharedMemoryQueueV1,
};
use codex_hepta_types::Digest32;

fn frames() -> (ActionVerifierV1, Vec<ActionFrameV1>) {
    let grant = CapabilityGrantV1 {
        digest: Digest32::of_bytes(b"hepta-fastcell-microbench-grant"),
        allowed: 1 | 2 | 4 | 8 | 16,
    };
    let verifier = ActionVerifierV1 {
        generation: 7,
        grant,
    };
    let frames = (1..=32)
        .map(|sequence| ActionFrameV1 {
            generation: 7,
            sequence,
            capability_digest: grant.digest,
            arguments: ActionArgumentsV1::Click {
                target_digest: Digest32::of_bytes(b"bounded-element"),
                x: 2,
                y: 3,
            },
        })
        .collect();
    (verifier, frames)
}

fn samples(
    verifier: ActionVerifierV1,
    frames: &[ActionFrameV1],
    batch: bool,
    count: usize,
) -> Result<Vec<u128>, Box<dyn std::error::Error>> {
    let mut times = Vec::with_capacity(count);
    for _ in 0..count {
        let started = Instant::now();
        let mut queue = SharedMemoryQueueV1::new(verifier, 64)?;
        if batch {
            queue.push_batch(frames)?;
        } else {
            for frame in frames {
                queue.push(frame.clone())?;
            }
        }
        let mut digest_xor = 0_u64;
        for _ in frames {
            let bound = queue.pop()?;
            digest_xor ^= bound.frame().sequence;
        }
        black_box(digest_xor);
        times.push(started.elapsed().as_nanos());
    }
    Ok(times)
}

fn quantiles(values: &mut [u128]) -> (u128, u128, u128) {
    values.sort_unstable();
    let at = |numerator: usize| {
        let index = ((values.len() - 1) * numerator) / 100;
        values[index]
    };
    (at(50), at(95), at(99))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (verifier, actions) = frames();
    let count = if std::env::args().any(|arg| arg == "--smoke") {
        64
    } else {
        1024
    };
    samples(verifier, &actions, false, 32)?;
    samples(verifier, &actions, true, 32)?;
    let scalar = quantiles(&mut samples(verifier, &actions, false, count)?);
    let batch = quantiles(&mut samples(verifier, &actions, true, count)?);
    println!(
        "{{\"schema\":\"hepta.fastcell.native-batch-microbench.v1\",\"iterations\":{count},\"frames_per_iteration\":{},\"scalar_p50_ns\":{},\"scalar_p95_ns\":{},\"scalar_p99_ns\":{},\"batch_p50_ns\":{},\"batch_p95_ns\":{},\"batch_p99_ns\":{},\"external_effects\":false,\"production_accepted\":false}}",
        actions.len(),
        scalar.0,
        scalar.1,
        scalar.2,
        batch.0,
        batch.1,
        batch.2,
    );
    Ok(())
}
