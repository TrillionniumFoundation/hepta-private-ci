use std::env;
use std::error::Error;
use std::fs;
use std::hint::black_box;
use std::io;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_types::{
    ContractRegistryV1, MAX_REGISTRY_ENTRIES_V1, RegistryDefinitionV1, RegistryKindV1,
    StableId,
};

#[derive(Clone, Copy)]
struct BenchmarkResult {
    entry_count: usize,
    construction_elapsed_ns: u128,
    identity_elapsed_ns: u128,
    digest_elapsed_ns: u128,
    registry_identity_elapsed_ns: u128,
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}

fn parse_arguments() -> Result<(u64, PathBuf), Box<dyn Error>> {
    let mut arguments = env::args().skip(1);
    let iterations = arguments
        .next()
        .ok_or(invalid_input("iterations argument is required"))?
        .parse::<u64>()?;
    if iterations == 0 {
        return Err(invalid_input("iterations must be positive").into());
    }
    let output = arguments
        .next()
        .map(PathBuf::from)
        .ok_or(invalid_input("output path argument is required"))?;
    if arguments.next().is_some() {
        return Err(invalid_input("unexpected extra benchmark arguments").into());
    }
    Ok((iterations, output))
}

fn benchmark_case(
    entry_count: usize,
    iterations: u64,
) -> Result<BenchmarkResult, Box<dyn Error>> {
    let mut entries = Vec::with_capacity(entry_count);
    for index in 0..entry_count {
        let id = StableId::new(format!("schema:benchmark-{index}"))?;
        entries.push(RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            id,
            1,
            &format!("field=value-{index}:u64"),
        )?);
    }

    let target = entries[entry_count / 2].clone();
    let target_id = target.id().clone();
    let target_digest = target.digest();
    let construction_started = Instant::now();
    let registry = ContractRegistryV1::new(entries)?;
    let construction_elapsed_ns = construction_started.elapsed().as_nanos();

    let identity_started = Instant::now();
    for _ in 0..iterations {
        let Some(resolved) = registry.resolve(RegistryKindV1::Schema, &target_id, 1) else {
            return Err(invalid_input("identity lookup unexpectedly failed").into());
        };
        black_box(resolved);
    }
    let identity_elapsed_ns = identity_started.elapsed().as_nanos();

    let digest_started = Instant::now();
    for _ in 0..iterations {
        let Some(resolved) = registry.resolve_digest(RegistryKindV1::Schema, target_digest) else {
            return Err(invalid_input("digest lookup unexpectedly failed").into());
        };
        black_box(resolved);
    }
    let digest_elapsed_ns = digest_started.elapsed().as_nanos();

    let registry_identity_started = Instant::now();
    for _ in 0..iterations {
        black_box(registry.registry_digest()?);
    }
    let registry_identity_elapsed_ns = registry_identity_started.elapsed().as_nanos();

    Ok(BenchmarkResult {
        entry_count,
        construction_elapsed_ns,
        identity_elapsed_ns,
        digest_elapsed_ns,
        registry_identity_elapsed_ns,
    })
}

fn main() -> Result<(), Box<dyn Error>> {
    let (iterations, output) = parse_arguments()?;
    let results = [8, MAX_REGISTRY_ENTRIES_V1]
        .into_iter()
        .map(|entry_count| benchmark_case(entry_count, iterations))
        .collect::<Result<Vec<_>, _>>()?;
    let divisor = u128::from(iterations);
    let rows = results
        .iter()
        .map(|result| {
            format!(
                "    {{\"entryCount\":{},\"constructionElapsedNs\":{},\"constructionNsPerEntry\":{},\"identityElapsedNs\":{},\"identityNsPerLookup\":{},\"digestElapsedNs\":{},\"digestNsPerLookup\":{},\"registryIdentityElapsedNs\":{},\"registryIdentityNsPerLookup\":{}}}",
                result.entry_count,
                result.construction_elapsed_ns,
                result.construction_elapsed_ns / result.entry_count as u128,
                result.identity_elapsed_ns,
                result.identity_elapsed_ns / divisor,
                result.digest_elapsed_ns,
                result.digest_elapsed_ns / divisor,
                result.registry_identity_elapsed_ns,
                result.registry_identity_elapsed_ns / divisor,
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    let document = format!(
        "{{\n  \"schema\": \"hepta.platform-types.registry-lookup-benchmark.v1\",\n  \"schemaVersion\": 1,\n  \"iterationsPerLookup\": {iterations},\n  \"acceptanceThreshold\": null,\n  \"claimBoundary\": \"same-candidate measurement only; no target-host threshold or release claim\",\n  \"cases\": [\n{rows}\n  ]\n}}\n"
    );
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&output, document)?;
    println!(
        "platform.types registry benchmark: {} iterations, {} cases, output={}",
        iterations,
        results.len(),
        output.display()
    );
    Ok(())
}
