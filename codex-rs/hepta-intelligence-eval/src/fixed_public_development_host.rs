//! The same G MainPID performs a closed, keyless public measurement before a
//! first prediction artifact exists. It cannot freeze, sign or consume a plan.
use crate::fixed_paired_generator_host::actual_generator;
use crate::fixed_paired_generator_host::actual_limits;
use crate::fixed_paired_generator_host::sample;
use crate::paired_development_transport::Encoder;
use crate::paired_development_transport::PURPOSE;
use crate::paired_development_transport::Response;
use crate::paired_development_transport::Source;
use crate::paired_development_transport::measure;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    uid: u32,
    gid: u32,
    program_digest: String,
    root_verifying_key_hex: String,
    source: Source,
    inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Pair {
    pair_id: String,
    source_row_sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inputs {
    schema: String,
    purpose: String,
    trust: ReviewTrustWireV1,
    encoder: Encoder,
    batch_id: String,
    pairs: Vec<Pair>,
    timeout_ms: u64,
}
impl Inputs {
    fn validate(&self) -> Result<()> {
        if self.schema != "hepta.eval.public-development.measurement-inputs.v1"
            || self.purpose != PURPOSE
            || self.batch_id.is_empty()
            || self.batch_id.len() > 256
            || !(1..=120_000).contains(&self.timeout_ms)
            || !(1..=256).contains(&self.pairs.len())
        {
            return Err("closed first public development batch policy".into());
        }
        let mut pairs = BTreeSet::new();
        let mut records = BTreeSet::new();
        for pair in &self.pairs {
            let digest = pair.source_row_sha256.parse::<Digest32>()?;
            if pair.pair_id.is_empty()
                || pair.pair_id.len() > 256
                || digest.is_zero()
                || !pairs.insert(&pair.pair_id)
                || !records.insert(digest)
            {
                return Err("distinct exact public feature identities required".into());
            }
        }
        Ok(())
    }
}
/// Measure the Root-predeclared public rows as the actual bounded G MainPID.
/// Output is raw measurement provenance, never learning evidence or authority.
pub fn run_fixed_public_development_measurement(path: &Path) -> Result<()> {
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-public-development-measurement-config.v1"
        || config.uid == 0
        || config.uid != config.gid
        || config.inaccessible_paths.len() != 5
        || config
            .inaccessible_paths
            .iter()
            .collect::<BTreeSet<_>>()
            .len()
            != 5
    {
        return Err("fixed keyless public G Root policy".into());
    }
    let cgroup = crate::fixed_calibration_host::boundary_in_service(
        config.uid,
        config.gid,
        "hepta-native-generator-",
    )?;
    actual_limits(&cgroup)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if program != config.program_digest.parse::<Digest32>()? {
        return Err("actual immutable public G program changed".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("G has custody/another role access or no physical denial".into()),
        }
    }
    let source_bytes = config.source.read(2 * 1024 * 1024)?;
    let inputs: Inputs = serde_json::from_slice(&source_bytes)?;
    inputs.validate()?;
    if inputs.trust.root_verifying_key_hex != config.root_verifying_key_hex {
        return Err("actual original Root public trust pin".into());
    }
    let (root, distribution) = inputs.trust.native()?;
    let signer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| signer.principal.principal_id.as_str() == "native-unprivileged-generator")
        .ok_or("original G admission absent")?;
    actual_generator(signer, program, config.uid, &root.verifying_key)?;
    let trust = activate_learning_trust(
        &root,
        distribution,
        None,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    let mut last = None;
    let measured_at_ms = sample(&trust, &mut last)?;
    let started = Instant::now();
    let expiry_remaining = trust
        .expires_at()
        .checked_sub(measured_at_ms)
        .ok_or("original G distribution expired")?;
    let budget = Duration::from_millis(inputs.timeout_ms.min(expiry_remaining));
    let deadline = started
        .checked_add(budget)
        .ok_or("original public batch budget overflow")?;
    let mut measurements: Vec<Response> = Vec::with_capacity(inputs.pairs.len());
    for pair in &inputs.pairs {
        sample(&trust, &mut last)?;
        measurements.push(measure(
            &inputs.encoder,
            &inputs.batch_id,
            &pair.pair_id,
            &pair.source_row_sha256,
            config.uid,
            deadline,
        )?);
    }
    if Instant::now() >= deadline
        || config.source.read(2 * 1024 * 1024)? != source_bytes
        || read_root_review_input(path, 32 * 1024)? != config_bytes
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != program
    {
        return Err("original public measurement source/program/budget changed".into());
    }
    actual_limits(&crate::fixed_calibration_host::boundary_in_service(
        config.uid,
        config.gid,
        "hepta-native-generator-",
    )?)?;
    let completed_at_ms = sample(&trust, &mut last)?;
    println!(
        "{}",
        serde_json::json!({
            "schema":"hepta.eval.public-development.measurement-source.v1",
            "purpose":PURPOSE,"batch_id":inputs.batch_id,
            "program_digest":program.to_string(),"config_digest":Digest32::of_bytes(&config_bytes).to_string(),
            "source_digest":Digest32::of_bytes(&source_bytes).to_string(),
            "measured_at_ms":measured_at_ms,"completed_at_ms":completed_at_ms,
            "monotonic_elapsed_micros":started.elapsed().as_micros(),"measurements":measurements,
            "learning_evidence_signed":false,"plan_frozen":false,"holdout_consumed":false,
            "qualification":false,"production_activation":false,
        })
    );
    Ok(())
}

#[cfg(test)]
#[path = "fixed_public_development_host_tests.rs"]
mod tests;
