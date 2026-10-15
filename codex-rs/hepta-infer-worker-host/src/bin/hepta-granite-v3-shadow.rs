//! A non-authorizing, research-only command-line acceptance test for one
//! independently reviewed frozen Granite97 export and bounded Cell Head set.
//!
//! This binary NEVER fetches/loads model weights, authenticates physical work,
//! grants model use or invokes tool/runtime effects. The four immutable local
//! inputs must come from an independent admission owner; data consistency
//! checks alone are not proof of reviewer identity.

use std::error::Error as StdError;
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_worker_host::model_worker::read_shadow_granite_v3_v7;

const MAX_ADMISSION_BYTES: u64 = 1_000_000;
const MAX_SOURCE_BYTES: u64 = 65_536;
const MAX_EXPORT_BYTES: u64 = 2_500_000;
const MAX_REVIEW_BYTES: u64 = 65_536;

/// Bounds the actual number of input bytes read, independently of reported
/// metadata size. This is research CLI preflight, NOT a symlink-race proof.
fn read_one(path: &str, maximum: u64) -> Result<Vec<u8>, Box<dyn StdError>> {
    let file_path = Path::new(path);
    if !file_path.is_absolute() {
        return Err("absolute, independently admitted local input path required".into());
    }
    let metadata = std::fs::symlink_metadata(file_path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err("invalid, linked or oversized input file".into());
    }
    let mut data = Vec::new();
    File::open(file_path)?
        .take(maximum + 1)
        .read_to_end(&mut data)?;
    if data.is_empty() || data.len() as u64 > maximum {
        return Err("read exceeded its admitted byte bound".into());
    }
    Ok(data)
}

fn main() -> Result<(), Box<dyn StdError>> {
    let mut admission = None;
    let mut source = None;
    let mut export = None;
    let mut review = None;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-granite-v3-shadow --admission ABS_OWNER_JSON \
                 --original-source ABS_SOURCE_FILE --export ABS_EXPORT_JSON \
                 --review ABS_INDEPENDENT_REVIEW_JSON\n\
                 Research-only immutable data/CPU Reader validation. \
                 No model weights, unsigned grants, GPU or external effects."
            );
            return Ok(());
        }
        let value = args.next().ok_or("missing path for research input")?;
        match flag.as_str() {
            "--admission" if admission.is_none() => admission = Some(value),
            "--original-source" if source.is_none() => source = Some(value),
            "--export" if export.is_none() => export = Some(value),
            "--review" if review.is_none() => review = Some(value),
            _ => return Err(format!("duplicate or unexpected CLI flag: {flag}").into()),
        }
    }
    let admission_bytes = read_one(
        &admission.ok_or("--admission is required")?,
        MAX_ADMISSION_BYTES,
    )?;
    let original_bytes = read_one(
        &source.ok_or("--original-source is required")?,
        MAX_SOURCE_BYTES,
    )?;
    let export_bytes = read_one(&export.ok_or("--export is required")?, MAX_EXPORT_BYTES)?;
    let review_bytes = read_one(&review.ok_or("--review is required")?, MAX_REVIEW_BYTES)?;

    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let report = read_shadow_granite_v3_v7(
        &admission_bytes,
        &original_bytes,
        &export_bytes,
        &review_bytes,
        now_ms,
    )?;
    if report.authority != "DENY_ALL" || report.production_authorized || report.model_selected {
        return Err("research data path unexpectedly requested a production grant".into());
    }
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}
