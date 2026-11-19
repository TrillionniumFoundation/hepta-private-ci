//! Paired same-process allocation/timing diagnostics over the actual public API.
//! No runtime owner, service, credential, or execution authority is introduced.
use std::error::Error;
use std::hint::black_box;
use std::time::Instant;

use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::NumericProfileDefinitionV1;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalSchemaV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::RegistryDefinitionV1;
use codex_hepta_types::RegistryKindV1;
use codex_hepta_types::SignalUnitV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;
use codex_hepta_types::canonical_encode_v1;
use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_v2;

#[path = "semantic_bench_support/allocator.rs"]
mod allocator;

#[global_allocator]
static ALLOCATOR: allocator::TrafficAllocator = allocator::TrafficAllocator;

const SAMPLES: usize = 17;
const ITERATIONS: usize = 64;
type Failure = Box<dyn Error>;

fn measure<T>(
    name: &str,
    sample: usize,
    operation: &mut impl FnMut() -> Result<T, Failure>,
) -> Result<String, Failure> {
    let measurement = allocator::Measurement::start();
    let started = Instant::now();
    for _ in 0..ITERATIONS {
        drop(black_box(operation()?));
    }
    let elapsed = started.elapsed().as_nanos();
    let (calls, reallocations, bytes) = measurement.finish();
    Ok(format!(
        "{{\"case\":\"{name}\",\"sample\":{sample},\"iterations\":{ITERATIONS},\"elapsedNs\":{elapsed},\"allocationCalls\":{calls},\"reallocations\":{reallocations},\"requestedBytes\":{bytes}}}"
    ))
}

fn repeat<T>(
    rows: &mut Vec<String>,
    name: &str,
    mut operation: impl FnMut() -> Result<T, Failure>,
) -> Result<(), Failure> {
    // Warm lazy implementation/CPU feature initialization outside measurement.
    for _ in 0..8 {
        drop(black_box(operation()?));
    }
    for sample in 0..SAMPLES {
        rows.push(measure(name, sample, &mut operation)?);
    }
    Ok(())
}

fn hash_cases(rows: &mut Vec<String>) -> Result<(), Failure> {
    let id = StableId::new("platform.types:semantic-benchmark-v1")?;
    for length in [8, 4096, 65536] {
        let payload = vec![0x5a; length];
        let fields = [CanonicalFieldV1 {
            name: "payload",
            value: CanonicalValueV1::Bytes(&payload),
        }];
        let expected = Digest32::of_bytes(&canonical_encode_v1(
            &id, /*schema_version*/ 1, &fields,
        )?);
        let mut buffered = || -> Result<_, Failure> {
            let encoded = canonical_encode_v1(
                black_box(&id),
                /*schema_version*/ 1,
                black_box(&fields),
            )?;
            let digest = Digest32::of_bytes(&encoded);
            if digest != expected {
                return Err("buffered digest changed".into());
            }
            Ok(digest)
        };
        let mut streaming = || -> Result<_, Failure> {
            let digest = canonical_digest_v1(
                black_box(&id),
                /*schema_version*/ 1,
                black_box(&fields),
            )?;
            if digest != expected {
                return Err("streaming digest changed".into());
            }
            Ok(digest)
        };
        for _ in 0..8 {
            let _ = black_box(buffered()?);
            let _ = black_box(streaming()?);
        }
        let buffered_name = format!("hash-buffered-{length}");
        let streaming_name = format!("hash-streaming-{length}");
        // Alternate ordering so thermal/frequency drift does not always favor
        // one implementation. Timing remains diagnostic on a shared runner.
        for sample in 0..SAMPLES {
            if sample % 2 == 0 {
                rows.push(measure(&buffered_name, sample, &mut buffered)?);
                rows.push(measure(&streaming_name, sample, &mut streaming)?);
            } else {
                rows.push(measure(&streaming_name, sample, &mut streaming)?);
                rows.push(measure(&buffered_name, sample, &mut buffered)?);
            }
        }
    }
    Ok(())
}

fn registry_cases(rows: &mut Vec<String>) -> Result<(), Failure> {
    for count in [8, 256] {
        let entries = (0..count)
            .map(|index| {
                RegistryDefinitionV1::new(
                    RegistryKindV1::Schema,
                    StableId::new(format!("schema:resource-{index}"))?,
                    /*version*/ 1,
                    "value:u64",
                )
                .map_err(Failure::from)
            })
            .collect::<Result<Vec<_>, Failure>>()?;
        repeat(rows, &format!("registry-construct-{count}"), || {
            Ok(ContractRegistryV1::new(black_box(entries.clone()))?)
        })?;
        let registry = ContractRegistryV1::new(entries)?;
        let target = &registry.entries()[count / 2];
        repeat(rows, &format!("registry-identity-{count}"), || {
            registry
                .resolve(
                    RegistryKindV1::Schema,
                    black_box(target.id()),
                    /*version*/ 1,
                )
                .map(RegistryDefinitionV1::digest)
                .ok_or_else(|| "identity lookup failed".into())
        })?;
        repeat(rows, &format!("registry-digest-{count}"), || {
            registry
                .resolve_digest(RegistryKindV1::Schema, black_box(target.digest()))
                .map(RegistryDefinitionV1::digest)
                .ok_or_else(|| "digest lookup failed".into())
        })?;
    }
    Ok(())
}

fn numeric_cases(rows: &mut Vec<String>) -> Result<(), Failure> {
    let normalization = RegistryDefinitionV1::new(
        RegistryKindV1::Normalization,
        StableId::new("normalization:resource-benchmark")?,
        /*version*/ 1,
        "identity",
    )?;
    let normalization_digest = normalization.digest();
    let registry = ContractRegistryV1::new_with_numeric_profiles(
        vec![normalization],
        vec![
            NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)?,
            NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ24NearestTiesEven)?,
        ],
    )?;
    let generation = Generation::new(7)?;
    for count in [8, 4096] {
        let source = NumericSignalV1 {
            schema: NumericSignalSchemaV1 {
                profile: NumericProfileV1::HnmfPpmTowardZero,
                unit: SignalUnitV1::Utility,
                shape: vec![count],
                minimum_raw: -1_000_000,
                maximum_raw: 1_000_000,
                normalization_digest,
            },
            values: vec![125_001; count],
        };
        let target = NumericSignalSchemaV1 {
            profile: NumericProfileV1::SignedQ24NearestTiesEven,
            minimum_raw: -(1_i64 << 24),
            maximum_raw: 1_i64 << 24,
            ..source.schema.clone()
        };
        let (_, receipt) = rescale_signal_registered_v2(&source, &target, &registry, generation)?;
        let snapshot = receipt.registry_snapshot();
        repeat(rows, &format!("numeric-convert-{count}"), || {
            Ok(rescale_signal_registered_v2(
                black_box(&source),
                &target,
                &registry,
                generation,
            )?)
        })?;
        repeat(rows, &format!("numeric-verify-{count}"), || {
            Ok(receipt.verify_for_snapshot(black_box(&source), &target, &registry, snapshot)?)
        })?;
    }
    Ok(())
}

fn main() -> Result<(), Failure> {
    let mut arguments = std::env::args().skip(1);
    let output = arguments.next().ok_or("output path required")?;
    if arguments.next().is_some() {
        return Err("only one output path is accepted".into());
    }
    let mut rows = Vec::new();
    hash_cases(&mut rows)?;
    registry_cases(&mut rows)?;
    numeric_cases(&mut rows)?;
    let document = format!(
        "{{\"schema\":\"hepta.platform-types.semantic-benchmark.v1\",\"samplesPerCase\":{SAMPLES},\"iterationsPerSample\":{ITERATIONS},\"allocationMetric\":\"successful-global-allocation-and-reallocation-requested-bytes\",\"timingAuthority\":\"diagnostic-only\",\"rows\":[{}]}}\n",
        rows.join(",\n")
    );
    std::fs::write(output, document)?;
    Ok(())
}
